"""Capture and replay a scenario baseline.

    uv run capture-baseline --database data/warehouse/energy.duckdb
    uv run replay-baseline  --baseline data/baselines/<id>.json

Replay always builds a **fresh** database from the members the baseline names, after
checking each member's decompressed content digest. It reports every field it compared,
and exits non-zero if any differs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..ingest.warehouse import DEFAULT_DATABASE
from ..profiling.reader import DEFAULT_ARCHIVE
from .baseline import (
    BASELINE_DIR,
    BaselineError,
    capture,
    describe_environment_drift,
    replay,
)
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(capture_main())
