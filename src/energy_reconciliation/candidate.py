"""Build one publication candidate: snapshot, build, validate, seal.

Before this existed the workflow was assembled by hand -- a ``COPY FROM DATABASE``
snapshot, then ``run-dbt`` against the copy, then ``publication finalise``. Each step is
easy to get subtly wrong, and two of the ways to get it wrong were measured rather than
imagined:

- a snapshot of a warehouse that has itself been built **inherits its build history**, so
  a file that was never built as a candidate carried a record saying it had been;
- a second build attempt in the same file leaves the first attempt's record standing over
  tables the second attempt partly replaced.

So this command owns the lifecycle instead. Every invocation writes a **new** file, clears
any inherited build schema, builds once, and seals only if that build and its tests
passed. A failed stage exits non-zero, names the stage and the file, and leaves the file
unsealed for inspection -- never retried in place.

**It does not promote.** A successful run reports a candidate that is *ready for
promotion*; the manifest and whatever the dashboard reads are untouched. Promotion stays
a separate, deliberate act (``publication promote``).

**What the seal certifies.** ``run-dbt`` records a ``started`` attempt before dbt runs and
completes it afterwards; ``finalise`` seals only when the **latest** attempt succeeded in
this file and the tables still digest as it recorded. So a failed or interrupted attempt
after a success is refused even when the tables are unchanged -- attempt success and output
equality are separate facts. The recorded identity covers what actually produces the
tables: the published calculation files plus ``tariff/dimensions.py``, the dbt project and
the dbt, DuckDB, PyArrow and pandas versions (``tariff/candidate_identity.py``).

**Outside the lifecycle**: running ``dbt`` directly or editing the database by hand records
no attempt. Content checks -- the output digest at sealing and the whole-file SHA-256 after
it -- are what catch those; the attempt record cannot.

**Still not done**: the dashboard reads no candidate; the published scenario is still the
Python one and its identity (``identity.py``) is unchanged; baselines are format 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import duckdb

from . import dbt_run, publication
from .dbt_macros import repository_root
from .ingest.warehouse import DEFAULT_DATABASE
from .tariff import prices as pr

#: Where ingestion writes. A candidate may never be created here: these files are the
#: mutable source of truth, and a build must not be able to touch one.
WAREHOUSE_DIR: Final[Path] = Path("data/warehouse")

#: Stages, in order. A failure reports the one it was in.
VALIDATE, SNAPSHOT, BUILD, SEAL = "validate", "snapshot", "build", "seal"


class CandidateError(RuntimeError):
    """A stage failed. Carries the stage and, once one exists, the candidate path."""

    def __init__(self, stage: str, message: str, candidate: Path | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.candidate = candidate


@dataclass(frozen=True, slots=True)
class Built:
    """A sealed candidate, ready for promotion and not promoted."""

    candidate: Path
    seal: publication.Seal
    models: int
    tests: int
    source: Path


def default_candidate_path(root: Path, when: datetime) -> Path:
    """A fresh file name per invocation. Never reused, so a retry cannot be in place."""
    return (
        root / publication.VERSIONS / f"cand-{when.strftime('%Y%m%dT%H%M%S%f')}.duckdb"
    )


def _validate_source(source: Path) -> Path:
    """A loaded warehouse, or a refusal that created nothing.

    Delegates to the guarded runner's own preflight, which orders its checks so that
    nothing can bring the file into existence: string, then ``exists``, then a read-only
    connection, which DuckDB never creates a file for.
    """
    try:
        return dbt_run.validated_database(str(source))
    except dbt_run.DatabasePathError as error:
        raise CandidateError(VALIDATE, str(error)) from error


def _validate_destination(candidate: Path, source: Path, root: Path) -> None:
    """Refuse anything that would overwrite work or build in the wrong place."""
    # Identity first, then existence: "you asked to build over the published version" is
    # a more useful refusal than "that file exists", and both are true of it.
    if candidate.resolve() == source.resolve():
        raise CandidateError(
            VALIDATE, f"the candidate and the source are the same file ({source})."
        )
    try:
        in_warehouse = candidate.resolve().is_relative_to(WAREHOUSE_DIR.resolve())
    except (OSError, ValueError):  # pragma: no cover - resolve on a missing parent
        in_warehouse = False
    if in_warehouse:
        raise CandidateError(
            VALIDATE,
            f"{candidate} is inside {WAREHOUSE_DIR}, where ingestion writes. A candidate "
            "must never be able to overwrite a source warehouse.",
        )
    manifest = publication.read_manifest(root)
    if manifest and candidate.name == manifest["file"]:
        raise CandidateError(
            VALIDATE,
            f"{candidate.name} is the published version ({manifest['version']}). "
            "Published versions are immutable.",
        )
    if publication._seal_path(candidate).exists():
        raise CandidateError(
            VALIDATE, f"{candidate.name} already has a seal beside it; refusing."
        )
    if candidate.exists():
        raise CandidateError(
            VALIDATE,
            f"{candidate} already exists. Every build gets a fresh file: a failed "
            "candidate is evidence, and rebuilding in place is what lets an old success "
            "record outlive the tables it described.",
            candidate,
        )
    candidate.parent.mkdir(parents=True, exist_ok=True)


def _snapshot(source: Path, candidate: Path) -> None:
    """A consistent copy, source attached READ_ONLY so it cannot be written.

    The read-only attach is also the lock check: it is refused while another process
    holds the warehouse read-write, and that is reported as what it is rather than
    retried, because the only writer that can hold it is an ingestion in progress.
    """
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"ATTACH '{source}' AS src (READ_ONLY)")
        con.execute(f"ATTACH '{candidate}' AS dst")
        con.execute("COPY FROM DATABASE src TO dst")
    except duckdb.IOException as error:
        candidate.unlink(missing_ok=True)
        raise CandidateError(
            SNAPSHOT,
            f"could not read {source}: {error}. Another process holds it read-write -- "
            "an ingestion is most likely running. Nothing was built; try again after it "
            "finishes.",
            candidate,
        ) from error
    except duckdb.Error as error:
        raise CandidateError(
            SNAPSHOT, f"{source} -> {candidate}: {error}", candidate
        ) from error
    finally:
        con.close()


def _clear_inherited_build(candidate: Path) -> list[str]:
    """Drop any build schema the snapshot inherited, and say what was dropped.

    Measured: ``COPY FROM DATABASE`` copies ``scenario_build`` whole, build record
    included. A candidate that starts with someone else's build history can be sealed on
    the strength of a build that happened in a different file, so it starts with none.
    """
    con = duckdb.connect(str(candidate))
    try:
        inherited = [
            name
            for (name,) in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                [dbt_run.BUILD_SCHEMA],
            ).fetchall()
        ]
        if inherited:
            con.execute(f"DROP SCHEMA {dbt_run.BUILD_SCHEMA} CASCADE")
    finally:
        con.close()
    return sorted(inherited)


def _run_results(target: Path) -> tuple[int, int]:
    """Models and tests that dbt reported as passing, from its own run results."""
    path = target / "run_results.json"
    if not path.is_file():
        raise CandidateError(BUILD, f"dbt wrote no run results at {path}")
    results = json.loads(path.read_text())["results"]

    def passing(kind: str) -> int:
        # dbt reports a model as "success" and a test as "pass"; both count only when
        # the node is of the kind asked for, so a model-only run cannot look tested.
        return sum(
            1
            for r in results
            if r["unique_id"].startswith(f"{kind}.")
            and r["status"] in {"success", "pass"}
        )

    return passing("model"), passing("test")


def build_candidate(
    source: Path = DEFAULT_DATABASE,
    *,
    schedule: str = dbt_run.WORKBOOK_VARIANT,
    workbook: str = "",
    tariff_group: str = pr.TOU_GROUP,
    root: Path = publication.DEFAULT_ROOT,
    candidate: Path | None = None,
    project_dir: Path | None = None,
    when: datetime | None = None,
) -> Built:
    """Snapshot, build, validate and seal one candidate. Never promotes."""
    when = when or datetime.now(UTC).replace(tzinfo=None)
    project_dir = project_dir or (repository_root() / "dbt")
    source = _validate_source(source)
    candidate = candidate or default_candidate_path(root, when)
    _validate_destination(candidate, source, root)

    _snapshot(source, candidate)
    _clear_inherited_build(candidate)

    # absolute: dbt resolves a relative --target-path against --project-dir, not the
    # working directory, which would put the run results somewhere unexpected.
    target = candidate.with_name(candidate.stem + "-target").resolve()
    code = dbt_run.main(
        [
            "--database",
            str(candidate),
            "--project-dir",
            str(project_dir),
            "--schedule",
            schedule,
            "--workbook",
            workbook,
            "--tariff-group",
            tariff_group,
            "build",
            "--target-path",
            str(target),
        ]
    )
    if code != 0:
        raise CandidateError(
            BUILD,
            f"dbt exited {code}; the attempt is recorded as failed and the candidate "
            f"is unsealed. Inspect it, then build a fresh one -- this file is not reused.",
            candidate,
        )
    models, tests = _run_results(target)
    if tests == 0:
        raise CandidateError(
            BUILD,
            "the build reported no passing tests. A candidate is sealed on models *and* "
            "tests; a model-only selection is not enough.",
            candidate,
        )
    try:
        seal = publication.finalise(candidate)
    except (publication.PublicationError, OSError) as error:
        # A refusal, or the sidecar could not be written. The succeeded attempt is still
        # recorded in the file, so `publication finalise <candidate>` can retry sealing
        # once the cause is fixed -- and it re-validates everything before it does.
        raise CandidateError(
            SEAL,
            f"{error} -- the build succeeded and is recorded; retry with "
            f"`uv run publication finalise {candidate}` once the cause is fixed.",
            candidate,
        ) from error
    return Built(
        candidate=candidate, seal=seal, models=models, tests=tests, source=source
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build-candidate",
        description=(
            "Create an isolated warehouse candidate from an ingestion warehouse, build "
            "it with dbt and seal it if the build and its tests pass. Does not promote."
        ),
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"ingestion warehouse to snapshot (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument("--root", type=Path, default=publication.DEFAULT_ROOT)
    parser.add_argument(
        "--candidate",
        type=Path,
        default=None,
        help="explicit candidate path; must not exist",
    )
    parser.add_argument(
        "--schedule",
        choices=dbt_run.SCHEDULE_VARIANTS,
        default=dbt_run.WORKBOOK_VARIANT,
        help=(
            f"{dbt_run.WORKBOOK_VARIANT}: the publisher's Tariffs.xlsx. "
            f"{dbt_run.DEMO_VARIANT}: the project's INVENTED schedule."
        ),
    )
    parser.add_argument("--workbook", default="", help="explicit workbook path")
    parser.add_argument("--tariff-group", default=pr.TOU_GROUP)
    args = parser.parse_args(argv)

    try:
        built = build_candidate(
            args.source,
            schedule=args.schedule,
            workbook=args.workbook,
            tariff_group=args.tariff_group,
            root=args.root,
            candidate=args.candidate,
        )
    except CandidateError as error:
        where = f" candidate: {error.candidate}" if error.candidate else ""
        print(f"build-candidate: [{error.stage}] {error}{where}", file=sys.stderr)
        return 1
    manifest = publication.read_manifest(args.root)
    print(
        f"sealed {built.candidate}\n"
        f"  run {built.seal.run_id}\n"
        f"  {built.models} models, {built.tests} tests passed · schedule "
        f"{built.seal.schedule_variant} · group {built.seal.tariff_group}\n"
        f"  sha256 {built.seal.sha256[:16]}…\n"
        f"READY FOR PROMOTION -- not published. The published version is still "
        f"{manifest['version'] if manifest else 'none'}. To publish it:\n"
        f"  uv run publication --root {args.root} promote {built.candidate} "
        f"--expect-published {manifest['version'] if manifest else 'none'}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
