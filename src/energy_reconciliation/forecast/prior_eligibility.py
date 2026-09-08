"""I-08 -- eligibility decided from source dates at or before each origin.

The contract for this experiment was written and committed **before** any score here was
computed: ``docs/tickets/I-08-prior-data-eligibility.md``. This module implements it and
adds nothing to it.

What differs from FORE-001
--------------------------

FORE-001 chose households by a clean run found over their **whole** history, holdout
included, and placed origins inside that run. Here:

- the universe is **every** household in the warehouse;
- the **origin calendar is fixed and shared**, derived only from the warehouse's date
  span -- never from any household's clean-run endpoint;
- a household qualifies **at an origin** if the 28 dates ending there hold at least
  ``MIN_USABLE_IN_WINDOW`` usable days and the origin itself is usable, both judged from
  source dates ``<= origin`` only.

The three models and their settings are imported unchanged from FORE-001.

Two axes, never collapsed
-------------------------

Every scheduled (household, origin, horizon) case is classified twice:

- **prediction**: issued, or declined with a reason;
- **target**: scoreable, or unavailable with a reason.

A case can be both declined *and* unscoreable, and then it appears under both. Missing
future targets are counted, not dropped -- an evaluation that quietly forgets the days it
could not score reports the accuracy of the days that happened to survive.

**As-of-source-date, not production availability.** "Available at the origin" means the
source-date label is on or before it. Whether the reading would have been published by
then is not recorded by this archive and is not claimed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from ..tariff import identity
from .baselines import Model, default_models
from .dataset import DayRecord, HouseholdSeries, daily_records
from .evaluate import Metric, round_kwh

#: Usable days required among the 28 dates ending at an origin. Fixed in the contract
#: before the experiment ran; not tuned.
MIN_USABLE_IN_WINDOW: Final[int] = 20
WINDOW_DAYS: Final[int] = 28

ISSUED, DECLINED = "issued", "declined"
SCOREABLE, UNAVAILABLE = "scoreable", "unavailable"

INSUFFICIENT_WINDOW: Final[str] = "insufficient_usable_history_in_window"
ORIGIN_UNUSABLE: Final[str] = "origin_day_not_usable"
TARGET_NOT_USABLE: Final[str] = "target_day_not_usable"
TARGET_ABSENT: Final[str] = "target_day_absent_from_warehouse"


@dataclass(frozen=True, slots=True)
class PriorConfig:
    """Everything that decides what is evaluated. Frozen in the contract."""

    horizon: int = 7
    window_days: int = WINDOW_DAYS
    min_usable_in_window: int = MIN_USABLE_IN_WINDOW
    origin_step_days: int = 7

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class Case:
    """One scheduled (household, origin, horizon), classified on both axes."""

    household_id: str
    origin: date
    horizon: int
    target_date: date
    prediction_state: str
    prediction_reason: str | None
    target_state: str
    target_reason: str | None
    model: str
    actual: Decimal | None
    predicted: Decimal | None

    @property
    def scored(self) -> bool:
        return (
            self.prediction_state == ISSUED
            and self.target_state == SCOREABLE
            and self.actual is not None
            and self.predicted is not None
        )

    @property
    def abs_error(self) -> Decimal | None:
        return abs(self.actual - self.predicted) if self.scored else None


def origin_calendar(
    records: dict[str, list[DayRecord]], config: PriorConfig
) -> list[date]:
    """A fixed calendar shared by every household, from the warehouse span alone.

    Deliberately **not** derived from any household's clean run: doing so would let a
    household's later data quality decide where it is evaluated, which is the very
    hindsight this experiment removes.
    """
    all_dates = [r.source_date for rows in records.values() for r in rows]
    if not all_dates:
        return []
    first, last = min(all_dates), max(all_dates)
    start = first + timedelta(days=config.window_days - 1)
    origins: list[date] = []
    origin = start
    while origin + timedelta(days=config.horizon) <= last:
        origins.append(origin)
        origin += timedelta(days=config.origin_step_days)
    return origins


def _usable_map(rows: list[DayRecord]) -> dict[date, Decimal]:
    return {r.source_date: r.kwh for r in rows if r.usable and r.kwh is not None}


def qualifies_at(
    usable: dict[date, Decimal], origin: date, config: PriorConfig
) -> bool:
    """Judged from source dates <= origin only. Nothing later is consulted."""
    if origin not in usable:
        return False
    window_start = origin - timedelta(days=config.window_days - 1)
    return (
        sum(1 for d in usable if window_start <= d <= origin)
        >= config.min_usable_in_window
    )


def _history_series(
    household: str, usable: dict[date, Decimal], origin: date, config: PriorConfig
) -> HouseholdSeries:
    """A series exposing **only** dates at or before the origin.

    Built per origin so that a model physically cannot read a later value, whatever it
    asks for. The run bounds are the earliest usable date and the origin itself, so the
    weekday model's backward walk terminates correctly.
    """
    visible = {d: v for d, v in usable.items() if d <= origin}
    first = min(visible) if visible else origin
    return HouseholdSeries(household, first, origin, visible)


def run_prior_eligibility(
    database: Path,
    config: PriorConfig | None = None,
    models: tuple[Model, ...] | None = None,
) -> dict[str, Any]:
    """Evaluate every scheduled case under prior-data eligibility."""
    config = config or PriorConfig()
    models = models or default_models()
    records = daily_records(database)
    origins = origin_calendar(records, config)
    usable_by_household = {h: _usable_map(rows) for h, rows in records.items()}
    recorded_dates = {h: {r.source_date for r in rows} for h, rows in records.items()}

    cases: list[Case] = []
    scheduled = 0
    qualifying_origins = 0
    for household in sorted(records):
        usable = usable_by_household[household]
        recorded = recorded_dates[household]
        for origin in origins:
            qualifies = qualifies_at(usable, origin, config)
            if qualifies:
                qualifying_origins += 1
                history = _history_series(household, usable, origin, config)
            for horizon in range(1, config.horizon + 1):
                target = origin + timedelta(days=horizon)
                scheduled += 1
                if target in usable:
                    target_state, target_reason, actual = (
                        SCOREABLE,
                        None,
                        usable[target],
                    )
                else:
                    target_state = UNAVAILABLE
                    target_reason = (
                        TARGET_NOT_USABLE if target in recorded else TARGET_ABSENT
                    )
                    actual = None
                for model in models:
                    if not qualifies:
                        reason = (
                            ORIGIN_UNUSABLE
                            if origin not in usable
                            else INSUFFICIENT_WINDOW
                        )
                        cases.append(
                            Case(
                                household,
                                origin,
                                horizon,
                                target,
                                DECLINED,
                                reason,
                                target_state,
                                target_reason,
                                model.name,
                                actual,
                                None,
                            )
                        )
                        continue
                    prediction = model.predict(history, origin, target)
                    cases.append(
                        Case(
                            household,
                            origin,
                            horizon,
                            target,
                            ISSUED if prediction.made else DECLINED,
                            prediction.reason,
                            target_state,
                            target_reason,
                            model.name,
                            actual,
                            prediction.value,
                        )
                    )
    return _report(
        database, config, models, origins, cases, scheduled, qualifying_origins, records
    )


def _metrics(cases: list[Case], key) -> dict[str, dict[str, Any]]:
    metrics: dict[Any, Metric] = {}
    for case in cases:
        if case.scored:
            metrics.setdefault(key(case), Metric()).add(case.abs_error)
    return {
        str(k): {
            "count": m.count,
            "mae_kwh": str(round_kwh(m.mae)),
            "mae_kwh_exact": str(m.mae),
            "median_ae_kwh": str(round_kwh(m.median_ae)),
        }
        for k, m in sorted(metrics.items(), key=lambda kv: str(kv[0]))
    }


def _report(
    database, config, models, origins, cases, scheduled, qualifying_origins, records
) -> dict[str, Any]:
    per_model = scheduled  # scheduled cases per model
    model_names = [m.name for m in models]
    issued = {
        m: sum(1 for c in cases if c.model == m and c.prediction_state == ISSUED)
        for m in model_names
    }
    scoreable = {
        m: sum(1 for c in cases if c.model == m and c.target_state == SCOREABLE)
        for m in model_names
    }
    scored = {
        m: sum(1 for c in cases if c.model == m and c.scored) for m in model_names
    }

    decline_reasons: dict[str, dict[str, int]] = {}
    for c in cases:
        if c.prediction_state == DECLINED:
            decline_reasons.setdefault(c.model, {})
            r = c.prediction_reason or "unknown"
            decline_reasons[c.model][r] = decline_reasons[c.model].get(r, 0) + 1
    target_reasons: dict[str, int] = {}
    for c in cases:
        if c.model == model_names[0] and c.target_state == UNAVAILABLE:
            r = c.target_reason or "unknown"
            target_reasons[r] = target_reasons.get(r, 0) + 1
    both = sum(
        1
        for c in cases
        if c.model == model_names[0]
        and c.prediction_state == DECLINED
        and c.target_state == UNAVAILABLE
    )

    # common scoreable cases: every model scored them
    counts: dict[tuple[str, date, int], int] = {}
    for c in cases:
        if c.scored:
            k = (c.household_id, c.origin, c.horizon)
            counts[k] = counts.get(k, 0) + 1
    common_keys = {k for k, n in counts.items() if n == len(models)}
    common = [
        c
        for c in cases
        if c.scored and (c.household_id, c.origin, c.horizon) in common_keys
    ]

    dataset_digest = hashlib.sha256()
    for household in sorted(records):
        for r in records[household]:
            if r.usable and r.kwh is not None:
                dataset_digest.update(f"{household}|{r.source_date}={r.kwh}".encode())
    code = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        code.update(path.name.encode())
        code.update(path.read_bytes())

    return {
        "generated_at_utc": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
        "experiment": "I-08 prior-data eligibility",
        "contract": "docs/tickets/I-08-prior-data-eligibility.md (frozen before this ran)",
        "database": str(database),
        "kind": (
            "as-of-source-date simulation, not a reconstruction of historical production "
            "availability; NOT a fresh independent holdout -- it re-uses the same "
            "warehouse and dates, including FORE-001's already-inspected holdout window"
        ),
        "config": asdict(config),
        "models": model_names,
        "universe": {
            "households": len(records),
            "origin_calendar": {
                "origins": len(origins),
                "first": str(origins[0]) if origins else None,
                "last": str(origins[-1]) if origins else None,
                "step_days": config.origin_step_days,
                "derived_from": "warehouse date span only, never a clean-run endpoint",
            },
            "scheduled_cases_per_model": per_model,
            "household_origins_qualifying": qualifying_origins,
            "household_origins_scheduled": len(records) * len(origins),
        },
        "coverage": {
            model: {
                "scheduled": per_model,
                "predictions_issued": issued[model],
                "prediction_coverage": round(issued[model] / per_model, 4)
                if per_model
                else 0.0,
                "targets_scoreable": scoreable[model],
                "scored": scored[model],
                "scoring_coverage": round(scored[model] / per_model, 4)
                if per_model
                else 0.0,
                "declined_by_reason": decline_reasons.get(model, {}),
            }
            for model in model_names
        },
        "target_availability": {
            "unavailable_by_reason": target_reasons,
            "declined_and_unavailable": both,
            "note": (
                "The two axes are independent: a case can be declined and unscoreable at "
                "once, and is then counted under both. No scheduled case is dropped."
            ),
        },
        "accuracy": {
            "all_scored_per_model": _metrics(cases, lambda c: c.model),
            "common_scoreable_cases": len(common_keys),
            "common_per_model": _metrics(common, lambda c: c.model),
            "common_per_model_horizon": _metrics(
                common, lambda c: f"{c.model}|h{c.horizon}"
            ),
        },
        "overlap_with_fore_001": _overlap(cases, database, model_names),
        "identity": {
            "dataset_sha256": dataset_digest.hexdigest(),
            "forecast_code_sha256": code.hexdigest(),
            "config_sha256": config.digest,
            "calculation_code_sha256": identity.calculation_digest(),
            "runtime": identity.runtime_identity(),
        },
        "_cases": cases,
    }


def _overlap(
    cases: list[Case], database: Path, model_names: list[str]
) -> dict[str, Any]:
    """How much of FORE-001 this experiment shares, and whether it reproduces it.

    The two origin calendars are different by construction: FORE-001 places origins
    relative to each household's own clean-run start, while I-08 uses one calendar
    derived from the warehouse span. Most cases therefore do **not** coincide, and the
    ones that do are a check, not a comparison population.
    """
    from .dataset import eligible_series
    from .evaluate import ExperimentConfig, evaluate_series

    fcfg = ExperimentConfig()
    prior: dict[tuple[str, date, int, str], Decimal] = {}
    for series in eligible_series(database, fcfg.min_run_days, fcfg.household_limit):
        for row in evaluate_series(series, default_models(), fcfg):
            if row.scored:
                prior[(row.household_id, row.origin, row.horizon, row.model)] = (
                    row.abs_error
                )

    scored = [c for c in cases if c.scored]
    prior_cases = {(h, o, x) for h, o, x, _ in prior}
    # The I-08 side of the split is every case scored by AT LEAST ONE model. That is
    # deliberately not the common frame (cases every model scored): a case one model
    # scored and another declined still belongs to the population, and the per-model
    # figures below count only the cases that model itself scored. In FORE-001 the two
    # sets coincide because its models are scored on identical cases.
    mine = {(c.household_id, c.origin, c.horizon) for c in scored}
    per_case: dict[tuple[str, date, int], int] = {}
    for c in scored:
        k = (c.household_id, c.origin, c.horizon)
        per_case[k] = per_case.get(k, 0) + 1
    every = {k for k, n in per_case.items() if n == len(model_names)}
    shared, new = prior_cases & mine, mine - prior_cases

    mismatches = 0
    compared = 0
    for c in scored:
        key = (c.household_id, c.origin, c.horizon, c.model)
        if key in prior:
            compared += 1
            if prior[key] != c.abs_error:
                mismatches += 1

    def mae(subset: list[Case]) -> str | None:
        return (
            str(round_kwh(sum(c.abs_error for c in subset) / Decimal(len(subset))))
            if subset
            else None
        )

    def in_set(model: str, keys: set[tuple[str, date, int]]) -> list[Case]:
        return [
            c
            for c in scored
            if c.model == model and (c.household_id, c.origin, c.horizon) in keys
        ]

    return {
        "fore_001_scored_cases": len(prior_cases),
        "i08_scored_cases": len(mine),
        "i08_scored_cases_definition": (
            "(household, origin, horizon) cases scored by at least one model -- a "
            "prediction was issued and the target was usable. Not the common frame."
        ),
        "i08_cases_scored_by_every_model": len(every),
        "shared_cases": len(shared),
        "new_to_i08": len(new),
        "in_fore_001_only": len(prior_cases - mine),
        "scored_per_model_on_shared": {m: len(in_set(m, shared)) for m in model_names},
        "scored_per_model_on_new": {m: len(in_set(m, new)) for m in model_names},
        "shared_pairs_compared": compared,
        "shared_absolute_error_mismatches": mismatches,
        "reproduces_fore_001_on_shared_cases": mismatches == 0,
        "mae_on_shared": {m: mae(in_set(m, shared)) for m in model_names},
        "mae_on_new": {m: mae(in_set(m, new)) for m in model_names},
        "note": (
            "The origin calendars differ by construction, so most cases do not coincide. "
            "Shared cases are a correctness check that the two implementations agree, "
            "not a population for comparison; the newly included cases are where this "
            "experiment's population actually differs. Shared + new = the cases scored "
            "by at least one model; each model's MAE on either side is over the cases "
            "that model itself scored there, so its denominator is at most the set size."
        ),
    }
