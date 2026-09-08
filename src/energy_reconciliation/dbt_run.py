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

The tariff dimensions and facts are **persisted tables built by dbt**, so which dbt
produced them, from which code, is part of what they are. Every invocation of this wrapper
writes an **attempt** row to ``scenario_build.dbt_build_run`` **before** dbt runs, and
completes it afterwards:

- ``started`` -- written before dbt is invoked, with the run identity (dbt, Python and
  library versions, the digests of every file that shapes an output, the resolved
  variables) and the **path of the file it was recorded in**. The connection is closed
  before dbt starts: DuckDB locks the file, and dbt could not open it otherwise.
- ``succeeded`` -- dbt exited 0. The row gains a digest of the built tables (see
  :func:`build_output_digest`) and the schedule and catalogue identity read from the
  dimension rows dbt wrote.
- ``failed`` -- dbt exited non-zero. Recorded when this process survives to record it.

An attempt left ``started`` -- this process was killed while dbt ran, or dbt is still
running -- is neither a success nor a recorded failure, and ``publication.finalise``
treats it as ineligible. A refusal **before** an attempt begins (an unusable path, a sealed
read-only file, a legacy record shape) records nothing, because nothing was attempted.

**The enforcement boundary, stated plainly.** Attempts are recorded by this entry point
and by ``build-candidate``, which calls it. Running ``dbt`` directly, or editing the
database by hand, is outside the lifecycle: such a change is not an attempt and leaves no
row. What catches it is content, not history -- ``finalise`` recomputes the output digest
against the latest succeeded attempt and refuses a mismatch, and the seal's whole-file
SHA-256 catches any change after sealing.

That record is deliberately **separate from ``scenario_run``**. These are *candidate*
outputs: the published tariff scenario is still built by ``build-tariff-scenario``, reads
its own dimensions, and is untouched by anything here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb

from .dbt_macros import repository_root
from .tariff import candidate_identity as cid
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

#: dbt packages recorded with every build.
DBT_PACKAGES: Final[tuple[str, ...]] = cid.DBT_PACKAGES

#: Prefix on every run_id this wrapper generates. A candidate build is not a published
#: scenario run and its identifiers must never be mistaken for one in a query or a log.
CANDIDATE_PREFIX: Final[str] = "dbtcand"

#: Attempt states. ``started`` is the only state a row is created in.
STARTED, SUCCEEDED, FAILED = "started", "succeeded", "failed"

#: Identifies the canonicalisation :func:`build_output_digest` implements. Recorded with
#: every succeeded attempt and in the seal, and compared before a digest is compared, so
#: a digest from a different algorithm is refused as such rather than as a mismatch.
OUTPUT_DIGEST_VERSION: Final[str] = "canonical-rows-1"

#: Columns of the attempt record, in order, with their SQL types. NULL-able columns are
#: the ones a ``started`` row cannot know yet.
#:
#: A stored table with a different shape is a **legacy record** and is refused, by this
#: wrapper (nothing runs) and by ``publication.finalise`` (nothing seals), with the same
#: instruction: build a fresh candidate. It is never dropped or migrated in place, because
#: either would rewrite what an older build claimed.
_BUILD_RUN_SCHEMA: Final[tuple[tuple[str, str], ...]] = (
    ("run_id", "VARCHAR NOT NULL"),
    ("status", "VARCHAR NOT NULL"),
    ("started_at_utc", "TIMESTAMP NOT NULL"),
    ("finished_at_utc", "TIMESTAMP"),
    ("dbt_exit_code", "INTEGER"),
    ("database_path", "VARCHAR NOT NULL"),
    ("target_schema", "VARCHAR NOT NULL"),
    ("dbt_command", "VARCHAR NOT NULL"),
    ("dbt_vars", "VARCHAR NOT NULL"),
    ("schedule_variant", "VARCHAR NOT NULL"),
    ("tariff_group", "VARCHAR NOT NULL"),
    ("dbt_core_version", "VARCHAR NOT NULL"),
    ("dbt_duckdb_version", "VARCHAR NOT NULL"),
    ("python_version", "VARCHAR NOT NULL"),
    ("runtime_detail", "VARCHAR NOT NULL"),
    ("runtime_fingerprint", "VARCHAR NOT NULL"),
    ("dbt_project_sha256", "VARCHAR NOT NULL"),
    ("macro_sha256", "VARCHAR NOT NULL"),
    ("policy_sha256", "VARCHAR NOT NULL"),
    ("calculation_code_sha256", "VARCHAR NOT NULL"),
    ("covered_files", "VARCHAR NOT NULL"),
    ("schedule_source", "VARCHAR"),
    ("schedule_sha256", "VARCHAR"),
    ("schedule_rows", "INTEGER"),
    ("price_catalogue_version", "VARCHAR"),
    ("output_digest_version", "VARCHAR"),
    ("built_output_sha256", "VARCHAR"),
    ("note", "VARCHAR NOT NULL"),
)
_BUILD_RUN_COLUMNS: Final[tuple[str, ...]] = tuple(n for n, _ in _BUILD_RUN_SCHEMA)

#: Schema dbt builds into, and the one table in it that is not a build output.
_OUTPUT_SCHEMA: Final[str] = BUILD_SCHEMA
_RECORD_TABLE: Final[str] = "dbt_build_run"

_NOTE: Final[str] = (
    "Candidate dbt build attempts. NOT the published tariff scenario: that is built by "
    "build-tariff-scenario, reads its own dimensions, and consumes nothing in this "
    "schema. A row is written as 'started' before dbt runs and completed afterwards; "
    "only a 'succeeded' row that is the latest attempt, whose output digest still "
    "matches the tables, can be sealed."
)


class LegacyRecordError(RuntimeError):
    """``dbt_build_run`` exists with a shape this code does not write.

    Raised rather than migrated: an older row's claims are not upgraded to the current
    contract, and a fresh candidate is the supported way forward.
    """


class AttemptRefused(RuntimeError):
    """The attempt could not be recorded, so dbt was not invoked and nothing ran."""


def _quoted(name: str) -> str:
    """A catalogue identifier, double-quoted. Names come from the catalogue, never a caller."""
    return '"' + name.replace('"', '""') + '"'


def _canonical_rows_sql(schema: str, table: str, columns: list[str]) -> str:
    """Per-row SHA-256 of a self-delimiting text encoding, in digest order.

    Each column becomes ``N`` when NULL, else ``V<character length>:<text>`` where the text
    is DuckDB's own ``CAST(... AS VARCHAR)`` -- a DECIMAL keeps its scale (``0.6720``, never
    ``0.672``), a DATE is ``2013-01-01``, a TIMESTAMP ``2013-01-01 00:30:00``, a BOOLEAN
    ``true``. The length prefix makes the concatenation unambiguous whatever a string
    holds, and NULL is distinct from every string, the empty one included. Types are not
    in the row text; they are in the relation header the caller writes first.
    """
    tokens = [
        f"CASE WHEN {_quoted(c)} IS NULL THEN 'N' ELSE 'V' || "
        f"length(CAST({_quoted(c)} AS VARCHAR)) || ':' || CAST({_quoted(c)} AS VARCHAR) END"
        for c in columns
    ]
    expr = " || ".join(tokens) if tokens else "''"
    return (
        f"SELECT sha256({expr}) AS h FROM {_quoted(schema)}.{_quoted(table)} ORDER BY h"
    )


def build_output_digest(con) -> str:
    """A versioned, order-independent digest of what dbt actually left in the build schema.

    Recorded with a succeeded attempt and recomputed before a candidate is sealed. It
    covers every **base table** in ``scenario_build`` other than the attempt record, and
    for each one: its name, its ordered column names and types, its row count, and the
    sorted list of per-row SHA-256 hashes over the canonical encoding described in
    :func:`_canonical_rows_sql`. Sorting rather than summing is the point: a commutative
    summary such as ``bit_xor`` lets two rows cancel, so ``{1, 1, 2}`` and ``{2, 3, 3}``
    summarised identically. Here every row occurrence is present in the hashed stream, so
    duplicate multiplicity, any value, any column type or name, and the set of relations
    all move the digest, while physical row order does not.

    Memory is bounded on the Python side: rows are streamed in chunks, and the sort is
    DuckDB's. Views are excluded because their contents come from ``main``, which a build
    never writes. **This is a digest, not a proof of equality**: two different tables
    digesting the same is astronomically unlikely, not impossible, and migration evidence
    still comes from row-by-row comparison.
    """
    tables = [
        name
        for (name,) in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ? "
            "AND table_type = 'BASE TABLE' AND table_name <> ? ORDER BY table_name",
            [_OUTPUT_SCHEMA, _RECORD_TABLE],
        ).fetchall()
    ]
    digest = hashlib.sha256()
    digest.update(f"{OUTPUT_DIGEST_VERSION}\n".encode())
    for name in tables:
        columns = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [_OUTPUT_SCHEMA, name],
        ).fetchall()
        digest.update(f"relation\0{_OUTPUT_SCHEMA}.{name}\n".encode())
        for column, data_type in columns:
            digest.update(f"column\0{column}\0{data_type}\n".encode())
        (count,) = con.execute(
            f"SELECT COUNT(*) FROM {_quoted(_OUTPUT_SCHEMA)}.{_quoted(name)}"
        ).fetchone()
        digest.update(f"rows\0{count}\n".encode())
        cursor = con.execute(
            _canonical_rows_sql(_OUTPUT_SCHEMA, name, [c for c, _ in columns])
        )
        while chunk := cursor.fetchmany(65_536):
            digest.update("".join(f"{h}\n" for (h,) in chunk).encode())
    return digest.hexdigest()


def candidate_run_id(project: Path, when: datetime) -> str:
    """An identifier for one candidate build, keyed by what produced it."""
    material = "::".join(
        [
            cid.dbt_project_digest(project),
            cid.candidate_calculation_digest(project),
            identity.policy_digest(),
        ]
    )
    return (
        f"{CANDIDATE_PREFIX}-{hashlib.sha256(material.encode()).hexdigest()[:12]}"
        f"@{when.strftime('%Y%m%dT%H%M%S%f')}"
    )


class DatabasePathError(ValueError):
    """The database path is unusable, and nothing was opened or created because of it."""


def dbt_identity() -> dict[str, str]:
    """The dbt versions that rendered and executed the models."""
    runtime = cid.candidate_runtime_identity()
    return {name: runtime[name] for name in DBT_PACKAGES}


def project_digest(project: Path | None = None) -> str:
    """A digest over the dbt project files that can change an output.

    Delegates to :func:`candidate_identity.dbt_project_digest`: ``target/``, ``logs/`` and
    ``.user.yml`` are excluded there because they are artefacts of running, not inputs to
    it, and ``.user.yml`` is a per-machine identifier.
    """
    return cid.dbt_project_digest(project)


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


def subcommand_of(dbt_command: str) -> str:
    """The dbt subcommand in a recorded command string: the first token not a flag."""
    return next((t for t in dbt_command.split() if not t.startswith("-")), "")


def record_shape(con) -> tuple[str, ...]:
    """The stored record's columns in order, or an empty tuple when there is no table."""
    return tuple(
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE "
            "table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [BUILD_SCHEMA, _RECORD_TABLE],
        ).fetchall()
    )


def require_current_shape(con, database: Path) -> None:
    """Refuse a legacy record rather than migrate or drop it."""
    existing = record_shape(con)
    if existing and existing != _BUILD_RUN_COLUMNS:
        raise LegacyRecordError(
            f"{database.name}: {BUILD_RUN_TABLE} has a shape this version does not "
            f"write ({len(existing)} columns, expected {len(_BUILD_RUN_COLUMNS)}). Its "
            "rows were made under an earlier contract and are not upgraded: they say "
            "neither which attempt was latest nor how their output digest was computed. "
            "Build a fresh candidate with `uv run build-candidate`; this file is left as "
            "it is."
        )


def begin_attempt(
    database: Path,
    *,
    schedule: str,
    workbook: str,
    tariff_group: str,
    dbt_args: list[str],
    project: Path,
    run_id: str,
    when: datetime,
) -> dict[str, Any]:
    """Record a ``started`` attempt and close the file, so dbt can open it.

    Everything that identifies the build is known before dbt runs and is written now;
    what only the build can tell (its exit code, the tables it left) is written by
    :func:`finish_attempt`. If the row cannot be written -- the file is sealed read-only,
    or holds a legacy record -- :class:`AttemptRefused` is raised and **nothing ran**.
    """
    runtime = cid.candidate_runtime_identity()
    record: dict[str, Any] = {
        "run_id": run_id,
        "status": STARTED,
        "started_at_utc": when,
        "finished_at_utc": None,
        "dbt_exit_code": None,
        "database_path": str(database.resolve()),
        "target_schema": BUILD_SCHEMA,
        "dbt_command": " ".join(dbt_args),
        "dbt_vars": json.dumps(
            {
                "schedule": schedule,
                "workbook": workbook,
                "tariff_group": tariff_group,
                "run_id": run_id,
                "project_dir": str(project.resolve()),
            },
            sort_keys=True,
        ),
        "schedule_variant": schedule,
        "tariff_group": tariff_group,
        "dbt_core_version": runtime["dbt-core"],
        "dbt_duckdb_version": runtime["dbt-duckdb"],
        "python_version": runtime["python"],
        "runtime_detail": json.dumps(runtime, sort_keys=True),
        "runtime_fingerprint": cid.candidate_runtime_fingerprint(),
        "dbt_project_sha256": cid.dbt_project_digest(project),
        "macro_sha256": hashlib.sha256(
            (project / "macros" / "generated_policy.sql").read_bytes()
        ).hexdigest(),
        "policy_sha256": identity.policy_digest(),
        "calculation_code_sha256": cid.candidate_calculation_digest(project),
        "covered_files": json.dumps(
            cid.candidate_file_digests(project), sort_keys=True
        ),
        "schedule_source": None,
        "schedule_sha256": None,
        "schedule_rows": None,
        "price_catalogue_version": None,
        "output_digest_version": None,
        "built_output_sha256": None,
        "note": _NOTE,
    }
    assert tuple(record) == _BUILD_RUN_COLUMNS
    try:
        con = duckdb.connect(str(database))
    except duckdb.Error as error:
        raise AttemptRefused(
            f"{database} cannot be opened for writing ({error}); no attempt was "
            "recorded and dbt was not run. A sealed candidate is read-only on purpose: "
            "build a fresh one."
        ) from error
    try:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {BUILD_SCHEMA}")
        try:
            require_current_shape(con, database)
        except LegacyRecordError as error:
            raise AttemptRefused(str(error)) from error
        columns = ",\n    ".join(f"{name} {kind}" for name, kind in _BUILD_RUN_SCHEMA)
        con.execute(f"CREATE TABLE IF NOT EXISTS {BUILD_RUN_TABLE} (\n    {columns}\n)")
        placeholders = ",".join("?" * len(_BUILD_RUN_COLUMNS))
        con.execute(
            f"INSERT INTO {BUILD_RUN_TABLE} VALUES ({placeholders})",
            list(record.values()),
        )
    finally:
        con.close()
    return record


def _schedule_identity(con) -> dict[str, Any]:
    """Schedule and catalogue identity, read from the dimension rows dbt wrote.

    Read from the built tables rather than resolved again in this process, so the record
    describes what was **built**, not what the parent would have read. Absent when the
    build did not produce the dimension (a partial selection): recorded as NULL, not
    guessed.
    """
    out: dict[str, Any] = {
        "schedule_source": None,
        "schedule_sha256": None,
        "schedule_rows": None,
        "price_catalogue_version": None,
    }
    tables = {
        name
        for (name,) in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
            [BUILD_SCHEMA],
        ).fetchall()
    }
    if "dim_tariff_band_schedule" in tables:
        rows = con.execute(
            "SELECT schedule_source, source_sha256, COUNT(*) FROM "
            f"{BUILD_SCHEMA}.dim_tariff_band_schedule GROUP BY 1, 2"
        ).fetchall()
        if len(rows) == 1:
            out["schedule_source"], out["schedule_sha256"], out["schedule_rows"] = rows[
                0
            ]
    if "dim_tariff_price" in tables:
        versions = con.execute(
            f"SELECT DISTINCT catalogue_version FROM {BUILD_SCHEMA}.dim_tariff_price"
        ).fetchall()
        if len(versions) == 1:
            out["price_catalogue_version"] = versions[0][0]
    return out


def finish_attempt(
    database: Path, run_id: str, exit_code: int, when: datetime
) -> dict[str, Any]:
    """Complete the attempt ``run_id`` as ``succeeded`` (exit 0) or ``failed``.

    Opened read-write only after dbt has exited and released the file lock. On success
    the output digest is computed **from the database being written**, so the record
    describes this file's tables as they are at this moment.
    """
    con = duckdb.connect(str(database))
    try:
        fields: dict[str, Any] = {
            "status": SUCCEEDED if exit_code == 0 else FAILED,
            "finished_at_utc": when,
            "dbt_exit_code": exit_code,
        }
        if exit_code == 0:
            fields.update(_schedule_identity(con))
            fields["output_digest_version"] = OUTPUT_DIGEST_VERSION
            fields["built_output_sha256"] = build_output_digest(con)
        assignments = ", ".join(f"{name} = ?" for name in fields)
        con.execute(
            f"UPDATE {BUILD_RUN_TABLE} SET {assignments} WHERE run_id = ?",
            [*fields.values(), run_id],
        )
        row = con.execute(
            f"SELECT * FROM {BUILD_RUN_TABLE} WHERE run_id = ?", [run_id]
        ).fetchone()
    finally:
        con.close()
    if row is None:  # pragma: no cover - the started row was written by begin_attempt
        raise RuntimeError(f"attempt {run_id} is not recorded in {database}")
    return dict(zip(_BUILD_RUN_COLUMNS, row, strict=True))


def record_build(
    database: Path,
    schedule: str,
    command: list[str],
    project: Path,
    run_id: str,
    when: datetime,
    tariff_group: str,
    exit_code: int = 0,
    workbook: str = "",
) -> dict[str, Any]:
    """Begin and immediately finish one attempt. For callers that ran dbt themselves.

    The supported entry point is :func:`main`, which records ``started`` *before* dbt runs.
    This shortcut exists for tests that stand in for a build; it records exactly what
    ``main`` would have recorded had dbt exited with ``exit_code`` at once.
    """
    begin_attempt(
        database,
        schedule=schedule,
        workbook=workbook,
        tariff_group=tariff_group,
        dbt_args=command,
        project=project,
        run_id=run_id,
        when=when,
    )
    return finish_attempt(database, run_id, exit_code, when)


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
    try:
        begin_attempt(
            database,
            schedule=args.schedule,
            workbook=args.workbook,
            tariff_group=args.tariff_group,
            dbt_args=dbt_args,
            project=args.project_dir,
            run_id=run_id,
            when=when,
        )
    except AttemptRefused as error:
        print(f"run-dbt: {error}", file=sys.stderr)
        return 2
    # The recording connection is closed; dbt now holds the file alone. argv is built
    # here and no shell is involved.
    completed = subprocess.run(
        command,
        env={**os.environ, "ENERGY_RECONCILIATION_DB": str(database)},
        check=False,
    )
    finished = datetime.now(UTC).replace(tzinfo=None)
    record = finish_attempt(database, run_id, completed.returncode, finished)
    if completed.returncode != 0:
        print(
            f"run-dbt: dbt exited {completed.returncode}; attempt {run_id} is recorded "
            f"as {record['status']} in {BUILD_RUN_TABLE}. No success was recorded.",
            file=sys.stderr,
        )
        return completed.returncode
    print(
        f"recorded in {BUILD_RUN_TABLE}: {record['run_id']} {record['status']} · dbt-core "
        f"{record['dbt_core_version']}, dbt-duckdb {record['dbt_duckdb_version']}, "
        f"schedule {record['schedule_variant']}, group {record['tariff_group']}, "
        f"outputs {str(record['built_output_sha256'])[:12]}… "
        f"({record['output_digest_version']})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
