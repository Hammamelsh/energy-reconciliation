"""Schema compatibility between the running code and a persisted warehouse.

These exist because the failure actually happened. A Streamlit server that had imported
``tariff/analytics.py`` before a rebuild kept the old module -- the tariff package is
outside Streamlit's reload scope -- while ``build-tariff-scenario`` in another terminal
migrated ``scenario_run`` underneath it. The old SQL asked for ``tariff_code_sha256``,
the new table had ``calculation_code_sha256``, and DuckDB raised a ``BinderException``
from the middle of the page.

Two things are asserted here, and they are deliberately separate concerns:

- **Schema compatibility** -- can this code read these columns at all. That is what
  ``scenario_availability`` answers.
- **Calculation-content identity** -- whether the stored result is still current for the
  inputs and code. That is the scenario fingerprint's job, and it is not conflated with
  the above: a readable schema holding a stale result is a different situation from an
  unreadable one.
"""

from __future__ import annotations

import duckdb
import pytest
from conftest import HEADER, row
from test_tariff import load, make_schedule

from energy_reconciliation.explorer import queries as q
from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff.models import build_scenario


def _built(tmp_path, name="schema.zip"):
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 "),
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 2 "),
        ]
    )
    database = load(tmp_path, body, name=name)
    result = build_scenario(
        database,
        make_schedule(
            [("2013-01-01 00:30:00", "Low"), ("2013-01-01 01:00:00", "High")]
        ),
    )
    return database, result


def _rename_column(database, old, new):
    """Make a current warehouse look like one written by a different generation."""
    con = duckdb.connect(str(database))
    try:
        con.execute(f"ALTER TABLE scenario_run RENAME COLUMN {old} TO {new}")
    finally:
        con.close()


# ------------------------------------------------------------------ the three states
def test_a_current_warehouse_reads_as_ready(tmp_path):
    database, _ = _built(tmp_path)
    availability = ta.scenario_availability(database)
    assert availability.state == ta.READY
    assert availability.ready
    assert ta.latest_run(database) is not None


def test_a_warehouse_with_no_scenario_reads_as_absent_not_incompatible(tmp_path):
    """Never built and cannot be read are different facts and get different messages."""
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
    database = load(tmp_path, body, name="none.zip")
    availability = ta.scenario_availability(database)
    assert availability.state == ta.ABSENT
    assert not availability.ready
    assert ta.latest_run(database) is None  # absence is None, never an error


def test_the_reported_mismatch_is_recognised_rather_than_raised(tmp_path):
    """Exactly the incident: the code wants a column the database no longer has."""
    database, _ = _built(tmp_path)
    _rename_column(database, "calculation_code_sha256", "tariff_code_sha256")

    availability = ta.scenario_availability(database)
    assert availability.state == ta.INCOMPATIBLE
    assert availability.missing_columns == ("calculation_code_sha256",)
    assert availability.unexpected_columns == ("tariff_code_sha256",)
    assert "different generations" in availability.diagnosis
    assert "Restart the app first" in availability.recovery


def test_an_unreadable_scenario_raises_rather_than_looking_empty(tmp_path):
    """Returning None here would show an empty tab over a database full of results."""
    database, _ = _built(tmp_path)
    _rename_column(database, "calculation_code_sha256", "tariff_code_sha256")
    with pytest.raises(ta.ScenarioSchemaError) as caught:
        ta.latest_run(database)
    message = str(caught.value)
    assert "calculation_code_sha256" in message
    assert "tariff_code_sha256" in message


def test_extra_unknown_columns_alone_are_still_readable(tmp_path):
    """A database holding more than this code selects is not broken.

    Only a column the code needs and cannot find makes a schema unreadable. Treating
    extra columns as a fault would make every forward-compatible warehouse look broken.
    """
    database, _ = _built(tmp_path)
    con = duckdb.connect(str(database))
    try:
        con.execute("ALTER TABLE scenario_run ADD COLUMN some_future_field VARCHAR")
    finally:
        con.close()
    availability = ta.scenario_availability(database)
    assert availability.state == ta.READY
    assert ta.latest_run(database) is not None


def test_a_missing_column_with_no_extras_points_at_the_database(tmp_path):
    database, _ = _built(tmp_path)
    con = duckdb.connect(str(database))
    try:
        con.execute("ALTER TABLE scenario_run DROP COLUMN runtime_detail")
    finally:
        con.close()
    availability = ta.scenario_availability(database)
    assert availability.missing_columns == ("runtime_detail",)
    assert availability.unexpected_columns == ()
    assert "predate the current model" in availability.diagnosis
    assert availability.recovery == (
        "Rebuild the scenario with `build-tariff-scenario`."
    )


# ------------------------------------------- the other tabs keep working regardless
def test_the_explorer_queries_are_unaffected_by_an_unreadable_tariff_schema(tmp_path):
    """Overview, Data quality and Source records read `readings`, not the tariff tables."""
    database, _ = _built(tmp_path)
    _rename_column(database, "calculation_code_sha256", "tariff_code_sha256")

    from datetime import date

    assert q.households(database) == ["MAC000001"]
    assert q.date_bounds(database, "MAC000001") == (date(2013, 1, 1), date(2013, 1, 1))
    period = q.period_summary(database, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert period.total_kwh is not None
    assert q.observation_count(database, "MAC000001") == 2
    assert q.quality_summary(database, "MAC000001").observed_records == 2
    assert len(q.loaded_sources(database)) == 1


# ------------------------------------------------- the build-side schema migration
def test_rebuilding_over_an_older_schema_preserves_readings_and_load_history(tmp_path):
    """``ensure_schema`` may drop only derived tables, and must say that it did.

    The tariff tables are rebuildable from the archive and the workbook. ``readings``,
    ``rejected_records`` and ``load_registry`` are not, so they must survive untouched.
    """
    database, first = _built(tmp_path)
    con = duckdb.connect(str(database), read_only=True)
    try:
        before_readings = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        before_loads = con.execute(
            "SELECT load_id, member_content_sha256 FROM load_registry ORDER BY 1"
        ).fetchall()
        before_rejects = con.execute(
            "SELECT COUNT(*) FROM rejected_records"
        ).fetchone()[0]
    finally:
        con.close()

    _rename_column(database, "calculation_code_sha256", "tariff_code_sha256")

    schedule = make_schedule(
        [("2013-01-01 00:30:00", "Low"), ("2013-01-01 01:00:00", "High")]
    )
    second = build_scenario(database, schedule)

    assert not second.skipped, "an unreadable schema must never be skipped as unchanged"
    assert ta.scenario_availability(database).state == ta.READY

    con = duckdb.connect(str(database), read_only=True)
    try:
        assert (
            con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
            == before_readings
        )
        assert (
            con.execute(
                "SELECT load_id, member_content_sha256 FROM load_registry ORDER BY 1"
            ).fetchall()
            == before_loads
        )
        assert (
            con.execute("SELECT COUNT(*) FROM rejected_records").fetchone()[0]
            == before_rejects
        )
    finally:
        con.close()
    # The figures are the same because the inputs are: a schema repair is not a
    # recalculation, and must not look like one.
    assert second.total_energy_charge_gbp_exact == first.total_energy_charge_gbp_exact
    assert second.included_readings == first.included_readings


def test_schema_compatibility_and_content_identity_stay_separate(tmp_path):
    """A readable schema says nothing about whether the result is current.

    Rerunning unchanged inputs skips: the schema was always readable, and the content
    identity says the stored result still stands. Conflating the two would either
    rebuild needlessly or serve a stale result as current.
    """
    database, first = _built(tmp_path)
    schedule = make_schedule(
        [("2013-01-01 00:30:00", "Low"), ("2013-01-01 01:00:00", "High")]
    )
    assert ta.scenario_availability(database).state == ta.READY
    second = build_scenario(database, schedule)
    assert second.skipped
    assert second.scenario_fingerprint == first.scenario_fingerprint
