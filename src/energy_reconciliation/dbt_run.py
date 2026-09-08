"""The supported way to run this project's dbt models, and the only guarded one.

Why a wrapper exists
--------------------

``dbt`` is given a DuckDB *file path*. DuckDB creates a database at any path it is
handed, so a typo, an unset variable or a stale shell produces an **empty warehouse** and
a build that succeeds against nothing. The project's ``on-run-start`` hook catches the
wrong-database case, but only after the adapter has opened -- and therefore created -- the
file. By then the damage is a stray empty database on disk.

This wrapper closes that window: it validates the path **before** anything can open it,
using ``Path.exists`` and then a **read-only** connection, which DuckDB never creates a
file for. A wrong path is refused with nothing written.

**This guarantee belongs to this entry point, not to dbt.** Running ``dbt`` directly is
still possible and still useful, and it is *not* protected: it will create an empty file
at a wrong path before the in-project hook rejects it. The hook remains as the backstop
for that route. Neither the wrapper nor the hook is a substitute for the other.

What it records
---------------

The tariff dimensions are now **persisted tables built by dbt**, so which dbt produced
them is part of what they are. After a successful build this writes one row to
``scenario_build.dbt_build_run``: the dbt versions, the digests of the code and project
files that shaped the output, and the schedule variant.

That record is deliberately **separate from ``scenario_run``**. These dimensions are
*candidate* outputs: the published tariff scenario is still built by
``build-tariff-scenario``, reads its own dimensions, and is untouched by anything here.
Folding dbt into the published run's fingerprint before dbt produces a published figure
would claim a dependency that does not exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Final

import duckdb

from .dbt_macros import repository_root
from .tariff import identity
from .tariff import prices as pr
from .tariff.dimensions import (
    DEMO_VARIANT,
    SCHEDULE_VARIANTS,
    WORKBOOK_VARIANT,
)

#: The schema every dbt model is built into. Never ``main``: the warehouse's own tables
#: are written by ingestion, and a dbt run must not be able to replace one.
BUILD_SCHEMA: Final[str] = "scenario_build"

#: Where the build identity is recorded. Not ``scenario_run`` -- see the module docstring.
BUILD_RUN_TABLE: Final[str] = f"{BUILD_SCHEMA}.dbt_build_run"

#: Files whose bytes shape a dbt output. Directories that hold build artefacts, logs and
#: a per-machine identifier are not among them.
_PROJECT_GLOBS: Final[tuple[str, ...]] = ("dbt_project.yml", "models/**/*", "macros/*")

#: dbt packages recorded with every build.
DBT_PACKAGES: Final[tuple[str, ...]] = ("dbt-core", "dbt-duckdb")

#: Prefix on every run_id this wrapper generates. A candidate build is not a published
#: scenario run and its identifiers must never be mistaken for one in a query or a log.
CANDIDATE_PREFIX: Final[str] = "dbtcand"

#: Columns of the build record. A stored table with a different shape is dropped and
#: rebuilt rather than migrated: it is a log of candidate builds, derivable by rebuilding,
#: and guessing at a migration would be the riskier choice.
_BUILD_RUN_COLUMNS: Final[tuple[str, ...]] = (
    "run_id",
    "built_at_utc",
    "dbt_core_version",
    "dbt_duckdb_version",
    "python_version",
    "target_schema",
    "schedule_variant",
    "tariff_group",
    "dbt_command",
    "dbt_project_sha256",
    "macro_sha256",
    "policy_sha256",
    "calculation_code_sha256",
    "note",
)


def candidate_run_id(project: Path, when: datetime) -> str:
    """An identifier for one candidate build, keyed by what produced it."""
    material = "::".join(
        [
            project_digest(project),
            identity.calculation_digest(),
            identity.policy_digest(),
        ]
    )
    return (
        f"{CANDIDATE_PREFIX}-{hashlib.sha256(material.encode()).hexdigest()[:12]}"
        f"@{when.strftime('%Y%m%dT%H%M%S%f')}"
    )


class DatabasePathError(ValueError):
    """The database path is unusable, and nothing was opened or created because of it."""


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - only if uninstalled
        return "absent"


def dbt_identity() -> dict[str, str]:
    """The dbt versions that rendered and executed the models."""
    return {name: _package_version(name) for name in DBT_PACKAGES}


def project_digest(project: Path | None = None) -> str:
    """A digest over the dbt project files that can change an output.

    ``target/``, ``logs/`` and ``.user.yml`` are excluded: they are artefacts of running,
    not inputs to it, and ``.user.yml`` is a per-machine identifier that would make the
    digest differ between machines for identical projects.
    """
    root = project or (repository_root() / "dbt")
    paths: list[Path] = []
    for pattern in _PROJECT_GLOBS:
        paths.extend(p for p in root.glob(pattern) if p.is_file())
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def validated_database(raw: str | None) -> Path:
    """The database to build against, or a refusal that created nothing.

    Every check here is ordered so that no step can bring the file into existence:
    string checks first, then ``exists``, then a **read-only** connection, which DuckDB
    will not create a file for.
    """
    if raw is None or not raw.strip():
        msg = (
            "no database given. Pass --database, or set ENERGY_RECONCILIATION_DB. "
            "There is deliberately no default: DuckDB creates a database at whatever "
            "path it is handed, and an empty one would build successfully against "
            "nothing."
        )
        raise DatabasePathError(msg)

    path = Path(raw).expanduser()
    if not path.exists():
        msg = (
            f"{path} does not exist. Refusing to run: dbt would have created an empty "
            "database here and every model would have succeeded with zero rows. Load a "
            "warehouse first, or copy one (ATTACH ... (READ_ONLY) + COPY FROM DATABASE)."
        )
        raise DatabasePathError(msg)
    if not path.is_file():
        raise DatabasePathError(f"{path} is not a file.")
    if path.stat().st_size == 0:
        msg = f"{path} is empty (0 bytes), so it is not a DuckDB database."
        raise DatabasePathError(msg)

    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as error:  # not a DuckDB database, or locked by another process
        msg = f"{path} could not be opened read-only: {error}"
        raise DatabasePathError(msg) from error
    try:
        found = con.execute(
            "SELECT COUNT(*) FROM duckdb_tables() "
            "WHERE schema_name = 'main' AND table_name = 'readings'"
        ).fetchone()[0]
    finally:
        con.close()
    if not found:
        msg = (
            f"{path} has no main.readings table, so it is not a loaded warehouse. "
            "Run `uv run ingest-member` first."
        )
        raise DatabasePathError(msg)
    return path


def _dbt_command() -> list[str]:
    executable = Path(sys.executable).with_name("dbt")
    return (
        [str(executable)]
        if executable.is_file()
        else [sys.executable, "-m", "dbt.cli.main"]
    )


def record_build(
    database: Path,
    schedule: str,
    command: list[str],
    project: Path,
    run_id: str,
    when: datetime,
    tariff_group: str,
) -> dict[str, Any]:
    """Write one row describing the build that just succeeded.

    Opened read-write only after dbt has finished and released the file lock.

    **Only successful builds are recorded, and a record does not certify the tables
    afterwards.** dbt fails per model, so a later partial rebuild can leave some candidate
    tables refreshed and others as they were, while this table still shows the earlier
    success. The row says what produced a build, not what the schema currently holds.
    """
    record = {
        "run_id": run_id,
        "built_at_utc": when,
        "dbt_core_version": dbt_identity()["dbt-core"],
        "dbt_duckdb_version": dbt_identity()["dbt-duckdb"],
        "python_version": identity.runtime_identity()["python"],
        "target_schema": BUILD_SCHEMA,
        "schedule_variant": schedule,
        "tariff_group": tariff_group,
        "dbt_command": " ".join(command),
        "dbt_project_sha256": project_digest(project),
        "macro_sha256": hashlib.sha256(
            (project / "macros" / "generated_policy.sql").read_bytes()
        ).hexdigest(),
        "policy_sha256": identity.policy_digest(),
        "calculation_code_sha256": identity.calculation_digest(),
        "note": (
            "Candidate dbt outputs. NOT the published tariff scenario: that is built by "
            "build-tariff-scenario, reads its own dimensions, and does not consume "
            "anything in this schema. A row here records a build that succeeded; it does "
            "not certify what the schema holds after any later partial rebuild."
        ),
    }
    assert tuple(record) == _BUILD_RUN_COLUMNS
    con = duckdb.connect(str(database))
    try:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {BUILD_SCHEMA}")
        existing = tuple(
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE "
                f"table_schema = '{BUILD_SCHEMA}' AND table_name = 'dbt_build_run' "
                "ORDER BY ordinal_position"
            ).fetchall()
        )
        if existing and existing != _BUILD_RUN_COLUMNS:
            print(f"rebuilding {BUILD_RUN_TABLE}: recorded shape is out of date")
            con.execute(f"DROP TABLE {BUILD_RUN_TABLE}")
        columns = ",\n                ".join(
            f"{name:24s} {'TIMESTAMP' if name.endswith('_utc') else 'VARCHAR'} NOT NULL"
            for name in _BUILD_RUN_COLUMNS
        )
        con.execute(f"CREATE TABLE IF NOT EXISTS {BUILD_RUN_TABLE} (\n{columns}\n)")
        placeholders = ",".join("?" * len(_BUILD_RUN_COLUMNS))
        con.execute(
            f"INSERT INTO {BUILD_RUN_TABLE} VALUES ({placeholders})",
            list(record.values()),
        )
    finally:
        con.close()
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run-dbt",
        description=(
            "Run this project's dbt models against a warehouse, validating the database "
            "path before anything can create it."
        ),
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("ENERGY_RECONCILIATION_DB"),
        help="DuckDB warehouse to build against (default: $ENERGY_RECONCILIATION_DB)",
    )
    parser.add_argument(
        "--schedule",
        choices=SCHEDULE_VARIANTS,
        default=WORKBOOK_VARIANT,
        help=(
            f"{WORKBOOK_VARIANT}: the publisher's Tariffs.xlsx. "
            f"{DEMO_VARIANT}: the project's INVENTED schedule, recorded as "
            "'synthetic-demo' on every row it produces."
        ),
    )
    parser.add_argument("--workbook", default="", help="explicit workbook path")
    parser.add_argument(
        "--tariff-group",
        default=pr.TOU_GROUP,
        help=f"tariff group the scenario is scoped to (default: {pr.TOU_GROUP})",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=repository_root() / "dbt",
        help="dbt project to run (default: this repository's dbt/)",
    )
    args, passthrough = parser.parse_known_args(argv)

    try:
        database = validated_database(args.database)
    except DatabasePathError as error:
        print(f"run-dbt: {error}", file=sys.stderr)
        return 2

    when = datetime.now(UTC).replace(tzinfo=None)
    run_id = candidate_run_id(args.project_dir, when)
    dbt_args = passthrough or ["build"]
    command = [
        *_dbt_command(),
        *dbt_args,
        "--project-dir",
        str(args.project_dir),
        "--profiles-dir",
        str(args.project_dir),
        "--vars",
        json.dumps(
            {
                "schedule": args.schedule,
                "workbook": args.workbook,
                "tariff_group": args.tariff_group,
                "run_id": run_id,
            }
        ),
    ]
    # argv is built here and no shell is involved.
    completed = subprocess.run(
        command,
        env={**os.environ, "ENERGY_RECONCILIATION_DB": str(database)},
        check=False,
    )
    if completed.returncode != 0:
        print(
            f"run-dbt: dbt exited {completed.returncode}; no build was recorded.",
            file=sys.stderr,
        )
        return completed.returncode

    record = record_build(
        database,
        args.schedule,
        dbt_args,
        args.project_dir,
        run_id,
        when,
        args.tariff_group,
    )
    print(
        f"recorded in {BUILD_RUN_TABLE}: {record['run_id']} · dbt-core "
        f"{record['dbt_core_version']}, dbt-duckdb {record['dbt_duckdb_version']}, "
        f"schedule {record['schedule_variant']}, group {record['tariff_group']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
