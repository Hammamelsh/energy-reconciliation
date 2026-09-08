"""ANL-003 step 2: dbt and Python return the same rows, not merely the same count.

A count is a weak check. Two queries can agree on how many rows they produce and
disagree about which ones, which is exactly the failure a policy port risks: a collapse
rule applied to the wrong column would keep the tally and change the membership. So the
comparison here is over **every column of every row**, ordered, on a fixture that
contains one of each case the policies exist to resolve.

The fixture is synthetic and built through the real loader, so the rows dbt reads are
rows this project actually stores. The dataset is never needed.

**dbt is really invoked.** Compiling a macro proves the text is well formed; only
running it proves the database agrees.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, MEMBER, build_archive, row

from energy_reconciliation import dbt_macros, policy
from energy_reconciliation.ingest.loader import load_member

pytest.importorskip("dbt.cli.main", reason="dbt is not installed")

PROJECT = dbt_macros.repository_root() / "dbt"

#: Every case the four policies exist to resolve, in one small member.
FIXTURE = HEADER + b"".join(
    [
        # an ordinary reading
        row("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.5 "),
        # an exact duplicate: collapses to one distinct reading
        row("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.5 "),
        # equivalent representations of one value: also one distinct reading
        row("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.200 "),
        row("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.2 "),
        # a conflict: two signatures at one label, so two distinct readings
        row("MAC000001", "Std", "2013-01-01 01:30:00.0000000", " 0.3 "),
        row("MAC000001", "Std", "2013-01-01 01:30:00.0000000", " 0.9 "),
        # a number beside a missing-value token is also a conflict
        row("MAC000001", "Std", "2013-01-01 02:00:00.0000000", " 0.4 "),
        row("MAC000001", "Std", "2013-01-01 02:00:00.0000000", "Null"),
        # off the half-hour grid, and a lone missing-value token
        row("MAC000001", "Std", "2013-01-01 02:37:27.0000000", "Null"),
        # a second household, and a second tariff group
        row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 1.25 "),
        row("MAC000002", "ToU", "2013-01-01 01:00:00.0000000", " 0 "),
    ]
)

#: Compared as text on both sides, so the check is about values rather than about how
#: each client happens to type a DECIMAL on the way out.
COLUMNS = (
    "household_id",
    "tariff_group",
    "source_timestamp_text",
    "observed_at_naive",
    "on_half_hour_grid",
    "consumption_kwh",
    "value_category",
    "value_signature",
)
#: The dbt entry point. The console script rather than ``-m``, which warns when pytest
#: has already imported ``dbt.cli``.
DBT = Path(sys.executable).with_name("dbt")


def _dbt(database: Path, target: Path, *args: str) -> subprocess.CompletedProcess:
    command = [str(DBT)] if DBT.is_file() else [sys.executable, "-m", "dbt.cli.main"]
    return subprocess.run(
        [
            *command,
            *args,
            "--project-dir",
            str(PROJECT),
            "--profiles-dir",
            str(PROJECT),
            "--target-path",
            str(target),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "ENERGY_RECONCILIATION_DB": str(database)},
        check=False,
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[Path, Path]:
    """A loaded fixture warehouse with the dbt project built against it.

    Module-scoped because dbt costs seconds and nothing here mutates the database.
    ``dbt run`` has to happen before any ephemeral model can be selected: the staging
    view they read is a real relation, and its absence is a missing table, not an
    empty result.
    """
    tmp_path = tmp_path_factory.mktemp("dbt_equivalence")
    archive = build_archive(tmp_path, {MEMBER: FIXTURE}, name="equiv.zip")
    database = tmp_path / "equiv.duckdb"
    assert load_member(archive, MEMBER, database).complete
    target = tmp_path / "target"
    process = _dbt(database, target, "build")
    assert process.returncode == 0, process.stdout + process.stderr
    return database, target


def _dbt_rows(built: tuple[Path, Path], model: str, columns: tuple[str, ...]):
    """Run `dbt show` and return its rows. dbt executes the SQL, not this test."""
    database, target = built
    cast = ", ".join(f"CAST({c} AS VARCHAR) AS {c}" for c in columns)
    order = ", ".join(columns)
    query = f"select {cast} from {{{{ ref('{model}') }}}} order by {order}"
    process = _dbt(
        database,
        target,
        "show",
        "--inline",
        query,
        "--output",
        "json",
        "--limit",
        "500",
    )
    assert process.returncode == 0, process.stdout + process.stderr
    payload = process.stdout[process.stdout.index("{") :]
    return [tuple(r[c] for c in columns) for r in json.loads(payload)["show"]]


def _python_rows(database: Path, sql: str, columns: tuple[str, ...]):
    cast = ", ".join(f"CAST({c} AS VARCHAR) AS {c}" for c in columns)
    order = ", ".join(columns)
    con = duckdb.connect(str(database), read_only=True)
    try:
        return con.execute(f"SELECT {cast} FROM ({sql}) ORDER BY {order}").fetchall()
    finally:
        con.close()


def test_distinct_readings_rows_are_identical(built):
    """Every column of every row, in the same order, from both paths."""
    mine = _python_rows(built[0], policy.distinct_readings_sql(), COLUMNS)
    theirs = _dbt_rows(built, "int_distinct_readings", COLUMNS)
    assert theirs == mine
    assert mine, "the fixture must produce rows, or this proves nothing"


def test_conflicting_labels_rows_are_identical(built):
    keys = ("household_id", "source_timestamp_text")
    mine = _python_rows(built[0], policy.conflicting_labels_sql(), keys)
    theirs = _dbt_rows(built, "int_conflicting_labels", keys)
    assert theirs == mine
    # the fixture holds exactly the two disagreements written into it
    assert len(mine) == 2


def test_the_fixture_exercises_the_policies_it_claims_to(built):
    """If the fixture stopped containing duplicates the comparison would be empty talk."""
    con = duckdb.connect(str(built[0]), read_only=True)
    try:
        raw = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        distinct = con.execute(
            f"SELECT COUNT(*) FROM ({policy.distinct_readings_sql()})"
        ).fetchone()[0]
        off_grid = con.execute(
            "SELECT COUNT(*) FROM readings WHERE NOT on_half_hour_grid"
        ).fetchone()[0]
        tokens = con.execute(
            f"SELECT COUNT(*) FROM readings WHERE value_category <> '{policy.FINITE}'"
        ).fetchone()[0]
    finally:
        con.close()
    assert raw == 11
    # 11 raw rows - 1 exact duplicate - 1 equivalent representation = 9 distinct readings
    assert distinct == 9
    assert off_grid == 1
    assert tokens == 2
