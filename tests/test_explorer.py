"""Explorer query behaviour: date filtering, policies, gaps, empty selections."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import HEADER, build_archive
from conftest import row as make_row

from energy_reconciliation.explorer import queries as q
from energy_reconciliation.ingest.loader import load_member

MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"


def build(tmp_path, rows):
    archive = build_archive(
        tmp_path, {MEMBER: HEADER + b"".join(make_row(*r) for r in rows)}
    )
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER, db)
    return db


def day_rows(day: str, values, household="MAC000001", start_half=0):
    out = []
    for i, val in enumerate(values):
        hour, half = divmod(start_half + i, 2)
        out.append(
            (household, "Std", f"{day} {hour:02d}:{half * 30:02d}:00.0000000", val)
        )
    return out


@pytest.fixture
def three_days(tmp_path):
    rows = (
        day_rows("2013-01-01", [" 0.1 ", " 0.2 ", " 0.3 "])
        + day_rows("2013-01-02", [" 1.0 ", " 2.0 "])
        + day_rows("2013-01-03", [" 0.5 "])
    )
    return build(tmp_path, rows)


# -- date filtering -----------------------------------------------------------


def test_daily_totals_respect_the_date_range(three_days):
    frame = q.daily_totals(three_days, "MAC000001", date(2013, 1, 1), date(2013, 1, 2))
    assert list(frame["source_date"].dt.date) == [date(2013, 1, 1), date(2013, 1, 2)]
    assert float(frame["recorded_kwh"].sum()) == pytest.approx(3.6)


def test_period_summary_only_counts_the_selected_range(three_days):
    whole = q.period_summary(
        three_days, "MAC000001", date(2013, 1, 1), date(2013, 1, 3)
    )
    one_day = q.period_summary(
        three_days, "MAC000001", date(2013, 1, 2), date(2013, 1, 2)
    )
    assert whole.total_kwh == Decimal("4.1")
    assert one_day.total_kwh == Decimal("3.0")
    assert one_day.contributing_readings == 2


def test_empty_selection_returns_zero_not_an_error(three_days):
    empty = q.period_summary(
        three_days, "MAC000001", date(2012, 5, 1), date(2012, 5, 2)
    )
    assert empty.total_kwh == Decimal(0)
    assert empty.contributing_readings == 0
    assert q.daily_totals(
        three_days, "MAC000001", date(2012, 5, 1), date(2012, 5, 2)
    ).empty
    assert (
        q.observation_count(three_days, "MAC000001", date(2012, 5, 1), date(2012, 5, 2))
        == 0
    )


def test_default_window_is_relative_to_the_household_not_today(three_days):
    start, end = q.default_window(three_days, "MAC000001", days=2)
    assert end == date(2013, 1, 3), "must end at the household's last recorded date"
    assert start == date(2013, 1, 2)
    assert end.year == 2013, "must not drift toward the current date"


# -- gaps versus repeats ------------------------------------------------------


def test_gaps_and_repeated_timestamps_are_reported_separately(tmp_path):
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.1 "),
            ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.2 "),
            # 01:00 absent -> a gap
            ("MAC000001", "Std", "2013-01-01 01:30:00.0000000", " 0.3 "),
            # a repeated timestamp carrying a different value
            ("MAC000001", "Std", "2013-01-01 02:00:00.0000000", " 0.4 "),
            ("MAC000001", "Std", "2013-01-01 02:00:00.0000000", " 0.9 "),
        ],
    )
    steps = q.step_anomalies(db, "MAC000001")
    assert len(steps["gaps"]) == 1, "one step longer than half an hour"
    assert int(steps["gaps"].iloc[0]["step_seconds"]) == 3600
    summary = q.quality_summary(db, "MAC000001")
    assert summary.repeated_timestamps == 1, "02:00 carries two values: a repeat"
    assert summary.conflicting_keys == 1, "and because they differ, a conflict"


def test_exact_duplicates_do_not_create_phantom_repeats(tmp_path):
    """A duplicated row is not a repeated timestamp in the series sense."""
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.1 "),
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.1 "),
            ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.2 "),
        ],
    )
    steps = q.step_anomalies(db, "MAC000001")
    assert steps["gaps"].empty, "identical readings collapse before stepping"
    assert q.quality_summary(db, "MAC000001").repeated_timestamps == 0
    assert steps["gaps"].empty


# -- chart gaps ---------------------------------------------------------------


def test_chart_breaks_the_line_across_an_absent_timestamp(tmp_path):
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.1 "),
            ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.2 "),
            # 01:00 and 01:30 absent
            ("MAC000001", "Std", "2013-01-01 02:00:00.0000000", " 0.3 "),
        ],
    )
    frame = q.chart_series(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    breaks = frame[frame["value_category"] == "line_break"]
    assert len(breaks) == 1, "one break inserted at the gap"
    assert breaks.iloc[0]["recorded_kwh"] is None or pd_isna(
        breaks.iloc[0]["recorded_kwh"]
    )
    assert len(frame) == 4, "three readings plus one break row"


def test_chart_does_not_break_a_continuous_series(tmp_path):
    db = build(tmp_path, day_rows("2013-01-01", [" 0.1 ", " 0.2 ", " 0.3 "]))
    frame = q.chart_series(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert (frame["value_category"] == "line_break").sum() == 0


def test_missing_values_stay_blank_in_the_chart(tmp_path):
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.1 "),
            ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", "Null"),
            ("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.3 "),
        ],
    )
    frame = q.chart_series(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert (frame["value_category"] == "line_break").sum() == 0, "no gap: rows exist"
    assert frame["recorded_kwh"].isna().sum() == 1, "the Null is a blank point"


def pd_isna(value) -> bool:
    import pandas as pd

    return bool(pd.isna(value))


# -- consistent duplicate policy ---------------------------------------------


def test_total_and_counters_use_the_same_duplicate_policy(tmp_path):
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.25 "),
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.25 "),
            ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.75 "),
        ],
    )
    s = q.quality_summary(db, "MAC000001")
    p = q.period_summary(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert s.observed_records - s.exact_duplicate_extras == s.distinct_readings
    assert p.total_kwh == Decimal("1.00"), "the duplicate is counted once"
    assert p.contributing_readings == 2
    chart = q.chart_series(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert len(chart) == 2, "the chart plots the same deduplicated readings"


def test_conflict_withholds_the_period_total_only_when_in_range(tmp_path):
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.3 "),
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.9 "),
            ("MAC000001", "Std", "2013-01-05 00:00:00.0000000", " 1.0 "),
        ],
    )
    affected = q.period_summary(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 5))
    assert affected.total_kwh is None
    assert "disagreeing" in affected.withheld_reason

    clear = q.period_summary(db, "MAC000001", date(2013, 1, 5), date(2013, 1, 5))
    assert clear.total_kwh == Decimal("1.0"), "a clean period still reports a total"
    assert clear.conflicts_in_period == 0


# -- pagination and traceability ---------------------------------------------


def test_observations_paginate_and_keep_source_references(three_days):
    total = q.observation_count(
        three_days, "MAC000001", date(2013, 1, 1), date(2013, 1, 3)
    )
    assert total == 6
    first = q.observations(
        three_days, "MAC000001", date(2013, 1, 1), date(2013, 1, 3), limit=4
    )
    second = q.observations(
        three_days, "MAC000001", date(2013, 1, 1), date(2013, 1, 3), limit=4, offset=4
    )
    assert len(first) == 4 and len(second) == 2
    assert set(first.columns) >= {"member_name", "source_record_no"}
    assert list(second["source_record_no"]) == [5, 6]


# =============================================================================
# Review pass: one selection scope, boundary handling, honest status wording
# =============================================================================


@pytest.fixture
def span_with_issues(tmp_path):
    """Five source dates, 1 Jan – 5 Jan 2013, with something on most days.

    1 Jan: 3 clean readings (a boundary day).
    2 Jan: readings at 00:00 and 00:30, then 02:00 -> one gap of 5400 s.
    3 Jan: a repeated identical reading (duplicate) and a Null.
    4 Jan: nothing recorded at all.
    5 Jan: one reading (the other boundary day).
    """
    rows = [
        ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.1 "),
        ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.2 "),
        ("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.3 "),
        ("MAC000001", "Std", "2013-01-02 00:00:00.0000000", " 0.4 "),
        ("MAC000001", "Std", "2013-01-02 00:30:00.0000000", " 0.5 "),
        ("MAC000001", "Std", "2013-01-02 02:00:00.0000000", " 0.6 "),
        ("MAC000001", "Std", "2013-01-03 00:00:00.0000000", " 0.7 "),
        ("MAC000001", "Std", "2013-01-03 00:00:00.0000000", " 0.7 "),  # duplicate
        ("MAC000001", "Std", "2013-01-03 00:30:00.0000000", "Null"),
        ("MAC000001", "Std", "2013-01-05 00:00:00.0000000", " 0.9 "),
    ]
    return build(tmp_path, rows)


# -- 1. one shared scope ------------------------------------------------------


def test_quality_counters_are_scoped_to_the_selected_period(span_with_issues):
    """The Data quality tab must count the same rows the other tabs show."""
    db = span_with_issues
    period = q.quality_summary(db, "MAC000001", date(2013, 1, 3), date(2013, 1, 3))
    assert period.scope == "selected period"
    assert period.observed_records == 3  # two identical rows + the Null
    assert period.duplicates_removed == 1
    assert period.distinct_readings == 2
    assert period.null_tokens == 1
    assert period.gaps == 0, "the 2 Jan gap is outside this period"

    whole = q.quality_summary(db, "MAC000001")
    assert whole.scope == "whole loaded history"
    assert whole.observed_records == 10
    assert whole.gaps >= 1, "whole history sees the 2 Jan gap"


def test_raw_rows_distinct_and_contributing_reconcile_on_screen(span_with_issues):
    """626 vs 625 in the screenshots: raw − repeats = distinct; distinct − Null = counted."""
    db, s, e = span_with_issues, date(2013, 1, 1), date(2013, 1, 5)
    raw = q.observation_count(db, "MAC000001", s, e)
    quality = q.quality_summary(db, "MAC000001", s, e)
    period = q.period_summary(db, "MAC000001", s, e)
    assert raw == 10
    assert raw - quality.duplicates_removed == quality.distinct_readings == 9
    assert (
        quality.distinct_readings - quality.null_tokens
        == period.contributing_readings
        == 8
    )
    assert period.duplicates_removed == quality.duplicates_removed == 1


def test_gaps_are_internal_to_the_period(span_with_issues):
    """A gap straddling the period boundary is not an internal gap of that period."""
    db = span_with_issues
    inside = q.step_anomalies(db, "MAC000001", date(2013, 1, 2), date(2013, 1, 2))
    assert len(inside["gaps"]) == 1
    assert int(inside["gaps"].iloc[0]["step_seconds"]) == 5400
    only_first = q.step_anomalies(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert only_first["gaps"].empty


# -- 2. date handling ---------------------------------------------------------


def test_end_date_is_inclusive(span_with_issues):
    p = q.period_summary(
        span_with_issues, "MAC000001", date(2013, 1, 1), date(2013, 1, 2)
    )
    assert p.contributing_readings == 6, "readings on the end date itself must count"


def test_single_day_selection_is_valid(span_with_issues):
    p = q.period_summary(
        span_with_issues, "MAC000001", date(2013, 1, 5), date(2013, 1, 5)
    )
    assert p.contributing_readings == 1
    assert p.total_kwh == Decimal("0.9")


def test_presets_anchor_to_the_household_last_date(span_with_issues):
    start, end = q.preset_window(span_with_issues, "MAC000001", 7)
    assert end == date(2013, 1, 5)
    assert start == date(2013, 1, 1), "clipped to the first recorded date, not before"
    start3, end3 = q.preset_window(span_with_issues, "MAC000001", 3)
    assert (start3, end3) == (date(2013, 1, 3), date(2013, 1, 5))


def test_empty_range_gives_zero_and_no_fabricated_days(span_with_issues):
    p = q.period_summary(
        span_with_issues, "MAC000001", date(2012, 6, 1), date(2012, 6, 5)
    )
    assert p.total_kwh == Decimal(0) and p.contributing_readings == 0
    assert p.issues_for_review == 0
    daily = q.daily_totals(
        span_with_issues, "MAC000001", date(2012, 6, 1), date(2012, 6, 5)
    )
    assert daily.empty, "days outside the recorded span are never invented"


def test_household_switch_bounds_differ(tmp_path):
    """Two households with disjoint spans: bounds must come from the selected one."""
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.1 "),
            ("MAC000002", "Std", "2013-06-01 00:00:00.0000000", " 0.2 "),
        ],
    )
    assert q.date_bounds(db, "MAC000001") == (date(2013, 1, 1), date(2013, 1, 1))
    assert q.date_bounds(db, "MAC000002") == (date(2013, 6, 1), date(2013, 6, 1))
    assert q.preset_window(db, "MAC000002", 14) == (date(2013, 6, 1), date(2013, 6, 1))


# -- 3. no "48 = complete" assumption; boundary days visible ------------------


def test_a_day_with_no_rows_appears_as_no_readings_recorded(span_with_issues):
    daily = q.daily_totals(
        span_with_issues, "MAC000001", date(2013, 1, 1), date(2013, 1, 5)
    )
    assert len(daily) == 5, "4 Jan must appear even though it has no rows"
    jan4 = daily[daily["source_date"].dt.date == date(2013, 1, 4)].iloc[0]
    assert jan4["status"] == "no readings recorded"
    assert jan4["contributing_readings"] == 0
    assert pd_isna(jan4["recorded_kwh"]), "an absent day has no total, not a zero"


def test_boundary_days_are_flagged_not_excluded(span_with_issues):
    daily = q.daily_totals(
        span_with_issues, "MAC000001", date(2013, 1, 1), date(2013, 1, 5)
    )
    flagged = set(daily.loc[daily["is_boundary_day"], "source_date"].dt.date)
    assert flagged == {date(2013, 1, 1), date(2013, 1, 5)}
    jan5 = daily[daily["source_date"].dt.date == date(2013, 1, 5)].iloc[0]
    assert jan5["status"] == "boundary date"
    assert jan5["contributing_readings"] == 1, "still counted, with visible context"
    p = q.period_summary(
        span_with_issues, "MAC000001", date(2013, 1, 1), date(2013, 1, 5)
    )
    assert set(p.boundary_days) == flagged
    assert p.total_kwh == Decimal("3.7"), "boundary readings are in the total"
    # The column is DECIMAL(28,10), so the value arrives as 3.7000000000. Equality
    # with Decimal("3.7") is what proves there is no float noise; a wrapped float
    # would be 3.6999999999999997 and fail it. Normalise only to compare text.
    assert format(p.total_kwh.normalize(), "f") == "3.7"


def test_no_column_or_status_encodes_a_full_day_assumption(span_with_issues):
    daily = q.daily_totals(
        span_with_issues, "MAC000001", date(2013, 1, 1), date(2013, 1, 5)
    )
    assert "expected_readings" not in daily.columns
    assert not any("full day" in s for s in daily["status"])
    jan1 = daily[daily["source_date"].dt.date == date(2013, 1, 1)].iloc[0]
    assert jan1["status"] == "boundary date", (
        "three readings on a boundary day are context, not a completeness verdict"
    )


def test_per_day_duplicates_and_gaps_are_reported(span_with_issues):
    daily = q.daily_totals(
        span_with_issues, "MAC000001", date(2013, 1, 1), date(2013, 1, 5)
    )
    by_day = {
        d.date(): r
        for d, r in zip(daily["source_date"], daily.itertuples(), strict=True)
    }
    assert by_day[date(2013, 1, 3)].duplicates_removed == 1
    assert by_day[date(2013, 1, 3)].missing_values == 1
    assert by_day[date(2013, 1, 3)].status == "for review"
    # Two gaps end on 2 Jan: the internal 00:30 -> 02:00 step, AND the overnight
    # step from 1 Jan's last reading (01:00) to 2 Jan 00:00. Both are observed
    # steps longer than half an hour between consecutive recorded readings.
    assert by_day[date(2013, 1, 2)].gaps_observed == 2
    assert by_day[date(2013, 1, 2)].status == "for review"


# -- 4. status wording --------------------------------------------------------


def test_status_never_claims_no_concerns(span_with_issues):
    clean = q.period_summary(
        span_with_issues, "MAC000001", date(2013, 1, 1), date(2013, 1, 1)
    )
    status = q.review_status(clean)
    assert status.level == "clear"
    assert status.headline == "No detected conflicts or internal gaps"
    assert "no concerns" not in (status.headline + status.detail).lower()
    assert "unresolved" in status.standing_caveat
    assert "Boundary coverage" in status.standing_caveat


def test_status_keeps_duplicate_removal_visible_when_otherwise_clear(span_with_issues):
    p = q.period_summary(
        span_with_issues, "MAC000001", date(2013, 1, 3), date(2013, 1, 3)
    )
    status = q.review_status(p)
    assert status.level == "review", "the Null puts the day under review"
    assert "1 repeated identical reading" in status.detail
    assert p.issues_for_review == 1, "the collapsed duplicate is not an issue"


def test_status_levels_and_issue_count(span_with_issues):
    review = q.period_summary(
        span_with_issues, "MAC000001", date(2013, 1, 2), date(2013, 1, 3)
    )
    s = q.review_status(review)
    assert s.level == "review"
    # Gaps in 2-3 Jan: 00:30 -> 02:00 on 2 Jan, and 2 Jan 02:00 -> 3 Jan 00:00
    # overnight. Plus one missing value on 3 Jan. The overnight step counts: it is
    # a real interval between consecutive recorded readings with nothing in it.
    assert review.gaps == 2 and review.null_values == 1
    assert review.issues_for_review == 3
    assert s.headline == "3 item(s) for review"
    assert "does not by itself mean less electricity" in s.detail


def test_status_is_blocking_on_conflict(tmp_path):
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.3 "),
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.9 "),
        ],
    )
    p = q.period_summary(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    s = q.review_status(p)
    assert s.level == "blocking" and "withheld" in s.headline
    assert p.total_kwh is None and p.issues_for_review == 1


# -- 5. one duplicate policy across every consumer ---------------------------


def test_dedup_key_matches_the_warehouse_view(tmp_path):
    """' 0.5 ' and ' 0.50 ' are different source texts and must NOT collapse."""
    db = build(
        tmp_path,
        [
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.5 "),
            ("MAC000001", "Std", "2013-01-01 00:00:00.0000000", " 0.50 "),
        ],
    )
    quality = q.quality_summary(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert quality.duplicates_removed == 0, (
        "different raw text is not an exact duplicate"
    )
    assert quality.repeated_timestamps == 1
    assert quality.conflicting_keys == 0, "one numeric value: not a conflict"
    assert quality.equivalent_representations == 1


def test_bars_detail_and_total_agree_on_deduplication(span_with_issues):
    db, day = span_with_issues, date(2013, 1, 3)
    daily = q.daily_totals(db, "MAC000001", day, day).iloc[0]
    detail = q.half_hour_detail(db, "MAC000001", day).series
    real = detail[detail["value_category"] != "line_break"]
    p = q.period_summary(db, "MAC000001", day, day)
    assert daily["contributing_readings"] == 1
    assert len(real) == 2, "one finite reading (deduplicated) plus one Null point"
    assert p.total_kwh == Decimal("0.7")


def test_detail_chart_breaks_at_an_absent_half_hour_only(span_with_issues):
    detail = q.half_hour_detail(span_with_issues, "MAC000001", date(2013, 1, 2)).series
    kinds = list(detail["value_category"])
    assert kinds.count("line_break") == 1
    assert kinds.index("line_break") == 2, "the break sits after 00:30, before 02:00"
    clean = q.half_hour_detail(span_with_issues, "MAC000001", date(2013, 1, 1)).series
    assert "line_break" not in list(clean["value_category"])


def test_repeated_timestamps_are_not_described_as_the_same_instant():
    import inspect

    text = inspect.getsource(q.step_anomalies) + inspect.getsource(q)
    assert "same instant" not in text.replace('not called "the same instant"', "")


# -- friendly labels ----------------------------------------------------------


def test_dataset_label_distinguishes_demo_from_real(tmp_path):
    demo = build(
        tmp_path, [("DEMO0001", "Std", "2013-01-01 00:00:00.0000000", " 0.1 ")]
    )
    assert q.dataset_label(demo).startswith("Synthetic demo")


def test_band_share_labels_are_rounded_once_from_the_exact_values():
    """The chart labels and the table beneath it must not round the frame's four-place share a
    second time: 72.8497% is 72.8%, not 72.9%."""
    import pandas as pd

    from energy_reconciliation.explorer import charts
    from energy_reconciliation.tariff import analytics as ta

    bands = pd.DataFrame(
        [
            {
                "band_label": "Normal",
                "readings": 392515,
                "households": 27,
                "kwh_exact": "72325.8739944000",
                "kwh_display": 72325.874,
                "charge_gbp_exact": "8505.5227817414400000",
                "charge_gbp_display": 8505.52,
                "price_pence_per_kwh": 11.76,
                "consumption_share": 0.8462,
                "charge_share": 0.7285,
            },
            {
                "band_label": "Other",
                "readings": 63581,
                "households": 27,
                "kwh_exact": "13141.2590024000",
                "kwh_display": 13141.259,
                "charge_gbp_exact": "3169.9111399118100000",
                "charge_gbp_display": 3169.91,
                "price_pence_per_kwh": 0.0,
                "consumption_share": 0.1538,
                "charge_share": 0.2715,
            },
        ]
    )
    frame = charts.share_frame(bands)
    labels = dict(
        zip(
            zip(frame["band_label"], frame["series"], strict=True),
            frame["share_label"],
            strict=True,
        )
    )
    assert labels[("Normal", charts.CHARGE_SERIES)] == "72.8%"
    assert labels[("Normal", charts.CONSUMPTION_SERIES)] == "84.6%"
    assert charts.share_label(Decimal(1), Decimal(0)) == "n/a"
    assert ta.share_percent(
        Decimal("8505.5227817414400000"), Decimal("11675.4339216532500000")
    ) == Decimal("72.8")
