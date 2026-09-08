"""Chronological rolling evaluation with an untouched holdout.

How a forecast origin works
---------------------------

At origin ``O`` the models may use usable daily totals dated ``<= O`` and nothing else.
They predict ``O+1 .. O+horizon``. Origins step forward weekly, so every origin is a
fresh, later vantage point and no evaluated target is ever used to produce its own
prediction. ``tests/test_forecast.py`` proves the boundary holds by mutating the series
*after* an origin and asserting the predictions do not move.

Splits
------

Per household, over its one contiguous usable run:

- ``warm-up`` -- the first 28 days. No origin sits here, because the four-week weekday
  model needs four same-weekday dates behind it.
- ``development`` -- origins used for building and reading results.
- ``holdout`` -- the final 28 days. Its origins are evaluated **once**, at the end.
  Nothing was tuned on them; there is in fact nothing to tune, since both baselines and
  the reference are parameter-free once the four-week window is fixed in advance.

**The holdout is rolling, and that is a specification, not an accident.** Its four origins
step weekly through the window, so an origin inside the holdout may use holdout dates
that are already in its past as model inputs -- exactly as an operator on that day would.
Measured on the recorded run, 2,520 of 3,360 holdout predictions draw at least one input
from inside the window. What is forbidden is a target's own date, or any date after the
origin, and the leakage test proves that boundary holds. What is *also* not done is any
model or parameter choice informed by holdout scores.

**Run selection uses hindsight, and this is a retrospective benchmark.** A household's
longest contiguous usable run is found over its whole recorded history, holdout included,
so a household is in the cohort partly *because* its data stayed clean through the end.
That is not numerical leakage -- no model sees a value after its origin -- but it is a
selection an operator could not have made on the origin date. The result is a clean-run
benchmark of the models, not an estimate of operational accuracy over all households.

Metrics
-------

**MAE in kWh**, by model, by horizon and by household, with evaluation counts and the
reasons for every excluded (household, origin, horizon).

MAPE is deliberately absent. A daily total can be legitimately zero or near zero -- the
loaded data contains 45,538 zero half-hourly readings in one member alone -- and a
percentage error explodes there, so MAPE would rank models by how they behave on the
smallest days rather than on the ones that matter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Final

from ..tariff import identity
from .baselines import Model, WeekdayMean, default_models
from .dataset import (
    EXPECTED_INTERVALS,
    MIN_RUN_DAYS,
    HouseholdSeries,
    eligible_series,
    feasibility,
)

DEVELOPMENT: Final[str] = "development"
HOLDOUT: Final[str] = "holdout"

KWH_DP: Final[Decimal] = Decimal("0.001")


def round_kwh(value: Decimal) -> Decimal:
    return value.quantize(KWH_DP, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Everything that decides what is evaluated. Fixed before any result is read."""

    horizon: int = 7
    warmup_days: int = 28
    holdout_days: int = 28
    origin_step_days: int = 7
    min_run_days: int = MIN_RUN_DAYS
    household_limit: int | None = 40

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class Row:
    household_id: str
    model: str
    split: str
    origin: date
    horizon: int
    target_date: date
    actual: Decimal | None
    predicted: Decimal | None
    excluded_reason: str | None
    inputs: tuple[date, ...] = ()

    @property
    def scored(self) -> bool:
        return self.actual is not None and self.predicted is not None

    @property
    def abs_error(self) -> Decimal | None:
        return abs(self.actual - self.predicted) if self.scored else None


@dataclass
class Metric:
    count: int = 0
    total_abs_error: Decimal = Decimal(0)
    errors: list[Decimal] = field(default_factory=list)

    def add(self, error: Decimal) -> None:
        self.count += 1
        self.total_abs_error += error
        self.errors.append(error)

    @property
    def mae(self) -> Decimal | None:
        return self.total_abs_error / Decimal(self.count) if self.count else None

    @property
    def median_ae(self) -> Decimal | None:
        if not self.errors:
            return None
        ordered = sorted(self.errors)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


def origins_for(
    series: HouseholdSeries, config: ExperimentConfig
) -> tuple[list[date], list[date]]:
    """Development and holdout origins for one household, in chronological order."""
    holdout_start = series.run_end - timedelta(days=config.holdout_days - 1)
    development_end = holdout_start - timedelta(days=1)

    development: list[date] = []
    origin = series.run_start + timedelta(days=config.warmup_days - 1)
    while origin + timedelta(days=config.horizon) <= development_end:
        development.append(origin)
        origin += timedelta(days=config.origin_step_days)

    holdout: list[date] = []
    origin = holdout_start - timedelta(days=1)
    while origin + timedelta(days=config.horizon) <= series.run_end:
        holdout.append(origin)
        origin += timedelta(days=config.origin_step_days)
    return development, holdout


def evaluate_series(
    series: HouseholdSeries, models: tuple[Model, ...], config: ExperimentConfig
) -> list[Row]:
    """Every (origin, horizon, model) triple for one household, scored or excluded."""
    rows: list[Row] = []
    development, holdout = origins_for(series, config)
    for split, origins in ((DEVELOPMENT, development), (HOLDOUT, holdout)):
        for origin in origins:
            for horizon in range(1, config.horizon + 1):
                target = origin + timedelta(days=horizon)
                actual = series.at(target)
                for model in models:
                    if actual is None:
                        rows.append(
                            Row(
                                series.household_id,
                                model.name,
                                split,
                                origin,
                                horizon,
                                target,
                                None,
                                None,
                                "target_day_not_usable",
                            )
                        )
                        continue
                    prediction = model.predict(series, origin, target)
                    rows.append(
                        Row(
                            series.household_id,
                            model.name,
                            split,
                            origin,
                            horizon,
                            target,
                            actual,
                            prediction.value,
                            prediction.reason,
                            prediction.inputs,
                        )
                    )
    return rows


def _repeats(scored: list[Row]) -> int:
    """How many (model, household, target) keys were scored more than once. Zero by
    construction when origins step by exactly the horizon, and reported so a change to
    either would show up as repeated targets rather than as silently double-weighted
    days."""
    seen: dict[tuple[str, str, date], int] = {}
    for r in scored:
        k = (r.model, r.household_id, r.target_date)
        seen[k] = seen.get(k, 0) + 1
    return sum(1 for v in seen.values() if v > 1)


def _cohort_composition(database: Path, households: list[str]) -> dict[str, Any]:
    """Who is in the cohort, by tariff group and source member -- measured, so a reader
    can see how far 'the first N by id' is from a representative pick."""
    from ..ingest.warehouse import connect

    con = connect(database, read_only=True)
    try:
        rows = con.execute(
            "SELECT household_id, STRING_AGG(DISTINCT tariff_group, '|'), "
            "STRING_AGG(DISTINCT member_name, '|') FROM readings "
            "WHERE household_id IN (SELECT UNNEST(?)) GROUP BY 1",
            [households],
        ).fetchall()
        last = con.execute(
            "SELECT MAX(CAST(observed_at_naive AS DATE)) FROM readings"
        ).fetchone()[0]
    finally:
        con.close()
    per = {
        h: {
            "tariff_group": g,
            "members": sorted(m.split("/")[-1] for m in ms.split("|")),
        }
        for h, g, ms in rows
    }
    groups: dict[str, int] = {}
    members: dict[str, int] = {}
    for info in per.values():
        groups[info["tariff_group"]] = groups.get(info["tariff_group"], 0) + 1
        key = "+".join(info["members"])
        members[key] = members.get(key, 0) + 1
    return {
        "per_household": per,
        "tariff_groups": groups,
        "members": members,
        "_warehouse_last_date": last,
    }


def _summarise(rows: list[Row], key) -> dict[Any, dict[str, Any]]:
    metrics: dict[Any, Metric] = {}
    for row in rows:
        if row.scored:
            metrics.setdefault(key(row), Metric()).add(row.abs_error)
    return {
        k: {
            "count": m.count,
            "mae_kwh": str(round_kwh(m.mae)),
            "mae_kwh_exact": str(m.mae),
            "median_ae_kwh": str(round_kwh(m.median_ae)),
        }
        for k, m in sorted(metrics.items(), key=lambda kv: str(kv[0]))
    }


def run_experiment(
    database: Path,
    config: ExperimentConfig | None = None,
    models: tuple[Model, ...] | None = None,
) -> dict[str, Any]:
    """Run the whole backtest and return a self-describing result."""
    config = config or ExperimentConfig()
    models = models or default_models()
    series = eligible_series(database, config.min_run_days, config.household_limit)
    rows: list[Row] = []
    for one in series:
        rows.extend(evaluate_series(one, models, config))

    by_split: dict[str, list[Row]] = {DEVELOPMENT: [], HOLDOUT: []}
    for row in rows:
        by_split[row.split].append(row)

    exclusions: dict[str, dict[str, int]] = {}
    for row in rows:
        if row.excluded_reason:
            exclusions.setdefault(row.split, {})
            bucket = exclusions[row.split]
            label = f"{row.model}:{row.excluded_reason}"
            bucket[label] = bucket.get(label, 0) + 1

    cohort_ids = [s.household_id for s in series]
    composition = _cohort_composition(database, cohort_ids)
    last_date = composition.pop("_warehouse_last_date")

    def split_counts(split: str) -> dict[str, Any]:
        scored = [r for r in by_split[split] if r.scored]
        holdout_start = {
            s.household_id: s.run_end - timedelta(days=config.holdout_days - 1)
            for s in series
        }
        inside = sum(
            1
            for r in scored
            if split == HOLDOUT
            and any(d >= holdout_start[r.household_id] for d in r.inputs)
        )
        return {
            "households": len({r.household_id for r in scored}),
            "unique_household_targets": len(
                {(r.household_id, r.target_date) for r in scored}
            ),
            "unique_target_dates": len({r.target_date for r in scored}),
            "origins": len({(r.household_id, r.origin) for r in scored}),
            "weighting": (
                "pooled: every scored prediction has equal weight, so a household "
                "with more origins carries more weight"
            ),
            "targets_predicted_more_than_once_per_model": _repeats(scored),
            **(
                {"predictions_with_an_input_inside_the_holdout_window": inside}
                if split == HOLDOUT
                else {}
            ),
        }

    dataset_digest = hashlib.sha256()
    for one in series:
        dataset_digest.update(
            f"{one.household_id}|{one.run_start}|{one.run_end}|{len(one.values)}".encode()
        )
        for day in sorted(one.values):
            dataset_digest.update(f"{day}={one.values[day]}".encode())

    forecast_code = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        forecast_code.update(path.name.encode())
        forecast_code.update(path.read_bytes())

    return {
        "generated_at_utc": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
        "database": str(database),
        "kind": "historical backtest, not a live forecast",
        "target": (
            "the sum of a household's recorded half-hourly consumption over one source "
            "date, in kWh. A source date groups timestamp labels as written: it is not a "
            "local calendar day, not a settlement day, and 48 observed labels are not "
            "proof the meter covered the whole day."
        ),
        "feasibility": feasibility(database),
        "config": asdict(config),
        "models": [{"name": m.name, "description": m.description} for m in models],
        "identity": {
            "dataset_sha256": dataset_digest.hexdigest(),
            "forecast_code_sha256": forecast_code.hexdigest(),
            "config_sha256": config.digest,
            "ingestion_pipeline_fingerprint": identity.calculation_digest(),
            "runtime": identity.runtime_identity(),
        },
        "selection": {
            "rule": (
                "longest contiguous usable run >= min_run_days, computed over the "
                "household's WHOLE recorded history including the holdout window, then "
                "the first household_limit households by id"
            ),
            "kind": "retrospective clean-run benchmark, not an operational evaluation",
            "eligible_households": len(eligible_series(database, config.min_run_days)),
            "selected_households": len(series),
            "cohort_tariff_groups": composition["tariff_groups"],
            "cohort_members": composition["members"],
            "runs_ending_at_warehouse_end": sum(
                1 for s in series if s.run_end >= last_date - timedelta(days=1)
            ),
            "warehouse_last_date": str(last_date),
        },
        "households": [
            {
                "household_id": s.household_id,
                "tariff_group": composition["per_household"][s.household_id][
                    "tariff_group"
                ],
                "members": composition["per_household"][s.household_id]["members"],
                "run_start": str(s.run_start),
                "run_end": str(s.run_end),
                "usable_days": len(s.values),
                "development_origins": len(origins_for(s, config)[0]),
                "holdout_origins": len(origins_for(s, config)[1]),
            }
            for s in series
        ],
        "evaluation": {
            split: {
                **split_counts(split),
                "scored_predictions": sum(1 for r in by_split[split] if r.scored),
                "excluded_predictions": sum(1 for r in by_split[split] if not r.scored),
                "by_model": _summarise(by_split[split], lambda r: r.model),
                "by_model_horizon": _summarise(
                    by_split[split], lambda r: f"{r.model}|h{r.horizon}"
                ),
                "by_model_household": _summarise(
                    by_split[split], lambda r: f"{r.model}|{r.household_id}"
                ),
                "exclusions": exclusions.get(split, {}),
            }
            for split in (DEVELOPMENT, HOLDOUT)
        },
        "expected_intervals": EXPECTED_INTERVALS,
        "weeks_sweep": weekday_weeks_sweep(database, config),
    }


def weekday_weeks_sweep(
    database: Path,
    config: ExperimentConfig | None = None,
    candidates: tuple[int, ...] = (1, 2, 4, 8),
) -> dict[str, Any]:
    """Does averaging more same-weekday history help? Answered on **development only**.

    The two required baselines differ mainly in how much same-weekday history they
    average -- one week versus four -- and four won on development. That is a concrete
    question the data can answer without a new model class or a new dependency: sweep
    the number of weeks, pick the best on development, and then spend the holdout
    **once** on that single choice.

    ``k = 1`` is arithmetically identical to ``seasonal_naive_7``; it is included so the
    sweep contains the baseline it is being compared against.
    """
    config = config or ExperimentConfig()
    series = eligible_series(database, config.min_run_days, config.household_limit)
    models = tuple(
        WeekdayMean(weeks=k, name=f"weekday_mean_{k}", description=f"{k}-week mean")
        for k in candidates
    )
    rows: list[Row] = []
    for one in series:
        rows.extend(evaluate_series(one, models, config))
    development = [r for r in rows if r.split == DEVELOPMENT]
    # Candidates needing more history decline more often at early origins, so scoring
    # each on whatever it managed would compare them over different sets of days. The
    # comparison is restricted to the triples EVERY candidate predicted.
    triples: dict[tuple[str, date, int], int] = {}
    for r in development:
        if r.scored:
            key = (r.household_id, r.origin, r.horizon)
            triples[key] = triples.get(key, 0) + 1
    common = {k for k, n in triples.items() if n == len(models)}
    comparable = [
        r
        for r in development
        if r.scored and (r.household_id, r.origin, r.horizon) in common
    ]
    by_model = _summarise(comparable, lambda r: r.model)
    best = min(by_model, key=lambda k: Decimal(by_model[k]["mae_kwh_exact"]))
    best_weeks = int(best.rsplit("_", 1)[1])
    holdout = [r for r in rows if r.split == HOLDOUT and r.model == best]
    holdout_metric = _summarise(holdout, lambda r: r.model)
    return {
        "question": "does averaging more same-weekday history reduce error?",
        "candidates_weeks": list(candidates),
        "selected_on": DEVELOPMENT,
        "development_mae_by_weeks": by_model,
        "compared_on_common_triples": len(common),
        "declined_by_some_candidate": len(triples) - len(common),
        "selected_weeks": best_weeks,
        "holdout_of_selected_only": holdout_metric,
        "note": (
            "Selection used development only, and no candidate other than the "
            "selected one was scored on the holdout. However, this sweep was designed "
            "AFTER the main comparison's holdout results had been read, and the "
            "selected candidate (4 weeks) is the main comparison's own model, whose "
            "holdout figure was therefore already known. Treat the holdout line here "
            "as a restatement of that figure, not as a fresh independent test. The "
            "comparison between candidates also holds only on the common frame: cases "
            "the longest-history candidate could predict, which drops the earliest "
            "origins of every household."
        ),
        "frame_note": (
            "Candidates are compared on the cases every candidate predicted. The "
            "4-week figure here is therefore over a later, smaller frame than the main "
            "comparison's, and is not the same number."
        ),
    }


def observed_vs_predicted(
    series: HouseholdSeries,
    origin: date,
    models: tuple[Model, ...],
    config: ExperimentConfig,
) -> list[dict[str, Any]]:
    """One origin's seven days, for charting: actual beside each model's prediction."""
    out: list[dict[str, Any]] = []
    for horizon in range(1, config.horizon + 1):
        target = origin + timedelta(days=horizon)
        actual = series.at(target)
        entry: dict[str, Any] = {
            "target_date": target,
            "horizon": horizon,
            "actual_kwh": float(actual) if actual is not None else None,
            "actual_available": actual is not None,
        }
        for model in models:
            prediction = model.predict(series, origin, target)
            entry[model.name] = float(prediction.value) if prediction.made else None
            entry[f"{model.name}_reason"] = prediction.reason
        out.append(entry)
    return out
