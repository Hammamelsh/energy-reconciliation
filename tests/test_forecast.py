"""FORE-001: lag alignment, missing dates, and prevention of future-data leakage.

The model tests build a series whose values are a known arithmetic function of the date,
so the correct prediction can be computed in the test's own head rather than by running
the thing under test. If the lag is off by one day, or by one week, the arithmetic simply
does not come out.

The eligibility tests go through the real loader, so the rules are exercised against
actual stored rows rather than against a hand-made object.
"""

from __future__ import annotations

import zipfile
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from conftest import HEADER, row

from energy_reconciliation.forecast.baselines import (
    NO_LAG,
    NO_ORIGIN,
    NO_WEEKDAY_HISTORY,
    LastObservedDay,
    SeasonalNaiveWeek,
    WeekdayMean,
    default_models,
)
from energy_reconciliation.forecast.dataset import (
    EXPECTED_INTERVALS,
    HouseholdSeries,
    daily_records,
    eligible_series,
    longest_usable_run,
)
from energy_reconciliation.forecast.evaluate import (
    DEVELOPMENT,
    HOLDOUT,
    ExperimentConfig,
    evaluate_series,
    origins_for,
    run_experiment,
)
from energy_reconciliation.ingest.loader import load_member

START = date(2013, 1, 7)  # a Monday, so weekday arithmetic is easy to read
MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"


def linear_series(days: int = 200, household: str = "H1") -> HouseholdSeries:
    """value(d) = the number of days since START. Every lag is checkable by hand."""
    values = {START + timedelta(days=i): Decimal(i) for i in range(days)}
    return HouseholdSeries(household, START, START + timedelta(days=days - 1), values)


# ------------------------------------------------------------------ lag alignment
@pytest.mark.parametrize("horizon", range(1, 8))
def test_seasonal_naive_reads_exactly_seven_days_before_the_target(horizon):
    """Predicting O+h must return value(O+h-7) -- not value(O), not value(O+h-1)."""
    series = linear_series()
    origin = START + timedelta(days=100)
    target = origin + timedelta(days=horizon)
    prediction = SeasonalNaiveWeek().predict(series, origin, target)
    assert prediction.value == Decimal((target - timedelta(days=7) - START).days)
    assert prediction.inputs == (target - timedelta(days=7),)
    assert prediction.inputs[0] <= origin, (
        "the referenced day must not be in the future"
    )


@pytest.mark.parametrize("horizon", range(1, 8))
def test_weekday_mean_averages_the_four_preceding_same_weekdays(horizon):
    """On a linear series the mean of t-7, t-14, t-21, t-28 is value(t) - 17.5.

    (7 + 14 + 21 + 28) / 4 = 17.5, so the arithmetic pins both the lags and the count.
    """
    series = linear_series()
    origin = START + timedelta(days=100)
    target = origin + timedelta(days=horizon)
    prediction = WeekdayMean().predict(series, origin, target)
    expected = Decimal((target - START).days) - Decimal("17.5")
    assert prediction.value == expected
    assert len(prediction.inputs) == 4
    assert all(d.weekday() == target.weekday() for d in prediction.inputs)
    assert all(d <= origin for d in prediction.inputs)
    assert prediction.inputs == tuple(
        sorted(target - timedelta(days=7 * k) for k in (1, 2, 3, 4))
    )


def test_persistence_repeats_the_origin_day_across_the_horizon():
    series = linear_series()
    origin = START + timedelta(days=100)
    values = {
        h: LastObservedDay().predict(series, origin, origin + timedelta(days=h)).value
        for h in range(1, 8)
    }
    assert set(values.values()) == {Decimal(100)}


def test_a_model_refuses_a_target_that_is_not_after_the_origin():
    series = linear_series()
    origin = START + timedelta(days=10)
    for model in default_models():
        with pytest.raises(ValueError, match="not after the forecast origin"):
            model.predict(series, origin, origin)


# ------------------------------------------------------------------ missing dates
def test_a_missing_lag_day_declines_instead_of_substituting_a_zero():
    """The one thing that must never happen: an absent day becoming 0 kWh."""
    series = linear_series()
    origin = START + timedelta(days=100)
    target = origin + timedelta(days=3)
    holed = HouseholdSeries(
        series.household_id,
        series.run_start,
        series.run_end,
        {d: v for d, v in series.values.items() if d != target - timedelta(days=7)},
    )
    prediction = SeasonalNaiveWeek().predict(holed, origin, target)
    assert prediction.value is None
    assert prediction.reason == NO_LAG
    assert prediction.value != Decimal(0)


def test_insufficient_same_weekday_history_declines_rather_than_averaging_fewer():
    """Three weeks of history must not silently become a three-week mean."""
    series = linear_series(days=200)
    origin = series.run_start + timedelta(days=20)  # fewer than 4 weekdays behind
    target = origin + timedelta(days=1)
    prediction = WeekdayMean().predict(series, origin, target)
    assert prediction.value is None
    assert prediction.reason == NO_WEEKDAY_HISTORY


def test_a_missing_origin_day_declines_for_persistence():
    series = linear_series()
    origin = START + timedelta(days=100)
    holed = HouseholdSeries(
        series.household_id,
        series.run_start,
        series.run_end,
        {d: v for d, v in series.values.items() if d != origin},
    )
    prediction = LastObservedDay().predict(holed, origin, origin + timedelta(days=1))
    assert prediction.value is None
    assert prediction.reason == NO_ORIGIN


def test_a_missing_target_is_excluded_and_never_scored():
    series = linear_series(days=200)
    missing = START + timedelta(days=120)
    holed = HouseholdSeries(
        series.household_id,
        series.run_start,
        series.run_end,
        {d: v for d, v in series.values.items() if d != missing},
    )
    rows = evaluate_series(holed, default_models(), ExperimentConfig())
    affected = [r for r in rows if r.target_date == missing]
    assert affected, "the missing date must still appear, as an exclusion"
    assert all(not r.scored for r in affected)
    assert {r.excluded_reason for r in affected} == {"target_day_not_usable"}
    assert all(r.predicted is None and r.actual is None for r in affected)


# ------------------------------------------------------------ no future information
@pytest.mark.parametrize("horizon", range(1, 8))
def test_changing_the_future_cannot_change_a_prediction(horizon):
    """The decisive leakage test: rewrite every value after the origin, predict again.

    If any model consulted a date later than its origin, at least one prediction would
    move. None may.
    """
    series = linear_series()
    origin = START + timedelta(days=100)
    target = origin + timedelta(days=horizon)
    before = {m.name: m.predict(series, origin, target).value for m in default_models()}

    tampered = HouseholdSeries(
        series.household_id,
        series.run_start,
        series.run_end,
        {
            d: (v + Decimal(10_000) if d > origin else v)
            for d, v in series.values.items()
        },
    )
    after = {
        m.name: m.predict(tampered, origin, target).value for m in default_models()
    }
    assert before == after


def test_no_model_input_is_ever_after_its_origin():
    series = linear_series()
    for offset in (40, 80, 150):
        origin = START + timedelta(days=offset)
        for horizon in range(1, 8):
            for model in default_models():
                prediction = model.predict(
                    series, origin, origin + timedelta(days=horizon)
                )
                assert all(d <= origin for d in prediction.inputs)


# --------------------------------------------------------------- splits and origins
def test_holdout_origins_forecast_only_into_the_holdout_window():
    series = linear_series(days=250)
    config = ExperimentConfig()
    development, holdout = origins_for(series, config)
    holdout_start = series.run_end - timedelta(days=config.holdout_days - 1)

    assert development and holdout
    for origin in development:
        assert origin + timedelta(days=config.horizon) < holdout_start, (
            "a development origin must not forecast into the holdout"
        )
    for origin in holdout:
        assert origin + timedelta(days=1) >= holdout_start
        assert origin + timedelta(days=config.horizon) <= series.run_end
    assert max(development) < min(holdout)


def test_the_first_origin_leaves_room_for_the_four_week_warm_up():
    series = linear_series(days=250)
    config = ExperimentConfig()
    development, _ = origins_for(series, config)
    first = min(development)
    assert (first - series.run_start).days >= config.warmup_days - 1
    # and at that first origin the four-week model can in fact predict
    prediction = WeekdayMean().predict(series, first, first + timedelta(days=1))
    assert prediction.made


def test_origins_step_weekly_and_are_chronological():
    series = linear_series(days=250)
    development, holdout = origins_for(series, ExperimentConfig())
    for origins in (development, holdout):
        assert origins == sorted(origins)
        gaps = {(b - a).days for a, b in pairwise(origins)}
        assert gaps <= {7}


# ------------------------------------------------------- eligibility, via the loader
def _warehouse(tmp_path, rows, name="fc.zip"):
    archive = tmp_path / name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MEMBER, HEADER + b"".join(rows))
    database = tmp_path / f"{name}.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def _day(household: str, day: date, intervals: int = EXPECTED_INTERVALS, value=" 0.5 "):
    return [
        row(
            household,
            "Std",
            f"{day} {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
            value,
        )
        for i in range(intervals)
    ]


def test_a_partially_observed_date_is_not_usable(tmp_path):
    """47 of 48 labels is not a whole day, and is never treated as one."""
    rows = _day("H1", date(2013, 1, 1)) + _day("H1", date(2013, 1, 2), intervals=47)
    records = daily_records(_warehouse(tmp_path, rows))["H1"]
    by_date = {r.source_date: r for r in records}
    assert by_date[date(2013, 1, 1)].usable
    assert not by_date[date(2013, 1, 2)].usable
    assert by_date[date(2013, 1, 2)].unusable_reason == "partial_grid_47_of_48"


def test_a_recorded_missing_value_makes_the_date_unusable(tmp_path):
    day = date(2013, 1, 2)
    rows = (
        _day("H1", date(2013, 1, 1))
        + _day("H1", day)[:-1]
        + [row("H1", "Std", f"{day} 23:30:00.0000000", "Null")]
    )
    records = {
        r.source_date: r for r in daily_records(_warehouse(tmp_path, rows))["H1"]
    }
    assert not records[day].usable
    assert records[day].unusable_reason == "missing_value_recorded"


def test_a_disagreeing_date_is_unusable(tmp_path):
    day = date(2013, 1, 2)
    rows = (
        _day("H1", date(2013, 1, 1))
        + _day("H1", day)
        + [row("H1", "Std", f"{day} 00:00:00.0000000", " 9.9 ")]
    )
    records = {
        r.source_date: r for r in daily_records(_warehouse(tmp_path, rows))["H1"]
    }
    assert not records[day].usable
    assert records[day].unusable_reason == "conflicting_readings"


def test_the_longest_run_stops_at_a_gap(tmp_path):
    """Days 1-3 and 5-10: the run is 5-10, not "9 usable days"."""
    days = [date(2013, 1, d) for d in (1, 2, 3, 5, 6, 7, 8, 9, 10)]
    rows = [r for d in days for r in _day("H1", d)]
    records = daily_records(_warehouse(tmp_path, rows))["H1"]
    assert longest_usable_run(records) == (date(2013, 1, 5), date(2013, 1, 10))


def test_a_household_without_a_long_enough_run_is_not_eligible(tmp_path):
    rows = [
        r for i in range(10) for r in _day("H1", date(2013, 1, 1) + timedelta(days=i))
    ]
    assert eligible_series(_warehouse(tmp_path, rows), min_run_days=168) == []


def test_the_daily_total_matches_the_policy_total(tmp_path):
    """48 x 0.5 = 24.0 kWh, and a duplicated row does not double it."""
    day = date(2013, 1, 1)
    rows = _day("H1", day) + [row("H1", "Std", f"{day} 00:00:00.0000000", " 0.5 ")]
    records = {
        r.source_date: r for r in daily_records(_warehouse(tmp_path, rows))["H1"]
    }
    assert records[day].kwh == Decimal("24.0")
    assert records[day].usable


# ----------------------------------------------------------- the experiment shape
def test_the_experiment_reports_its_target_and_identity(tmp_path):
    rows = [
        r
        for i in range(200)
        for r in _day("H1", START + timedelta(days=i), value=" 0.25 ")
    ]
    report = run_experiment(_warehouse(tmp_path, rows), ExperimentConfig())
    assert report["kind"] == "historical backtest, not a live forecast"
    assert "not a local calendar day" in report["target"]
    assert report["identity"]["dataset_sha256"]
    assert report["identity"]["forecast_code_sha256"]
    assert report["identity"]["config_sha256"]
    assert set(report["evaluation"]) == {DEVELOPMENT, HOLDOUT}
    # a perfectly flat series is predicted exactly by every model
    for split in (DEVELOPMENT, HOLDOUT):
        for metric in report["evaluation"][split]["by_model"].values():
            assert Decimal(metric["mae_kwh_exact"]) == 0


# ------------------------------------------------ evaluation-contract invariants
def _flat_warehouse(tmp_path, days=250):
    rows = [
        r
        for i in range(days)
        for r in _day("H1", START + timedelta(days=i), value=" 0.25 ")
    ]
    return _warehouse(tmp_path, rows, name="contract.zip")


def test_each_target_is_predicted_exactly_once_per_model_per_split(tmp_path):
    """Origins step by the horizon, so no target day is double-counted in MAE."""
    report = run_experiment(_flat_warehouse(tmp_path), ExperimentConfig())
    for split in (DEVELOPMENT, HOLDOUT):
        section = report["evaluation"][split]
        assert section["targets_predicted_more_than_once_per_model"] == 0
        assert section["unique_household_targets"] * 3 == section["scored_predictions"]


def test_the_report_states_selection_hindsight_and_pooled_weighting(tmp_path):
    report = run_experiment(_flat_warehouse(tmp_path), ExperimentConfig())
    assert "retrospective" in report["selection"]["kind"]
    assert "including the holdout window" in report["selection"]["rule"]
    assert report["evaluation"][HOLDOUT]["weighting"].startswith("pooled")
    assert (
        "predictions_with_an_input_inside_the_holdout_window"
        in report["evaluation"][HOLDOUT]
    )
    assert (
        "predictions_with_an_input_inside_the_holdout_window"
        not in report["evaluation"][DEVELOPMENT]
    )


def test_rolling_holdout_uses_only_earlier_holdout_days_never_later(tmp_path):
    """Later holdout origins may see earlier holdout days; never a date after the origin."""
    series = linear_series(days=250)
    config = ExperimentConfig()
    _, holdout = origins_for(series, config)
    holdout_start = series.run_end - timedelta(days=config.holdout_days - 1)
    rows = [
        r
        for r in evaluate_series(series, default_models(), config)
        if r.split == HOLDOUT
    ]
    saw_inside = False
    for r in rows:
        assert all(d <= r.origin for d in r.inputs)
        saw_inside |= any(d >= holdout_start for d in r.inputs)
    assert saw_inside, (
        "with four weekly origins the rolling holdout must reuse holdout days"
    )
    assert holdout[0] == holdout_start - timedelta(days=1)


def test_the_sweep_note_does_not_claim_a_fresh_holdout(tmp_path):
    from energy_reconciliation.forecast.evaluate import weekday_weeks_sweep

    sweep = weekday_weeks_sweep(_flat_warehouse(tmp_path), ExperimentConfig())
    assert "restatement" in sweep["note"]
    assert "AFTER" in sweep["note"]
    assert sweep["compared_on_common_triples"] > 0


# ------------------------------------------------------------ presentation contracts
def test_observed_chart_pins_one_tick_per_target_date(tmp_path):
    """A temporal axis left to the renderer halves the interval and repeats every label."""
    from energy_reconciliation.explorer import charts
    from energy_reconciliation.explorer import forecast_view as fc

    series = linear_series(days=250)
    origin = START + timedelta(days=100)
    rows = fc.observed_vs_predicted(
        series, origin, default_models(), ExperimentConfig()
    )
    spec = charts.observed_vs_predicted_chart(fc.long_frame(rows)).to_dict()
    axis = spec["layer"][0]["encoding"]["x"]["axis"]
    assert axis["tickCount"] == {"interval": "day", "step": 1}
    assert spec["layer"][0]["encoding"]["x"]["type"] == "temporal"


def test_model_only_charts_do_not_list_observed_in_their_legend(tmp_path):
    from energy_reconciliation.explorer import charts
    from energy_reconciliation.explorer import forecast_view as fc

    report = run_experiment(
        _warehouse(
            tmp_path,
            [r for i in range(250) for r in _day("H1", START + timedelta(days=i))],
            name="legend.zip",
        ),
        ExperimentConfig(),
    )
    section = report["evaluation"][HOLDOUT]
    horizon = charts.horizon_error_chart(fc.horizon_frame(section)).to_dict()
    domain = horizon["encoding"]["color"]["scale"]["domain"]
    assert charts.MODEL_LABELS["observed"] not in domain
    assert set(domain) == set(charts.MODEL_ONLY)
    mae = charts.model_error_chart(fc.model_frame(section), "MAE").to_dict()
    assert (
        charts.MODEL_LABELS["observed"]
        not in mae["layer"][0]["encoding"]["color"]["scale"]["domain"]
    )


def test_user_facing_names_replace_identifiers_and_identifiers_are_retained(tmp_path):
    from energy_reconciliation.explorer import charts
    from energy_reconciliation.explorer import forecast_view as fc

    series = linear_series(days=250)
    origin = START + timedelta(days=100)
    rows = fc.observed_vs_predicted(
        series, origin, default_models(), ExperimentConfig()
    )
    table = fc.origin_table(rows)
    assert "4-week weekday mean" in table.columns
    assert "weekday_mean_4" not in table.columns
    frame = fc.long_frame(rows)
    assert set(frame["series"]) <= set(charts.FORECAST_COLOURS)
    section = {
        "by_model": {
            "weekday_mean_4": {"count": 1, "mae_kwh": "1.0", "median_ae_kwh": "1.0"}
        }
    }
    model_table = fc.model_table(section)
    assert model_table.loc[0, "Model"] == "4-week weekday mean"
    assert model_table.loc[0, "Identifier"] == "weekday_mean_4"


def test_series_are_distinguished_beyond_colour(tmp_path):
    from energy_reconciliation.explorer import charts
    from energy_reconciliation.explorer import forecast_view as fc

    series = linear_series(days=250)
    rows = fc.observed_vs_predicted(
        series, START + timedelta(days=100), default_models(), ExperimentConfig()
    )
    spec = charts.observed_vs_predicted_chart(fc.long_frame(rows)).to_dict()
    assert "strokeDash" in spec["layer"][0]["encoding"]
    assert "shape" in spec["layer"][1]["encoding"]


def test_cohort_members_are_described_in_numeric_order_with_spanning_households():
    from energy_reconciliation.explorer import forecast_view as fc

    text = fc.describe_members(
        {
            "LCL-June2015v2_135.csv": 5,
            "LCL-June2015v2_4.csv": 26,
            "LCL-June2015v2_4.csv+LCL-June2015v2_5.csv": 1,
            "LCL-June2015v2_5.csv": 8,
        }
    )
    assert text == (
        "26 in member 4 only, 1 spanning members 4 and 5, 8 in member 5 only, "
        "5 in member 135 only"
    )


def test_mae_chart_does_not_truncate_model_names(tmp_path):
    """The renderer's default 180 px label limit cut every name to "4-week weekda...".

    ``labelLimit`` 0 means no limit, so the margin grows to the longest name instead.
    """
    from energy_reconciliation.explorer import charts
    from energy_reconciliation.explorer import forecast_view as fc

    report = run_experiment(
        _warehouse(
            tmp_path,
            [r for i in range(250) for r in _day("H1", START + timedelta(days=i))],
            name="labels.zip",
        ),
        ExperimentConfig(),
    )
    spec = charts.model_error_chart(
        fc.model_frame(report["evaluation"][HOLDOUT]), "MAE"
    ).to_dict()
    for layer in spec["layer"]:
        assert layer["encoding"]["y"]["axis"]["labelLimit"] == 0


def test_worst_days_show_each_models_own_inputs():
    """The 4-week mean is explained by the four same-weekday values it averaged, the
    one-week naive by the previous week, persistence by the origin day. The values shown
    must be the ones the model actually read (recorded on the prediction), and for the
    4-week mean their mean must be the prediction itself."""
    from energy_reconciliation.explorer import forecast_view as fc

    values = {START + timedelta(days=i): Decimal(i) for i in range(200)}
    spike = START + timedelta(days=150)
    values[spike] = Decimal(1000)  # one unusual day, so the errors are not all alike
    series = HouseholdSeries("H1", START, START + timedelta(days=199), values)
    table = fc.worst_days(series, default_models(), ExperimentConfig())
    assert "Same weekday, 4 → 1 weeks earlier" in table.columns
    assert "Origin day" in table.columns
    assert "Dates the model read" in table.columns

    mean_rows = table[table["Model"] == "4-week weekday mean"]
    assert not mean_rows.empty
    for _, r in mean_rows.iterrows():
        four = [
            Decimal(v.replace(",", ""))
            for v in r["Same weekday, 4 → 1 weeks earlier"].split(" · ")
        ]
        assert len(four) == 4
        assert sum(four) / 4 == Decimal(r["Predicted kWh"].replace(",", ""))
        assert len(r["Dates the model read"].split(", ")) == 4
    naive_rows = table[table["Model"] == "Same weekday, previous week"]
    for _, r in naive_rows.iterrows():
        assert r["Same weekday, 1 week earlier"] == r["Predicted kWh"]
    persist_rows = table[table["Model"] == "Origin day repeated (reference)"]
    for _, r in persist_rows.iterrows():
        assert r["Origin day"].endswith(f"= {r['Predicted kWh']}")
