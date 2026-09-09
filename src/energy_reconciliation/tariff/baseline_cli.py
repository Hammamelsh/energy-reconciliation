"""Capture and replay a scenario baseline, in either format.

**Format 1 — the Python scenario** (unchanged)::

    uv run capture-baseline --database data/warehouse/energy.duckdb
    uv run replay-baseline  --baseline data/baselines/<id>.json

**Format 2 — a published dbt build**::

    uv run capture-published-baseline --root data/published
    uv run replay-published-baseline  --baseline data/baselines/pub2-<id>.json \
        --into data/proof-scratch/replay-<id>

Both replays build into a **fresh** destination from the members the baseline names,
after checking each member's decompressed content digest, and neither copies anything
from the result it is checking. Format 2 additionally runs the supported
``build-candidate`` path, so its rebuild is a real dbt build with every model and test.

Exit status is the same in both: ``0`` reproduced, ``1`` compared and differed, ``2``
could not reproduce (missing artifact, wrong format, destination in the way, failed
build). The two formats refuse each other's files by name and by version.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..ingest.warehouse import DEFAULT_DATABASE
from ..profiling.reader import DEFAULT_ARCHIVE
from ..publication import DEFAULT_ROOT as DEFAULT_PUBLICATION_ROOT
from ..publication import PublicationError
from . import published_baseline as pub2
from .baseline import (
    BASELINE_DIR,
    BaselineError,
    capture,
    describe_environment_drift,
    replay,
)
from .reads import ReadContextError
from .schedule import DEFAULT_WORKBOOK


def capture_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="capture-baseline",
        description=(
            "Record the published scenario result, its exact input members and the "
            "calculation identity, so a later result can be explained rather than "
            "merely compared."
        ),
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--directory", type=Path, default=BASELINE_DIR)
    args = parser.parse_args(argv)
    try:
        path = capture(args.database, args.directory)
    except BaselineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    data = json.loads(path.read_text())
    members = data["inputs"]["members"]
    print(f"baseline : {path}")
    print(f"id       : {data['baseline_id']}")
    print(f"inputs   : {len(members)} member(s)")
    for member in members:
        print(
            f"    {member['member_name']}  content {member['member_content_sha256'][:12]}…"
            f"  {member['records_published']:,} published"
        )
    schedule = data["inputs"]["schedule"]
    print(
        f"schedule : {schedule['source']} {schedule['sha256'][:12]}… "
        f"({schedule['rows']:,} labels)"
    )
    print(f"charged  : {data['output']['included_readings']:,}")
    print(f"excluded : {data['output']['excluded_readings']:,}")
    print(f"charge   : GBP {data['output']['total_energy_charge_gbp_exact']}")
    print()
    print("Reproduce from these inputs alone, into a database that does not yet exist:")
    print(
        f"  uv run replay-baseline --baseline {path} "
        f"--database data/warehouse/replay-{data['baseline_id']}.duckdb"
    )
    return 0


def replay_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="replay-baseline",
        description=(
            "Rebuild a captured scenario from its recorded input members into a fresh "
            "database, and compare the result field by field."
        ),
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="a database path that does not exist yet (default: derived from the id)",
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    args = parser.parse_args(argv)

    if not args.baseline.exists():
        print(f"error: baseline not found: {args.baseline}", file=sys.stderr)
        return 2
    database = args.database
    if database is None:
        ident = json.loads(args.baseline.read_text())["baseline_id"]
        database = Path("data/warehouse") / f"replay-{ident}.duckdb"
    try:
        differences, baseline = replay(
            args.baseline, database, args.archive, args.workbook
        )
    except BaselineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"baseline : {baseline['baseline_id']} captured {baseline['captured_at_utc']}"
    )
    print(f"replayed : {database}")
    print(
        f"inputs   : {baseline['inputs']['member_count']} member(s), digests verified"
    )
    print()
    print("environment recorded vs replaying (reported, not enforced):")
    for drift in describe_environment_drift(baseline):
        mark = "  same" if drift.matches else "  DIFFERS"
        shown = (
            drift.baseline if len(drift.baseline) < 24 else drift.baseline[:16] + "…"
        )
        got = drift.replay if len(drift.replay) < 24 else drift.replay[:16] + "…"
        print(f"{mark:<10} {drift.field:<34} {shown} -> {got}")
    print()
    print("result comparison:")
    failed = [d for d in differences if not d.matches]
    for difference in differences:
        mark = "  match " if difference.matches else "  DIFFER"
        print(
            f"{mark} {difference.field:<44} {difference.baseline} | {difference.replay}"
        )
    print()
    print(f"compared {len(differences)} field(s); {len(failed)} differ")
    if failed:
        print("REPLAY DID NOT REPRODUCE THE BASELINE.")
        return 1
    print("REPLAY REPRODUCED THE BASELINE EXACTLY.")
    return 0


# ------------------------------------------------------- format 2: published dbt build
def capture_published_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="capture-published-baseline",
        description=(
            "Record the PUBLISHED dbt result as a format-2 baseline: its input members, "
            "schedule, calculation and runtime identity, and the exact outputs a rebuild "
            "must reproduce. Read through the validated publication contract."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PUBLICATION_ROOT,
        help=f"publication root to record (default: {DEFAULT_PUBLICATION_ROOT})",
    )
    parser.add_argument("--directory", type=Path, default=BASELINE_DIR)
    args = parser.parse_args(argv)
    try:
        path = pub2.capture(args.root, args.directory)
    except (BaselineError, PublicationError, ReadContextError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    data = json.loads(path.read_text())
    inputs, outputs = data["inputs"], data["outputs"]
    print(f"baseline : {path}")
    print(f"id       : {data['baseline_id']}  (format {data['format_version']})")
    print(
        f"published: {data['execution']['publication_version']} "
        f"{data['execution']['version_file']}"
    )
    print(f"dbt run  : {data['execution']['run_id']}")
    print(
        f"build    : {data['calculation']['required_build']}, "
        f"{data['calculation']['required_nodes_total']} required nodes"
    )
    print(f"inputs   : {inputs['member_count']} member(s)")
    for member in inputs["members"]:
        print(
            f"    {member['member_name']}  content "
            f"{member['member_content_sha256'][:12]}…  "
            f"{member['records_published']:,} published"
        )
    schedule = inputs["schedule"]
    print(
        f"schedule : {schedule['source']} {str(schedule['source_sha256'])[:12]}… "
        f"({schedule['rows']:,} labels, variant {schedule['variant']})"
    )
    print(f"charged  : {outputs['accounting']['included_readings']:,}")
    print(f"excluded : {outputs['accounting']['excluded_readings']:,}")
    print(f"charge   : GBP {outputs['total_energy_charge_gbp_exact']}")
    print()
    print(
        "Rebuild from these inputs alone, into a destination that does not yet exist:"
    )
    print(f"  uv run replay-published-baseline --baseline {path} \\")
    print(f"      --into data/proof-scratch/replay-{data['baseline_id']}")
    return 0


def replay_published_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="replay-published-baseline",
        description=(
            "Rebuild a format-2 baseline from its recorded members by re-ingesting them "
            "and running the supported build-candidate path, then compare every input, "
            "identity and output. Nothing is copied from the original publication."
        ),
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument(
        "--into",
        type=Path,
        default=None,
        help="a directory that does not exist yet (default: derived from the id)",
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--project-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.baseline.exists():
        print(f"error: baseline not found: {args.baseline}", file=sys.stderr)
        return 2
    into = args.into
    if into is None:
        try:
            ident = json.loads(args.baseline.read_text())["baseline_id"]
        except (OSError, ValueError, KeyError) as exc:
            print(f"error: {args.baseline}: {exc}", file=sys.stderr)
            return 2
        into = Path("data/proof-scratch") / f"replay-{ident}"

    try:
        result = pub2.replay(
            args.baseline, into, args.archive, args.workbook, args.project_dir
        )
    except BaselineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    baseline = result.baseline
    print(
        f"baseline : {baseline['baseline_id']} captured {baseline['captured_at_utc']}"
    )
    print(f"rebuilt  : {result.candidate}")
    print(
        f"inputs   : {baseline['inputs']['member_count']} member(s), digests verified "
        f"before any build"
    )
    print()
    print("execution provenance (expected to differ, never compared):")
    print(f"  recorded run  {baseline['execution']['run_id']}")
    print(f"  rebuilt  run  {result.run_id}")
    print()
    print("comparison:")
    for difference in result.differences:
        mark = "  match " if difference.matches else "  DIFFER"
        shown = difference.baseline
        got = difference.replay
        if difference.matches and len(shown) > 60:
            shown, got = shown[:57] + "…", got[:57] + "…"
        print(
            f"{mark} {difference.field:<52} {shown}"
            + ("" if difference.matches else f"\n{'':<9}{'':<52} != {got}")
        )
    print()
    failed = result.failed
    print(f"compared {len(result.differences)} field(s); {len(failed)} differ")
    if failed:
        print("REBUILD DID NOT REPRODUCE THE BASELINE.")
        return 1
    print("REBUILD REPRODUCED THE PUBLISHED RESULT EXACTLY.")
    print(
        "Reproduced means: same inputs, same calculation and runtime identity, and "
        "every logical output identical -- schemas, row counts, every row, the "
        "accounting ladder and the exact decimal totals. Execution provenance (run "
        "ids, timestamps, paths, file bytes) is new by construction."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(capture_main())
