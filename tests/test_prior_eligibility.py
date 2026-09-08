"""I-08: eligibility from prior data only, and the accounting that must not lose cases.

FORE-001 proved that *predictions* cannot see the future. This experiment moves a second
decision — whether a household is evaluated at all — behind the same boundary, so the
tests here check **both**: that eligibility is future-independent, and that predictions
still are.

The contract these tests enforce was frozen before the experiment ran:
``docs/tickets/I-08-prior-data-eligibility.md``.
"""

from __future__ import annotations

import zipfile
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from conftest import HEADER, row

from energy_reconciliation.forecast.baselines import default_models
from energy_reconciliation.forecast.dataset import EXPECTED_INTERVALS, daily_records
from energy_reconciliation.forecast.prior_eligibility import (
    DECLINED,
    INSUFFICIENT_WINDOW,
    ISSUED,
    ORIGIN_UNUSABLE,
    SCOREABLE,
    TARGET_ABSENT,
    TARGET_NOT_USABLE,
    UNAVAILABLE,
    PriorConfig,
    origin_calendar,
    qualifies_at,
    run_prior_eligibility,
)
from energy_reconciliation.ingest.loader import load_member

MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"
START = date(2013, 1, 7)


def _day(household: str, day: date, intervals: int = EXPECTED_INTERVALS, value=" 0.5 "):
    return [
        row(
            household, "Std", f"{day} {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000", value
        )
        for i in range(intervals)
    ]


def _warehouse(tmp_path, rows, name="prior.zip"):
    archive = tmp_path / name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MEMBER, HEADER + b"".join(rows))
    database = tmp_path / f"{name}.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def _usable(days: int = 120, household: str = "H1", value=" 0.5 "):
    return [
        r
        for i in range(days)
        for r in _day(household, START + timedelta(days=i), value=value)
    ]


# ------------------------------------------------- eligibility is future-independent
def test_eligibility_ignores_every_date_after_the_origin():
    """The decisive test for this experiment: rewriting the future must not change who
    qualifies. FORE-001's run selection would have changed; this must not."""
    config = PriorConfig()
    origin = START + timedelta(days=40)
    usable = {START + timedelta(days=i): Decimal(1) for i in range(120)}
    before = qualifies_at(usable, origin, config)

    # delete and corrupt everything after the origin
    truncated = {d: v for d, v in usable.items() if d <= origin}
    assert qualifies_at(truncated, origin, config) == before
    extended = {
        **usable,
        **{origin + timedelta(days=i): Decimal(999) for i in range(1, 60)},
    }
    assert qualifies_at(extended, origin, config) == before


def test_eligibility_counts_only_the_window_ending_at_the_origin():
    """20 of the 28 dates ending at the origin, not 20 anywhere in the history."""
    config = PriorConfig()
    origin = START + timedelta(days=60)
    far_past = {START + timedelta(days=i): Decimal(1) for i in range(28)}
    far_past[origin] = Decimal(1)
    assert not qualifies_at(far_past, origin, config)
    in_window = {
        origin - timedelta(days=i): Decimal(1)
        for i in range(config.min_usable_in_window)
    }
    assert qualifies_at(in_window, origin, config)


def test_an_unusable_origin_day_disqualifies_however_full_the_window():
    config = PriorConfig()
    origin = START + timedelta(days=40)
    usable = {
        START + timedelta(days=i): Decimal(1)
        for i in range(120)
        if START + timedelta(days=i) != origin
    }
    assert not qualifies_at(usable, origin, config)


def test_the_origin_calendar_comes_from_the_warehouse_span_not_a_clean_run(tmp_path):
    """Two households with very different clean runs must share one origin calendar."""
    rows = _usable(120, "H1") + [
        r for i in range(40) for r in _day("H2", START + timedelta(days=i + 60))
    ]
    records = daily_records(_warehouse(tmp_path, rows))
    config = PriorConfig()
    origins = origin_calendar(records, config)
    assert origins == sorted(origins)
    assert min(origins) == START + timedelta(days=config.window_days - 1)
    gaps = {(b - a).days for a, b in pairwise(origins)}
    assert gaps <= {7}
    # the calendar does not depend on either household's own span
    only_h1 = {"H1": records["H1"]}
    assert origin_calendar(only_h1, config)[0] == origins[0]


# ----------------------------------------------------- predictions still see no future
def test_predictions_cannot_see_past_their_origin(tmp_path):
    """Every issued prediction's inputs come from a history capped at the origin."""
    database = _warehouse(tmp_path, _usable(120), name="future.zip")
    report = run_prior_eligibility(database)
    for case in report["_cases"]:
        if case.prediction_state == ISSUED:
            assert case.origin < case.target_date


def test_a_missing_lag_day_declines_and_is_never_zero_filled(tmp_path):
    """A hole seven days before a target must decline, not become 0 kWh."""
    days = _usable(120)
    hole = START + timedelta(days=50)
    rows = [r for r in days if f"{hole} " not in r.decode("ascii")]
    database = _warehouse(tmp_path, rows, name="hole.zip")
    report = run_prior_eligibility(database)
    affected = [
        c
        for c in report["_cases"]
        if c.model == "seasonal_naive_7"
        and c.target_date == hole + timedelta(days=7)
        and c.prediction_state == DECLINED
    ]
    assert affected, "the model must decline when its lag day is unusable"
    assert all(c.prediction_reason == "lag_day_not_usable" for c in affected)
    assert all(c.predicted is None for c in affected)
    # and the hole itself is an unavailable target, not a zero
    targets = [c for c in report["_cases"] if c.target_date == hole]
    assert targets and all(c.target_state == UNAVAILABLE for c in targets)
    assert all(c.actual is None for c in targets)


# ------------------------------------------------------------------- the accounting
def test_every_scheduled_case_is_classified_on_both_axes(tmp_path):
    database = _warehouse(tmp_path, _usable(120), name="axes.zip")
    report = run_prior_eligibility(database)
    cases = report["_cases"]
    per_model = report["universe"]["scheduled_cases_per_model"]
    for model in report["models"]:
        mine = [c for c in cases if c.model == model]
        assert len(mine) == per_model, "no scheduled case may disappear"
        assert all(c.prediction_state in {ISSUED, DECLINED} for c in mine)
        assert all(c.target_state in {SCOREABLE, UNAVAILABLE} for c in mine)
        assert all(
            (c.prediction_reason is not None) == (c.prediction_state == DECLINED)
            for c in mine
        )
        assert all(
            (c.target_reason is not None) == (c.target_state == UNAVAILABLE)
            for c in mine
        )


def test_coverage_denominators_are_the_scheduled_cases(tmp_path):
    database = _warehouse(tmp_path, _usable(120), name="cov.zip")
    report = run_prior_eligibility(database)
    scheduled = report["universe"]["scheduled_cases_per_model"]
    for cov in report["coverage"].values():
        assert cov["scheduled"] == scheduled
        assert cov["prediction_coverage"] == pytest.approx(
            cov["predictions_issued"] / scheduled, abs=1e-4
        )
        assert cov["scoring_coverage"] == pytest.approx(
            cov["scored"] / scheduled, abs=1e-4
        )
        assert cov["scored"] <= cov["predictions_issued"]
        assert cov["scored"] <= cov["targets_scoreable"]
        assert (
            sum(cov["declined_by_reason"].values())
            == scheduled - cov["predictions_issued"]
        )


def test_the_two_axes_are_independent_and_both_reported(tmp_path):
    """A case can be declined AND unscoreable; it must appear under both, not one."""
    rows = _usable(60) + [
        r for i in range(30) for r in _day("H1", START + timedelta(days=i + 90))
    ]
    database = _warehouse(tmp_path, rows, name="both.zip")
    report = run_prior_eligibility(database)
    both = [
        c
        for c in report["_cases"]
        if c.prediction_state == DECLINED and c.target_state == UNAVAILABLE
    ]
    assert both, "the gap must produce cases that are both declined and unscoreable"
    assert report["target_availability"]["declined_and_unavailable"] == len(
        [c for c in both if c.model == report["models"][0]]
    )


def test_absent_and_unusable_targets_are_distinguished(tmp_path):
    """A date the warehouse never recorded is not the same as one it recorded badly."""
    days = _usable(120)
    absent = START + timedelta(days=60)
    partial = START + timedelta(days=70)
    rows = [r for r in days if f"{absent} " not in r.decode("ascii")]
    rows = [r for r in rows if f"{partial} " not in r.decode("ascii")]
    rows += _day("H1", partial, intervals=40)
    report = run_prior_eligibility(_warehouse(tmp_path, rows, name="reasons.zip"))
    reasons = {
        c.target_date: c.target_reason
        for c in report["_cases"]
        if c.target_state == UNAVAILABLE
    }
    assert reasons.get(absent) == TARGET_ABSENT
    assert reasons.get(partial) == TARGET_NOT_USABLE


def test_declines_are_attributed_to_the_rule_that_caused_them(tmp_path):
    rows = [r for i in range(10) for r in _day("H1", START + timedelta(days=i))]
    rows += [r for i in range(60) for r in _day("H1", START + timedelta(days=i + 40))]
    report = run_prior_eligibility(_warehouse(tmp_path, rows, name="why.zip"))
    reasons = {
        c.prediction_reason for c in report["_cases"] if c.prediction_state == DECLINED
    }
    assert ORIGIN_UNUSABLE in reasons or INSUFFICIENT_WINDOW in reasons


# --------------------------------------------------------------------- comparison
def test_models_are_compared_on_common_scoreable_cases(tmp_path):
    database = _warehouse(tmp_path, _usable(150), name="common.zip")
    report = run_prior_eligibility(database)
    common = report["accuracy"]["common_per_model"]
    counts = {m["count"] for m in common.values()}
    assert len(counts) == 1, "the common frame must be one set of cases for every model"
    assert next(iter(counts)) == report["accuracy"]["common_scoreable_cases"]


def test_a_flat_series_is_predicted_exactly_by_every_model(tmp_path):
    """A known answer: constant consumption means zero error, whatever the eligibility."""
    database = _warehouse(tmp_path, _usable(150, value=" 0.25 "), name="flat.zip")
    report = run_prior_eligibility(database)
    for metric in report["accuracy"]["common_per_model"].values():
        assert Decimal(metric["mae_kwh_exact"]) == 0


def test_the_report_states_its_status_honestly(tmp_path):
    report = run_prior_eligibility(
        _warehouse(tmp_path, _usable(120), name="status.zip")
    )
    assert "as-of-source-date" in report["kind"]
    assert "NOT a fresh independent holdout" in report["kind"]
    assert (
        "not a reconstruction of historical production availability" in report["kind"]
    )
    assert report["contract"].startswith("docs/tickets/I-08")
    assert report["universe"]["origin_calendar"]["derived_from"].startswith(
        "warehouse date span"
    )


def test_models_and_settings_are_unchanged_from_fore_001():
    """I-08 must not quietly retune anything; it changes eligibility only."""
    from energy_reconciliation.forecast.baselines import WEEKDAY_MEAN_WEEKS, WeekdayMean

    names = [m.name for m in default_models()]
    assert names == ["seasonal_naive_7", "weekday_mean_4", "persistence_1"]
    assert WEEKDAY_MEAN_WEEKS == 4
    assert WeekdayMean().weeks == 4


# ------------------------------------------------- the shared/new split is one set
def test_shared_and_new_partition_the_cases_scored_by_at_least_one_model(tmp_path):
    """Shared + new must equal the cases scored by at least one model, which is a
    superset of the every-model frame; and each model's shared/new count must be the
    cases it scored there, never more than the set size. 200 usable days makes the
    household eligible for FORE-001 too, so the shared set is non-empty."""
    database = _warehouse(tmp_path, _usable(200), name="overlap.zip")
    report = run_prior_eligibility(database, PriorConfig())
    overlap = report["overlap_with_fore_001"]
    assert overlap["shared_cases"] > 0
    assert (
        overlap["shared_cases"] + overlap["new_to_i08"] == overlap["i08_scored_cases"]
    )
    assert (
        overlap["i08_cases_scored_by_every_model"]
        == report["accuracy"]["common_scoreable_cases"]
    )
    assert overlap["i08_cases_scored_by_every_model"] <= overlap["i08_scored_cases"]
    assert "at least one model" in overlap["i08_scored_cases_definition"]
    for model in report["models"]:
        assert (
            0 < overlap["scored_per_model_on_shared"][model] <= overlap["shared_cases"]
        )
        assert overlap["scored_per_model_on_new"][model] <= overlap["new_to_i08"]
    # the union is what the cases themselves say it is
    scored = {
        (c.household_id, c.origin, c.horizon) for c in report["_cases"] if c.scored
    }
    assert len(scored) == overlap["i08_scored_cases"]


def test_overlap_tables_name_their_sets():
    from energy_reconciliation.explorer import forecast_view as fc

    prior = {
        "models": ["seasonal_naive_7", "weekday_mean_4", "persistence_1"],
        "universe": {
            "households": 2,
            "origin_calendar": {
                "origins": 3,
                "first": "2013-02-03",
                "last": "2013-02-17",
            },
            "household_origins_qualifying": 5,
            "household_origins_scheduled": 6,
            "scheduled_cases_per_model": 42,
        },
        "accuracy": {"common_scoreable_cases": 30},
        "overlap_with_fore_001": {
            "fore_001_scored_cases": 20,
            "i08_scored_cases": 33,
            "i08_cases_scored_by_every_model": 30,
            "shared_cases": 10,
            "new_to_i08": 23,
            "in_fore_001_only": 10,
            "shared_pairs_compared": 30,
            "shared_absolute_error_mismatches": 0,
            "reproduces_fore_001_on_shared_cases": True,
            "scored_per_model_on_shared": {
                "seasonal_naive_7": 9,
                "weekday_mean_4": 10,
                "persistence_1": 10,
            },
            "scored_per_model_on_new": {
                "seasonal_naive_7": 20,
                "weekday_mean_4": 21,
                "persistence_1": 23,
            },
            "mae_on_shared": {
                "seasonal_naive_7": "1.0",
                "weekday_mean_4": "0.5",
                "persistence_1": "2.0",
            },
            "mae_on_new": {
                "seasonal_naive_7": "1.5",
                "weekday_mean_4": "1.0",
                "persistence_1": "2.5",
            },
        },
    }
    population = fc.prior_population_table(prior)
    values = dict(zip(population["Measure"], population["Value"], strict=True))
    assert values["Cases scored by at least one model"].startswith(
        "33 of the scheduled"
    )
    assert (
        "30 of these were scored by every model"
        in values["Cases scored by at least one model"]
    )
    assert values["— of which new to this experiment"] == "23 (10 + 23 = 33)"
    table = fc.prior_overlap_table(prior)
    by_model = table.set_index("Model")
    assert (
        by_model.loc["Same weekday, previous week", "Shared cases this model scored"]
        == "9"
    )
    assert by_model.loc["4-week weekday mean", "MAE (kWh), new"] == "1.0"
