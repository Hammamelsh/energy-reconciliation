"""Tariff scenario tests. Every expectation here is hand-computable.

Nothing in this file reads ``data/raw``. Each test builds a small archive in a temp
directory, ingests it with the real loader, attaches a small schedule, and checks the
result against a figure worked out by hand and written in the docstring.

Real-dataset figures are **not** asserted here. They are measured separately and
recorded in ``docs/anl-002-tariff-scenario.md``; mixing the two would let a synthetic
expectation stand in for a measurement.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, build_archive, row

from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff import prices as pr
from energy_reconciliation.tariff.models import (
    ASSUMPTION_ID,
    EXCLUSION_REASONS,
    build_scenario,
    scenario_fingerprint,
    tariff_code_fingerprint,
)
from energy_reconciliation.tariff.schedule import (
    Schedule,
    ScheduleError,
    ScheduleRow,
    demo_schedule,
    step_report,
)

MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"


def make_schedule(pairs: list[tuple[str, str]], source: str = "test") -> Schedule:
    """Build a schedule straight from ``(timestamp, band)`` pairs, bypassing Excel.

    The digest is derived from the pairs, exactly as ``demo_schedule`` derives its own,
    so two different schedules can never claim the same identity.
    """
    from energy_reconciliation.tariff.schedule import _validate

    rows = [
        # Naive on purpose: schedule labels carry no timezone.
        ScheduleRow(datetime.fromisoformat(ts), band)
        for ts, band in pairs
    ]
    payload = "|".join(f"{ts}={band}" for ts, band in pairs)
    return Schedule(
        _validate(rows, source), source, hashlib.sha256(payload.encode()).hexdigest()
    )


def load(tmp_path: Path, body: bytes, name: str = "one.zip") -> Path:
    archive = build_archive(tmp_path, {MEMBER: body}, name=name)
    database = tmp_path / f"{name}.duckdb"
    result = load_member(archive, MEMBER, database)
    assert result.complete
    return database


# --------------------------------------------------------------- price catalogue
def test_every_documented_price_divides_by_100_exactly():
    """The pence-to-pounds conversion must introduce no rounding at all.

    67.20 -> 0.6720, 11.76 -> 0.1176, 3.99 -> 0.0399, 14.228 -> 0.14228.
    """
    for price in pr.CATALOGUE:
        assert price.gbp_per_kwh * Decimal(100) == price.pence_per_kwh
        assert price.gbp_per_kwh == price.pence_per_kwh / Decimal(100)


def test_flat_rate_effective_dates_are_unknown_not_invented():
    flat = [p for p in pr.CATALOGUE if p.band_label == pr.FLAT_BAND]
    assert flat, "the flat rate must be in the catalogue"
    for price in flat:
        assert price.effective_from is None
        assert price.effective_until is None


def test_validity_is_a_half_open_interval_with_an_exclusive_end():
    """A whole year is [2013-01-01, 2014-01-01), never an inclusive 2013-12-31.

    Compared against a timestamp, DATE '2013-12-31' is 2013-12-31 00:00:00, and an
    inclusive end would silently drop the last 47 half hours of the year.
    """
    for price in pr.CATALOGUE:
        if price.tariff_group == pr.TOU_GROUP:
            assert price.effective_from == date(2013, 1, 1)
            assert price.effective_until == date(2014, 1, 1)


def test_band_prices_are_labelled_publisher_documented():
    for price in pr.CATALOGUE:
        assert price.evidence_label == "PUBLISHER-DOCUMENTED"
        assert "london datastore" in price.source_citation.lower()


# -------------------------------------------------------------- schedule shape
def test_a_duplicated_schedule_key_is_refused_before_it_can_multiply():
    """A repeated label would double every reading joined to it. Refuse the load."""
    with pytest.raises(ScheduleError, match="duplicated schedule label"):
        make_schedule(
            [
                ("2013-01-01 00:30:00", "Low"),
                ("2013-01-01 00:30:00", "High"),
            ]
        )


def test_an_off_grid_schedule_label_is_refused():
    with pytest.raises(ScheduleError, match="not on the half-hour grid"):
        make_schedule([("2013-01-01 00:17:23", "Low")])


def test_an_empty_schedule_is_refused():
    with pytest.raises(ScheduleError, match="no schedule rows"):
        make_schedule([])


def test_demo_schedule_is_a_full_regular_day():
    """48 slots, every step 1800 seconds -- and that says nothing about timezone."""
    schedule = demo_schedule()
    assert len(schedule.rows) == 48
    report = step_report(schedule)
    assert report["steps"] == 47
    assert report["steps_of_1800_seconds"] == 47
    assert schedule.source == "synthetic-demo"


# ----------------------------------------------------------- the charge itself
def test_price_unit_conversion_end_to_end(tmp_path):
    """One ToU reading of 2 kWh in a High half hour.

    2 kWh x 67.20 p/kWh / 100 = 1.344 GBP. If the code ever treated the price as
    pounds instead of pence, this would come out as 134.40.
    """
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 ")
    database = load(tmp_path, body)
    schedule = make_schedule([("2013-01-01 00:30:00", "High")])
    result = build_scenario(database, schedule)
    assert result.included_readings == 1
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("1.344")


def test_three_bands_in_one_day(tmp_path):
    """1 kWh at High, 1 at Normal, 1 at Low.

    0.672 + 0.1176 + 0.0399 = 0.8295 GBP. Bands must not be interchangeable.
    """
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 "),
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 1 "),
            row("MAC000001", "ToU", "2013-01-01 01:30:00.0000000", " 1 "),
        ]
    )
    database = load(tmp_path, body)
    schedule = make_schedule(
        [
            ("2013-01-01 00:30:00", "High"),
            ("2013-01-01 01:00:00", "Normal"),
            ("2013-01-01 01:30:00", "Low"),
        ]
    )
    result = build_scenario(database, schedule)
    assert result.included_readings == 3
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("0.8295")
    bands = ta.band_summary(database, result.run_id)
    charges = dict(zip(bands["band_label"], bands["charge_gbp_exact"], strict=True))
    assert Decimal(charges["High"]) == Decimal("0.672")
    assert Decimal(charges["Normal"]) == Decimal("0.1176")
    assert Decimal(charges["Low"]) == Decimal("0.0399")


def test_the_band_boundary_is_the_label_not_the_neighbouring_slot(tmp_path):
    """Two adjacent half hours on opposite sides of a band change.

    00:30 is Low, 01:00 is High. 1 kWh in each: 0.0399 + 0.672 = 0.7119.
    A boundary read one slot out would give 0.672 + 0.0399 -- the same total but the
    wrong bands -- so the per-band figures are what actually pins this down.
    """
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 "),
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 1 "),
        ]
    )
    database = load(tmp_path, body)
    schedule = make_schedule(
        [("2013-01-01 00:30:00", "Low"), ("2013-01-01 01:00:00", "High")]
    )
    result = build_scenario(database, schedule)
    con = duckdb.connect(str(database), read_only=True)
    try:
        rows = con.execute(
            "SELECT source_timestamp_text, band_label, CAST(energy_charge_gbp AS VARCHAR) "
            "FROM fact_interval_charge_scenario ORDER BY observed_at_naive"
        ).fetchall()
    finally:
        con.close()
    assert [r[1] for r in rows] == ["Low", "High"]
    assert Decimal(rows[0][2]) == Decimal("0.0399")
    assert Decimal(rows[1][2]) == Decimal("0.672")
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("0.7119")


def test_no_row_level_rounding_happens(tmp_path):
    """A charge with more decimals than money has must survive unrounded.

    0.0000000001 kWh x 11.76 p/kWh / 100 = 0.000000000011760 GBP. Rounding per row
    would make it 0.00 and the total would be wrong by every row.
    """
    body = HEADER + row(
        "MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 0.0000000001 "
    )
    database = load(tmp_path, body)
    schedule = make_schedule([("2013-01-01 00:30:00", "Normal")])
    result = build_scenario(database, schedule)
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("0.00000000001176")
    assert ta.round_money(Decimal(result.total_energy_charge_gbp_exact)) == Decimal(
        "0.00"
    )


def test_display_rounding_is_half_up_and_applied_once():
    assert ta.round_money(Decimal("0.005")) == Decimal("0.01")
    assert ta.round_money(Decimal("2812.5713283360")) == Decimal("2812.57")
    assert ta.round_energy(Decimal("0.0005")) == Decimal("0.001")
    assert ta.round_share(Decimal("0.04899999")) == Decimal("0.0490")


# ------------------------------------------------------------- what is excluded
@pytest.fixture
def mixed_database(tmp_path):
    """One ToU household whose readings hit every exclusion path.

    Charged: 2013-01-01 00:30 (Low, 1 kWh) and 01:00 (High, 2 kWh)
             = 0.0399 + 1.344 = 1.3839 GBP.
    Excluded: an outside-2013 reading, a Null, an off-grid row, a conflicting label
              (two values), an in-coverage label the schedule does not carry
              (02:30), and a whole Std household.
    """
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 "),  # charged
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 2 "),  # charged
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 2 "),  # exact dup
            row("MAC000001", "ToU", "2013-01-01 01:30:00.0000000", "Null"),  # missing
            row("MAC000001", "ToU", "2013-01-01 02:00:00.0000000", " 0.5 "),  # conflict
            row("MAC000001", "ToU", "2013-01-01 02:00:00.0000000", " 0.9 "),  # conflict
            row("MAC000001", "ToU", "2013-01-01 02:17:23.0000000", " 0.4 "),  # off grid
            row(
                "MAC000001", "ToU", "2013-01-01 02:30:00.0000000", " 0.7 "
            ),  # unmatched
            row("MAC000001", "ToU", "2012-12-31 23:30:00.0000000", " 0.8 "),  # outside
            row("MAC000002", "Std", "2013-01-01 00:30:00.0000000", " 5 "),  # ineligible
        ]
    )
    database = load(tmp_path, body)
    # 02:30 is deliberately absent from the schedule, so a reading at that label is
    # INSIDE the schedule's coverage and still unmatched -- a different fault from a
    # reading that falls outside the covered period altogether.
    schedule = make_schedule(
        [
            ("2013-01-01 00:30:00", "Low"),
            ("2013-01-01 01:00:00", "High"),
            ("2013-01-01 01:30:00", "Normal"),
            ("2013-01-01 02:00:00", "Normal"),
            ("2013-01-01 03:00:00", "Normal"),
        ]
    )
    return database, build_scenario(database, schedule)


def test_the_charged_total_is_hand_computable(mixed_database):
    _database, result = mixed_database
    assert result.included_readings == 2
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("1.3839")


def test_every_distinct_reading_is_charged_or_excluded_with_a_reason(mixed_database):
    """10 rows, 1 exact duplicate collapsed, 9 distinct readings: 2 charged, 7 excluded."""
    database, result = mixed_database
    assert result.raw_rows == 10
    assert result.rows_collapsed_by_policy == 1
    assert result.distinct_readings == 9
    assert result.included_readings + result.excluded_readings == 9
    assert result.reconciles
    assert ta.accounting(database, result.run_id).reconciles


def test_each_exclusion_reason_appears_exactly_where_expected(mixed_database):
    """One reading per reason, except the conflict which excludes both its values."""
    _, result = mixed_database
    assert result.reasons == {
        "ineligible_tariff_group": 1,
        "outside_schedule_period": 1,
        "conflicting_label": 2,
        "off_grid_observation": 1,
        "missing_value": 1,
        "unmatched_schedule_label": 1,
    }
    assert set(result.reasons) <= set(EXCLUSION_REASONS)


def test_nothing_excluded_becomes_a_zero_charge(mixed_database):
    """An excluded reading has no charge row at all -- not a row with 0.00 in it.

    The invariant is *absence*, not "no zero charges exist": a measured 0 kWh reading is
    a measurement and is charged at exactly zero (see the next test). The real warehouse
    holds 133 such rows, every one of them with consumption_kwh = 0. An earlier version
    of this test asserted no fact row could carry a zero charge, which only passed
    because this fixture has no zero readings.
    """
    database, _result = mixed_database
    con = duckdb.connect(str(database), read_only=True)
    try:
        # Any zero charge must come from a zero reading, never from a zeroed exclusion.
        assert (
            con.execute(
                "SELECT COUNT(*) FROM fact_interval_charge_scenario "
                "WHERE energy_charge_gbp = 0 AND consumption_kwh <> 0"
            ).fetchone()[0]
            == 0
        )
        charged = set(
            con.execute(
                "SELECT household_id, source_timestamp_text "
                "FROM fact_interval_charge_scenario"
            ).fetchall()
        )
        excluded = set(
            con.execute(
                "SELECT household_id, source_timestamp_text "
                "FROM fact_interval_charge_exclusion"
            ).fetchall()
        )
    finally:
        con.close()
    assert charged & excluded == set()


def test_all_conditions_stay_visible_even_though_one_reason_is_assigned(mixed_database):
    """The off-grid row is also a valid label; the Null row is also on the grid.

    Only one reason is *assigned*, but every condition is stored as its own flag, so
    the ordering can never hide a fact.
    """
    database, _ = mixed_database
    con = duckdb.connect(str(database), read_only=True)
    try:
        flags = con.execute(
            "SELECT exclusion_reason, is_off_grid, is_missing_value, is_conflicted "
            "FROM fact_interval_charge_exclusion "
            "WHERE source_timestamp_text LIKE '2013-01-01 02:17%'"
        ).fetchone()
    finally:
        con.close()
    assert flags[0] == "off_grid_observation"
    assert flags[1] is True


def test_a_measured_zero_reading_is_charged_at_exactly_zero(tmp_path):
    """0 kWh x 67.20 p/kWh = 0.000 GBP -- a charged row, counted, worth nothing.

    "A zero is a measurement" is this project's policy for readings; the scenario keeps
    it. The row is in the fact table with a zero charge, not in the exclusions.
    """
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 0 "),
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 1 "),
        ]
    )
    database = load(tmp_path, body)
    schedule = make_schedule(
        [("2013-01-01 00:30:00", "High"), ("2013-01-01 01:00:00", "High")]
    )
    result = build_scenario(database, schedule)
    assert result.included_readings == 2
    assert result.excluded_readings == 0
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("0.672")
    con = duckdb.connect(str(database), read_only=True)
    try:
        zero = con.execute(
            "SELECT consumption_kwh, energy_charge_gbp FROM fact_interval_charge_scenario "
            "WHERE source_timestamp_text LIKE '2013-01-01 00:30%'"
        ).fetchone()
    finally:
        con.close()
    assert zero == (Decimal("0E-10"), Decimal("0E-16")) or (
        zero[0] == 0 and zero[1] == 0
    )


# ------------------------------------------------ validity and schedule boundaries
BOUNDARY_STAMPS = (
    "2012-12-31 23:30:00",
    "2013-01-01 00:00:00",
    "2013-12-31 00:00:00",
    "2013-12-31 00:30:00",
    "2013-12-31 23:30:00",
    "2014-01-01 00:00:00",
)


def _boundary_database(tmp_path, group="ToU"):
    body = HEADER + b"".join(
        row("MAC000001", group, f"{s}.0000000", " 1 ") for s in BOUNDARY_STAMPS
    )
    return load(tmp_path, body, name="boundary.zip")


def _charged_and_excluded(database):
    con = duckdb.connect(str(database), read_only=True)
    try:
        charged = dict(
            con.execute(
                "SELECT source_timestamp_text, CAST(energy_charge_gbp AS VARCHAR) "
                "FROM fact_interval_charge_scenario"
            ).fetchall()
        )
        excluded = dict(
            con.execute(
                "SELECT source_timestamp_text, exclusion_reason "
                "FROM fact_interval_charge_exclusion"
            ).fetchall()
        )
    finally:
        con.close()
    return charged, excluded


def test_the_six_boundary_timestamps_through_schedule_and_price(tmp_path):
    """Expected, derived before running: the year is [2013-01-01 00:00, 2014-01-01 00:00).

    Publisher: the dToU tariff ran "throughout the 2013 calendar year". Representation:
    naive labels; a whole-year interval is half-open. Implementation: a reading is charged
    only if the schedule carries its label AND a price is valid at that instant.
    """
    database = _boundary_database(tmp_path)
    schedule = make_schedule([(s, "High") for s in BOUNDARY_STAMPS[1:5]])
    result = build_scenario(database, schedule)
    charged, excluded = _charged_and_excluded(database)

    expected = {
        "2012-12-31 23:30:00": "excluded:outside_schedule_period",
        "2013-01-01 00:00:00": "charged:0.6720000000000000",
        "2013-12-31 00:00:00": "charged:0.6720000000000000",
        "2013-12-31 00:30:00": "charged:0.6720000000000000",
        "2013-12-31 23:30:00": "charged:0.6720000000000000",  # would vanish under an inclusive DATE end
        "2014-01-01 00:00:00": "excluded:outside_schedule_period",
    }
    actual = {
        s: (
            f"charged:{charged[f'{s}.0000000']}"
            if f"{s}.0000000" in charged
            else f"excluded:{excluded[f'{s}.0000000']}"
        )
        for s in BOUNDARY_STAMPS
    }
    assert actual == expected
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal(
        "2.688"
    )  # 4 x 0.672


def test_a_label_the_schedule_carries_but_no_price_covers_is_unpriced_not_zero(
    tmp_path, monkeypatch
):
    """Schedule coverage and price validity are checked independently.

    With the price valid only for [2013-01-01, 2013-12-31) -- deliberately one day short
    -- the schedule still carries 2013-12-31 labels, so those readings are excluded as
    ``unpriced_band``: visible, with a reason, never charged at zero.
    """
    from energy_reconciliation.tariff.prices import Price

    shortened = tuple(
        Price(
            p.tariff_group,
            p.band_label,
            p.pence_per_kwh,
            p.effective_from,
            date(2013, 12, 31) if p.tariff_group == pr.TOU_GROUP else p.effective_until,
            p.evidence_label,
            p.source_citation,
        )
        for p in pr.CATALOGUE
    )
    monkeypatch.setattr(pr, "CATALOGUE", shortened)
    database = _boundary_database(tmp_path)
    schedule = make_schedule([(s, "High") for s in BOUNDARY_STAMPS[1:5]])
    result = build_scenario(database, schedule)
    charged, excluded = _charged_and_excluded(database)

    assert "2013-01-01 00:00:00.0000000" in charged
    for s in ("2013-12-31 00:00:00", "2013-12-31 00:30:00", "2013-12-31 23:30:00"):
        assert excluded[f"{s}.0000000"] == "unpriced_band", s
    assert result.included_readings == 1
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("0.672")


def test_an_unknown_validity_prices_nothing(tmp_path, monkeypatch):
    """NULL bounds mean UNKNOWN, not open-ended: a ToU price with no dates charges nothing."""
    from energy_reconciliation.tariff.prices import Price

    undated = tuple(
        Price(
            p.tariff_group,
            p.band_label,
            p.pence_per_kwh,
            None,
            None,
            p.evidence_label,
            p.source_citation,
        )
        for p in pr.CATALOGUE
    )
    monkeypatch.setattr(pr, "CATALOGUE", undated)
    database = _boundary_database(tmp_path)
    result = build_scenario(
        database, make_schedule([(s, "High") for s in BOUNDARY_STAMPS[1:5]])
    )
    assert result.included_readings == 0
    assert result.reasons.get("unpriced_band") == 4
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal(0)


# ---------------------------------------------------------- arithmetic behaviour
def test_decimal_overflow_raises_rather_than_wrapping():
    """The engine behaviour the design relies on: overflow is loud, never silent.

    The loader rejects readings of 10^18 kWh and above, so one row is at most about
    6.7e19 GBP against 22 integer digits of headroom; a pathological sum could still
    exceed DECIMAL(38,16). DuckDB raises OutOfRangeException rather than wrapping, so
    the failure mode is an error, not a wrong total.
    """
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE big(v DECIMAL(38,16))")
        con.execute("INSERT INTO big VALUES (9e21), (9e21), (9e21)")
        with pytest.raises(duckdb.OutOfRangeException):
            con.execute("SELECT SUM(v) FROM big").fetchone()
        # and the types the fact actually carries, checked rather than assumed
        con.execute("CREATE TABLE t(c DECIMAL(28,10), p DECIMAL(9,6))")
        con.execute("INSERT INTO t VALUES (0.123, 0.672)")
        assert (
            con.execute("SELECT typeof(c*p) FROM t").fetchone()[0] == "DECIMAL(37,16)"
        )
        assert (
            con.execute(
                "SELECT typeof(SUM(CAST(c*p AS DECIMAL(38,16)))) FROM t"
            ).fetchone()[0]
            == "DECIMAL(38,16)"
        )
        assert con.execute("SELECT c*p FROM t").fetchone()[0] == Decimal("0.082656")
    finally:
        con.close()


# --------------------------------------------------------- joins cannot multiply
def test_the_join_cannot_multiply_consumption_rows(tmp_path):
    """48 readings against a 48-slot schedule must produce exactly 48 charged rows.

    The schedule key is unique, so an inner join is one-to-one. This is the arithmetic
    guarantee -- and it is *not* evidence that the two label sets mean the same thing.
    """
    rows = [
        row(
            "MAC000001",
            "ToU",
            f"2013-01-01 {slot // 2:02d}:{(slot % 2) * 30:02d}:00.0000000",
            " 0.25 ",
        )
        for slot in range(48)
    ]
    database = load(tmp_path, HEADER + b"".join(rows))
    schedule = demo_schedule()
    result = build_scenario(database, schedule)
    assert result.distinct_readings == 48
    assert result.included_readings == 48
    con = duckdb.connect(str(database), read_only=True)
    try:
        assert (
            con.execute(
                "SELECT COUNT(*) FROM fact_interval_charge_scenario"
            ).fetchone()[0]
            == 48
        )
        assert (
            con.execute(
                "SELECT COUNT(*) FROM (SELECT source_timestamp_text FROM "
                "fact_interval_charge_scenario GROUP BY 1 HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            == 0
        )
    finally:
        con.close()


def test_repeated_autumn_labels_are_resolved_by_policy_not_by_evidence(tmp_path):
    """Two rows at 2013-10-27 01:00, the label a UK local clock would repeat.

    Values 0.4 and 0.4 -- identical, so the duplicate policy collapses them and the
    label is charged once at 0.4 kWh. That is our analytical resolution. It is NOT
    proof the two rows are one physical half hour: if the labels were local wall-clock
    time, they would be two distinct half hours and the correct answer would be 0.8.
    The test pins the behaviour and the docstring records what it does not establish.
    """
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-10-27 01:00:00.0000000", " 0.4 "),
            row("MAC000001", "ToU", "2013-10-27 01:00:00.0000000", " 0.4 "),
        ]
    )
    database = load(tmp_path, body)
    schedule = make_schedule([("2013-10-27 01:00:00", "Normal")])
    result = build_scenario(database, schedule)
    assert result.raw_rows == 2
    assert result.rows_collapsed_by_policy == 1
    assert result.included_readings == 1
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("0.047040")


def test_repeated_autumn_labels_that_disagree_are_withheld_not_summed(tmp_path):
    """The same label twice with different values is a conflict: no charge at all."""
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-10-27 01:00:00.0000000", " 0.4 "),
            row("MAC000001", "ToU", "2013-10-27 01:00:00.0000000", " 0.6 "),
        ]
    )
    database = load(tmp_path, body)
    schedule = make_schedule([("2013-10-27 01:00:00", "Normal")])
    result = build_scenario(database, schedule)
    assert result.included_readings == 0
    assert result.reasons == {"conflicting_label": 2}
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal(0)


def test_equivalent_representations_are_charged_once(tmp_path):
    """' 0.5 ' and ' 0.50 ' at one label are one value: 0.5 x 11.76 / 100 = 0.0588."""
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 0.5 "),
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 0.50 "),
        ]
    )
    database = load(tmp_path, body)
    schedule = make_schedule([("2013-01-01 00:30:00", "Normal")])
    result = build_scenario(database, schedule)
    assert result.raw_rows == 2
    assert result.included_readings == 1
    assert Decimal(result.total_energy_charge_gbp_exact) == Decimal("0.0588")


# ------------------------------------------------------------------ reproducibility
def test_every_charged_row_carries_the_assumption(tmp_path):
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
    database = load(tmp_path, body)
    result = build_scenario(database, make_schedule([("2013-01-01 00:30:00", "Low")]))
    con = duckdb.connect(str(database), read_only=True)
    try:
        assert con.execute(
            "SELECT DISTINCT assumption_id FROM fact_interval_charge_scenario"
        ).fetchall() == [(ASSUMPTION_ID,)]
        assert (
            con.execute(
                "SELECT assumption_ids FROM scenario_run WHERE run_id = ?",
                [result.run_id],
            ).fetchone()[0]
            == ASSUMPTION_ID
        )
    finally:
        con.close()


def test_rerunning_unchanged_inputs_is_a_no_op(tmp_path):
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
    database = load(tmp_path, body)
    schedule = make_schedule([("2013-01-01 00:30:00", "Low")])
    first = build_scenario(database, schedule)
    second = build_scenario(database, schedule)
    assert not first.skipped
    assert second.skipped
    assert second.run_id == first.run_id
    con = duckdb.connect(str(database), read_only=True)
    try:
        assert (
            con.execute(
                "SELECT COUNT(*) FROM fact_interval_charge_scenario"
            ).fetchone()[0]
            == 1
        )
        assert (
            con.execute(
                "SELECT COUNT(*) FROM scenario_run WHERE status = 'published'"
            ).fetchone()[0]
            == 1
        )
    finally:
        con.close()


def test_a_changed_schedule_supersedes_the_previous_run(tmp_path):
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
    database = load(tmp_path, body)
    first = build_scenario(database, make_schedule([("2013-01-01 00:30:00", "Low")]))
    second = build_scenario(database, make_schedule([("2013-01-01 00:30:00", "High")]))
    assert second.run_id != first.run_id
    assert second.replaced_previous
    assert Decimal(first.total_energy_charge_gbp_exact) == Decimal("0.0399")
    assert Decimal(second.total_energy_charge_gbp_exact) == Decimal("0.672")
    con = duckdb.connect(str(database), read_only=True)
    try:
        statuses = dict(
            con.execute("SELECT run_id, status FROM scenario_run").fetchall()
        )
        assert statuses[first.run_id] == "superseded"
        assert statuses[second.run_id] == "published"
        assert (
            con.execute(
                "SELECT COUNT(*) FROM fact_interval_charge_scenario WHERE run_id = ?",
                [first.run_id],
            ).fetchone()[0]
            == 0
        )
    finally:
        con.close()


def test_the_fingerprint_covers_schedule_prices_code_and_data():
    schedule = demo_schedule()
    base = scenario_fingerprint(schedule, ["archive|m0|aa|pp"], "ToU")
    assert base != scenario_fingerprint(schedule, ["archive|m1|bb|pp"], "ToU")
    assert base != scenario_fingerprint(schedule, ["archive|m0|aa|pp"], "Std")
    other = Schedule(schedule.rows, schedule.source, "f" * 64)
    assert base != scenario_fingerprint(other, ["archive|m0|aa|pp"], "ToU")
    assert len(tariff_code_fingerprint()) == 64


def test_identical_content_loaded_twice_fingerprints_the_same(tmp_path):
    """Two fresh databases built from the same bytes must agree.

    The fingerprint keys on the **content** of each published load, not on the load
    event: a load id carries the moment of loading, so keying on it would make the
    fingerprint depend on when the warehouse happened to be built and no replay could
    ever reproduce it. Replaying a captured baseline is what exposed that.
    """
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
    schedule = make_schedule([("2013-01-01 00:30:00", "Low")])
    # Different archive file names on purpose: where the bytes were found is not what
    # they are, so the same member content must fingerprint the same either way.
    first = build_scenario(load(tmp_path, body, name="one.zip"), schedule)
    second = build_scenario(load(tmp_path, body, name="two.zip"), schedule)
    assert first.scenario_fingerprint == second.scenario_fingerprint
    assert first.total_energy_charge_gbp_exact == second.total_energy_charge_gbp_exact


def test_the_run_record_holds_what_reproduction_needs(tmp_path):
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
    database = load(tmp_path, body)
    build_scenario(database, make_schedule([("2013-01-01 00:30:00", "Low")]))
    run = ta.latest_run(database)
    assert run is not None
    assert run.schedule_sha256
    assert run.calculation_code_sha256 and run.policy_sha256 and run.model_code_sha256
    assert run.runtime_fingerprint
    assert run.ingestion_pipeline_fingerprint
    assert run.price_catalogue_version == pr.PRICE_CATALOGUE_VERSION
    assert run.source_load_ids
    assert "not established" in run.assumption_text.lower()
    assert set(run.runtime) >= {"python", "duckdb"}


# ------------------------------------------------------------------- analytics
def test_shares_use_the_stated_denominators(tmp_path):
    """2 kWh High and 8 kWh Low: consumption shares 20/80, charge shares from price.

    High charge 2 x 0.6720 = 1.3440; Low charge 8 x 0.0399 = 0.3192; total 1.6632.
    High charge share = 1.3440 / 1.6632 = 0.80808... -> 0.8081 at four places.
    """
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 "),
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 8 "),
        ]
    )
    database = load(tmp_path, body)
    schedule = make_schedule(
        [("2013-01-01 00:30:00", "High"), ("2013-01-01 01:00:00", "Low")]
    )
    result = build_scenario(database, schedule)
    bands = ta.band_summary(database, result.run_id)
    assert bands.attrs["denominator_kwh_exact"] == "10.0000000000"
    assert Decimal(bands.attrs["denominator_charge_gbp_exact"]) == Decimal("1.6632")
    shares = dict(zip(bands["band_label"], bands["consumption_share"], strict=True))
    charge_shares = dict(zip(bands["band_label"], bands["charge_share"], strict=True))
    assert shares["High"] == pytest.approx(0.2)
    assert shares["Low"] == pytest.approx(0.8)
    assert charge_shares["High"] == pytest.approx(0.8081)
    assert charge_shares["Low"] == pytest.approx(0.1919)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_schedule_wide_results_do_not_depend_on_loaded_households(tmp_path):
    """The schedule view describes the schedule. Loading nothing changes it."""
    body = HEADER + row("MAC000001", "Std", "2011-01-01 00:30:00.0000000", " 1 ")
    database = load(tmp_path, body)
    build_scenario(database, demo_schedule())
    totals = ta.schedule_totals(database)
    assert totals.attrs["denominator_slots"] == 48
    slots = dict(zip(totals["band_label"], totals["slots"], strict=True))
    assert slots == {"Normal": 46, "Low": 1, "High": 1}
    assert ta.band_summary(database, ta.latest_run(database).run_id).empty


def test_household_filter_narrows_to_one_household(tmp_path):
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 "),
            row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 3 "),
        ]
    )
    database = load(tmp_path, body)
    result = build_scenario(database, make_schedule([("2013-01-01 00:30:00", "Low")]))
    everyone = ta.band_summary(database, result.run_id)
    mine = ta.band_summary(database, result.run_id, household="MAC000001")
    assert Decimal(everyone.attrs["denominator_kwh_exact"]) == Decimal(4)
    assert Decimal(mine.attrs["denominator_kwh_exact"]) == Decimal(1)
    assert int(mine["households"].iloc[0]) == 1


def test_tariff_group_stability_is_measured_not_assumed(tmp_path):
    """A household recorded under two groups must be reported, not silently merged."""
    body = HEADER + b"".join(
        [
            row("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 1 "),
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 1 "),
            row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 1 "),
        ]
    )
    database = load(tmp_path, body)
    unstable = ta.tariff_group_stability(database)
    assert list(unstable["household_id"]) == ["MAC000001"]


def test_no_scenario_yet_reports_none(tmp_path):
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
    database = load(tmp_path, body)
    assert ta.latest_run(database) is None


def test_share_percent_rounds_once_from_the_exact_values():
    """The Normal band's charge share: 8505.52… of 11675.43… is 72.8497%, which is 72.8%
    when rounded once. Rounding the four-place share (0.7285) again gives 72.9%, which is
    the defect this helper exists to prevent."""
    part = Decimal("8505.5227817414400000")
    whole = Decimal("11675.4339216532500000")
    assert ta.share_percent(part, whole) == Decimal("72.8")
    twice = (ta.round_share(part / whole) * 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    assert twice == Decimal("72.9")
    assert ta.share_percent(Decimal(1), Decimal(0)) is None
    assert ta.share_percent(Decimal("0.0005"), Decimal(1)) == Decimal("0.1")
    assert ta.share_percent(part, whole, places=2) == Decimal("72.85")
