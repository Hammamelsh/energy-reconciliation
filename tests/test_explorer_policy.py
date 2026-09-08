"""Conflicts, equivalent representations, and the timestamp-step policy.

Each fixture's expected numbers are worked out by hand in its docstring.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from conftest import HEADER, build_archive
from conftest import row as make_row

from energy_reconciliation.explorer import charts
from energy_reconciliation.explorer import queries as q
from energy_reconciliation.ingest.loader import load_member

MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"
HH = "MAC000001"
D1, D2, D3 = date(2013, 1, 1), date(2013, 1, 2), date(2013, 1, 3)


def build(tmp_path, rows):
    archive = build_archive(
        tmp_path, {MEMBER: HEADER + b"".join(make_row(*r) for r in rows)}
    )
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER, db)
    return db


def r(ts: str, val: str, hh: str = HH):
    return (hh, "Std", f"{ts}.0000000", val)


# ============================================================ 1. conflicting totals
@pytest.fixture
def conflict_day(tmp_path):
    """1 Jan: 0.1, 0.2, then 03:00 carries 0.3 AND 0.9 (conflict). 2 Jan: clean 1.0 + 2.0."""
    return build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.1 "),
            r("2013-01-01 00:30:00", " 0.2 "),
            r("2013-01-01 03:00:00", " 0.3 "),
            r("2013-01-01 03:00:00", " 0.9 "),
            r("2013-01-02 00:00:00", " 1.0 "),
            r("2013-01-02 00:30:00", " 2.0 "),
        ],
    )


def test_conflict_day_total_is_withheld_not_numeric(conflict_day):
    daily = q.daily_totals(conflict_day, HH, D1, D2)
    day1 = daily[daily["source_date"].dt.date == D1].iloc[0]
    assert day1["total_status"] == "withheld"
    assert pd.isna(day1["recorded_kwh"]), "no number may exist for a disputed day"
    assert day1["recorded_kwh_text"] == ""
    assert day1["status"] == "conflicting readings"
    assert day1["contributing_readings"] == 0, "nothing contributes to a withheld total"
    assert day1["available_readings"] == 4, (
        "readings that exist stay visible: 0.1, 0.2, 0.3, 0.9"
    )


def test_unaffected_day_total_is_preserved(conflict_day):
    daily = q.daily_totals(conflict_day, HH, D1, D2)
    day2 = daily[daily["source_date"].dt.date == D2].iloc[0]
    assert day2["total_status"] == "published"
    assert day2["recorded_kwh_text"] == "3"
    assert day2["contributing_readings"] == 2


def test_period_total_withheld_when_any_day_conflicts(conflict_day):
    whole = q.period_summary(conflict_day, HH, D1, D2)
    assert whole.total_kwh is None and whole.contributing_readings == 0
    assert whole.available_readings == 6, (
        "available is reported even when the total is not"
    )
    clean = q.period_summary(conflict_day, HH, D2, D2)
    assert clean.total_kwh == Decimal("3.0") and clean.contributing_readings == 2


def test_daily_chart_never_draws_a_bar_for_a_withheld_day(conflict_day):
    """Inspect the spec the UI renders, not a helper the UI ignores."""
    daily = q.daily_totals(conflict_day, HH, D1, D2)
    spec = charts.daily_chart(daily).to_dict()
    bar_layer, marker_layer = spec["layer"]
    assert bar_layer["mark"]["type"] == "bar"
    bar_rows = spec["datasets"][bar_layer["data"]["name"]]
    marker_rows = spec["datasets"][marker_layer["data"]["name"]]
    assert [row["source_date"][:10] for row in bar_rows] == ["2013-01-02"]
    assert [row["source_date"][:10] for row in marker_rows] == ["2013-01-01"]
    assert marker_layer["mark"]["type"] == "text"
    assert marker_layer["encoding"]["y"] == {"value": 0}, "marker encodes no quantity"
    assert marker_rows[0]["status"] == "conflicting readings"
    assert marker_rows[0]["recorded_label"].startswith("withheld")
    assert marker_rows[0]["contributing_label"].startswith("not applicable")


def test_detail_flags_conflicting_points_and_breaks_the_line(conflict_day):
    detail = q.half_hour_detail(conflict_day, HH, D1)
    assert list(detail.conflicts["consumption_raw_text"]) == [" 0.3 ", " 0.9 "]
    assert set(detail.conflicts.columns) >= {"member_name", "source_record_no"}
    labels = list(detail.series["source_timestamp_text"].dropna())
    assert "2013-01-01 03:00:00.0000000" not in labels, (
        "the line never passes through it"
    )
    kinds = list(detail.series["value_category"])
    assert kinds.count("line_break") >= 1
    spec = charts.detail_chart(
        detail.series, detail.conflicts, detail.off_grid
    ).to_dict()
    point_layer = spec["layer"][1]
    assert point_layer["mark"]["type"] == "point"
    assert len(spec["datasets"][point_layer["data"]["name"]]) == 2
    assert "source_record_no" in {
        t["field"] for t in point_layer["encoding"]["tooltip"]
    }


def test_demo_household_expected_results():
    """The committed synthetic demo, exact numbers the app must show for DEMO0001."""
    from pathlib import Path

    db = Path("data/warehouse/demo.duckdb")
    if not db.exists():
        pytest.skip("demo warehouse not loaded")
    d = date(2013, 1, 1)
    p = q.period_summary(db, "DEMO0001", d, d)
    s = q.quality_summary(db, "DEMO0001", d, d)
    assert p.total_kwh is None and p.contributing_readings == 0
    assert p.available_readings == 8
    assert (s.duplicates_removed, s.equivalent_representations, s.conflicting_keys) == (
        1,
        0,
        1,
    )
    assert (s.null_tokens, s.gaps, s.off_grid_observations) == (1, 0, 1)
    assert p.issues_for_review == 3, "missing 1 + gaps 0 + conflicts 1 + off-grid 1"
    daily = q.daily_totals(db, "DEMO0001", d, d).iloc[0]
    assert daily["total_status"] == "withheld" and pd.isna(daily["recorded_kwh"])
    p2 = q.period_summary(db, "DEMO0002", d, d)
    assert p2.total_kwh == Decimal("2.125") and p2.contributing_readings == 2


# ======================================================== 2. timestamp-step policy
def test_normal_midnight_transition_is_not_a_gap(tmp_path):
    db = build(
        tmp_path, [r("2013-01-01 23:30:00", " 0.1 "), r("2013-01-02 00:00:00", " 0.2 ")]
    )
    assert q.step_anomalies(db, HH, D1, D2)["gaps"].empty


def test_overnight_gap_counted_once_and_attributed_to_the_later_date(tmp_path):
    db = build(
        tmp_path,
        [
            r("2013-01-01 22:00:00", " 0.1 "),
            r("2013-01-02 06:00:00", " 0.2 "),
            r("2013-01-02 06:30:00", " 0.3 "),
        ],
    )
    gaps = q.step_anomalies(db, HH, D1, D2)["gaps"]
    assert len(gaps) == 1 and int(gaps.iloc[0]["step_seconds"]) == 8 * 3600
    assert pd.Timestamp(gaps.iloc[0]["attributed_date"]).date() == D2
    daily = q.daily_totals(db, HH, D1, D2)
    assert (
        int(daily["gaps_observed"].sum()) == q.period_summary(db, HH, D1, D2).gaps == 1
    )
    assert daily.set_index(daily["source_date"].dt.date).loc[D2, "gaps_observed"] == 1


def test_gap_across_the_selection_edge_is_not_counted(tmp_path):
    db = build(
        tmp_path, [r("2013-01-01 22:00:00", " 0.1 "), r("2013-01-02 06:00:00", " 0.2 ")]
    )
    assert len(q.step_anomalies(db, HH, D1, D2)["gaps"]) == 1
    assert q.step_anomalies(db, HH, D2, D2)["gaps"].empty, (
        "the 1 Jan reading is out of scope"
    )
    assert q.period_summary(db, HH, D2, D2).total_kwh == Decimal("0.2"), (
        "no neighbour leaks in"
    )


def test_exact_duplicates_create_no_gap_and_no_repeat(tmp_path):
    db = build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.1 "),
            r("2013-01-01 00:00:00", " 0.1 "),
            r("2013-01-01 00:30:00", " 0.2 "),
        ],
    )
    s = q.quality_summary(db, HH, D1, D1)
    assert s.gaps == 0 and s.repeated_timestamps == 0 and s.duplicates_removed == 1


def test_off_grid_observation_is_counted_separately_never_as_a_gap(tmp_path):
    db = build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.1 "),
            r("2013-01-01 00:17:23", "Null"),
            r("2013-01-01 00:30:00", " 0.2 "),
        ],
    )
    steps = q.step_anomalies(db, HH, D1, D1)
    assert steps["gaps"].empty, "grid labels 00:00 -> 00:30 are 1800 s apart"
    assert len(steps["off_grid"]) == 1
    s = q.quality_summary(db, HH, D1, D1)
    assert s.off_grid_observations == 1 and s.gaps == 0
    daily = q.daily_totals(db, HH, D1, D1).iloc[0]
    assert daily["off_grid_rows"] == 1 and daily["gaps_observed"] == 0
    p = q.period_summary(db, HH, D1, D1)
    assert p.total_kwh == Decimal("0.3"), (
        "0.1 + 0.2; the off-grid Null contributes nothing"
    )


# =============================================== 3. equivalent representations
@pytest.fixture
def three_kinds(tmp_path):
    """00:00 exact duplicate; 00:30 equivalent ' 0.5 '/' 0.50 '; 01:00 true conflict."""
    return build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.1 "),
            r("2013-01-01 00:00:00", " 0.1 "),
            r("2013-01-01 00:30:00", " 0.5 "),
            r("2013-01-01 00:30:00", " 0.50 "),
            r("2013-01-01 01:00:00", " 0.3 "),
            r("2013-01-01 01:00:00", " 0.9 "),
        ],
    )


def test_three_kinds_of_repetition_are_kept_apart(three_kinds):
    agreement = q.label_agreement(three_kinds, HH, D1, D1)
    assert list(agreement["kind"]) == [
        "exact_duplicate",
        "equivalent_representation",
        "conflict",
    ]
    s = q.quality_summary(three_kinds, HH, D1, D1)
    assert (s.duplicates_removed, s.equivalent_representations, s.conflicting_keys) == (
        1,
        1,
        1,
    )
    assert s.repeated_timestamps == 2, (
        "equivalent + conflict; the exact duplicate is not a repeat"
    )
    assert s.candidate_key_collisions == 3


def test_equivalent_representations_are_kept_as_evidence_and_counted_once(tmp_path):
    db = build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.5 "),
            r("2013-01-01 00:00:00", " 0.50 "),
            r("2013-01-01 00:30:00", " 0.2 "),
        ],
    )
    s = q.quality_summary(db, HH, D1, D1)
    assert s.conflicting_keys == 0, "numerically equal values are not a conflict"
    assert s.equivalent_representations == 1
    assert s.duplicates_removed == 0, "different texts are not exact duplicates"
    assert q.observation_count(db, HH, D1, D1) == 3, "both rows survive as evidence"
    p = q.period_summary(db, HH, D1, D1)
    assert p.total_kwh == Decimal("0.7"), "0.5 once, plus 0.2 — never 0.5 + 0.50"
    assert p.contributing_readings == 2
    assert p.issues_for_review == 0
    assert "equivalent representations" in q.review_status(p).detail
    equiv = q.equivalent_representations(db, HH, D1, D1)
    assert len(equiv) == 1 and set(equiv.iloc[0]["texts"].split(" | ")) == {
        " 0.5 ",
        " 0.50 ",
    }


def test_null_beside_a_number_is_a_conflict(tmp_path):
    db = build(
        tmp_path, [r("2013-01-01 00:00:00", " 0.5 "), r("2013-01-01 00:00:00", "Null")]
    )
    s = q.quality_summary(db, HH, D1, D1)
    assert s.conflicting_keys == 1 and s.equivalent_representations == 0


def test_detail_series_keeps_off_grid_points_distinguishable(tmp_path):
    """Under the current policy an off-grid point never enters the grid series.

    It is plotted from its own frame, with provenance, and the grid series carries
    ``on_half_hour_grid`` so nothing in it can be mistaken for an off-grid reading.
    """
    db = build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.1 "),
            r("2013-01-01 00:17:23", " 0.9 "),
            r("2013-01-01 00:30:00", " 0.2 "),
        ],
    )
    detail = q.half_hour_detail(db, HH, D1)
    series = detail.series[detail.series["value_category"] != "line_break"]
    assert "2013-01-01 00:17:23.0000000" not in list(series["source_timestamp_text"])
    assert series["on_half_hour_grid"].all(), "the grid series holds grid readings only"
    assert list(detail.off_grid["source_timestamp_text"]) == [
        "2013-01-01 00:17:23.0000000"
    ]
    assert {"member_name", "source_record_no", "consumption_raw_text"} <= set(
        detail.off_grid.columns
    )
    spec = charts.detail_chart(
        detail.series, detail.conflicts, detail.off_grid
    ).to_dict()
    off_layer = spec["layer"][2]
    assert off_layer["mark"]["type"] == "point"
    assert "source_record_no" in {
        tt["field"] for tt in off_layer["encoding"]["tooltip"]
    }
    assert q.step_anomalies(db, HH, D1, D1)["gaps"].empty, "still not a gap"


# ============================================ off-grid excluded from half-hour totals
def test_off_grid_finite_reading_is_excluded_from_totals_but_kept_visible(tmp_path):
    """Policy: an off-grid value is recorded evidence, not part of the half-hour series."""
    db = build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.1 "),
            r("2013-01-01 00:17:23", " 0.9 "),
            r("2013-01-01 00:30:00", " 0.2 "),
        ],
    )
    p = q.period_summary(db, HH, D1, D1)
    assert p.total_kwh == Decimal("0.3"), "0.9 is off-grid and must not be summed"
    assert p.contributing_readings == 2
    assert p.available_readings == 3, "but it is still counted as recorded"
    assert p.off_grid_observations == 1
    assert p.issues_for_review == 1, "an excluded reading is an item for review"
    assert "off-grid" in q.review_status(p).detail
    daily = q.daily_totals(db, HH, D1, D1).iloc[0]
    assert daily["recorded_kwh_text"] == "0.3" and daily["off_grid_rows"] == 1
    detail = q.half_hour_detail(db, HH, D1)
    assert "2013-01-01 00:17:23.0000000" not in list(
        detail.series["source_timestamp_text"].dropna()
    )
    assert list(detail.off_grid["consumption_raw_text"]) == [" 0.9 "]
    assert {"member_name", "source_record_no"} <= set(detail.off_grid.columns)
    spec = charts.detail_chart(
        detail.series, detail.conflicts, detail.off_grid
    ).to_dict()
    assert len(spec["layer"]) == 3
    off_layer = spec["layer"][2]
    assert len(spec["datasets"][off_layer["data"]["name"]]) == 1
    assert "source_record_no" in {t["field"] for t in off_layer["encoding"]["tooltip"]}


def test_null_beside_number_withholds_and_preserves_both_rows(tmp_path):
    """Our analytical policy: a Null and a number at one label is an unresolved
    disagreement. Both rows survive; nothing infers which one the meter produced."""
    db = build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.5 "),
            r("2013-01-01 00:00:00", "Null"),
            r("2013-01-01 00:30:00", " 0.2 "),
        ],
    )
    p = q.period_summary(db, HH, D1, D1)
    assert p.total_kwh is None and p.conflicts_in_period == 1
    assert q.observation_count(db, HH, D1, D1) == 3
    detail = q.half_hour_detail(db, HH, D1)
    assert sorted(detail.conflicts["consumption_raw_text"]) == [" 0.5 ", "Null"]
    assert "publisher" not in q.review_status(p).detail.lower()


# ==================================================== all-unavailable chart state
def test_status_strip_when_nothing_is_publishable(tmp_path):
    """Conflict on 1 Jan, nothing on 2 Jan, only a Null on 3 Jan: no kWh axis at all."""
    db = build(
        tmp_path,
        [
            r("2013-01-01 00:00:00", " 0.3 "),
            r("2013-01-01 00:00:00", " 0.9 "),
            r("2013-01-03 00:00:00", "Null"),
        ],
    )
    daily = q.daily_totals(db, HH, D1, D3)
    assert list(daily["total_status"]) == ["withheld", "none", "none"]
    assert list(daily["status"]) == [
        "conflicting readings",
        "no readings recorded",
        "for review",
    ]
    spec = charts.daily_chart(daily).to_dict()
    assert "layer" not in spec, "a single status strip, not the bar+marker layering"
    assert spec["mark"]["type"] == "text"
    assert "y" not in spec["encoding"], "no kWh axis when no total is publishable"
    rows = spec["datasets"][spec["data"]["name"]]
    labels = {row["source_date"][:10]: row["recorded_label"] for row in rows}
    assert labels["2013-01-01"].startswith("withheld")
    assert labels["2013-01-02"] == "no observations"
    assert labels["2013-01-03"] == "no half-hour-grid readings"


def test_mixed_selection_keeps_bars_for_valid_days(conflict_day):
    daily = q.daily_totals(conflict_day, HH, D1, D2)
    spec = charts.daily_chart(daily).to_dict()
    assert "layer" in spec and spec["layer"][0]["mark"]["type"] == "bar"
    assert len(spec["datasets"][spec["layer"][0]["data"]["name"]]) == 1
