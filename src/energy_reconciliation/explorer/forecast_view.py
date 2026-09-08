"""Adapter between the forecast experiment and the explorer. No Streamlit, no modelling.

Shapes the recorded experiment and one household's series into frames the tab renders.
Every number it produces comes from :mod:`energy_reconciliation.forecast`; nothing is
recomputed here with different rules.
"""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from ..forecast import applicability
from ..forecast.baselines import Model, default_models
from ..forecast.dataset import HouseholdSeries, series_for
from ..forecast.evaluate import (
    ExperimentConfig,
    evaluate_series,
    observed_vs_predicted,
    origins_for,
    round_kwh,
)
from .charts import MODEL_LABELS, MODEL_ONLY

REPORT_DIR = Path("data/forecasts")
OBSERVED = "observed"

__all__ = [
    "OBSERVED",
    "config_from",
    "default_models",
    "describe_cohort",
    "describe_members",
    "exclusion_frame",
    "horizon_frame",
    "load_latest_report",
    "load_prior_report",
    "long_frame",
    "model_frame",
    "model_table",
    "observed_vs_predicted",
    "origin_table",
    "origins_for",
    "prior_comparison_table",
    "prior_overlap_table",
    "prior_population_table",
    "series_for",
    "sweep_table",
    "worst_days",
]


def load_latest_report(directory: Path = REPORT_DIR) -> dict[str, Any] | None:
    """The most recently generated experiment, or None if none has been run."""
    if not directory.is_dir():
        return None
    reports = sorted(directory.glob("fore-001-*.json"), key=lambda p: p.stat().st_mtime)
    if not reports:
        return None
    return json.loads(reports[-1].read_text())


def load_prior_report(directory: Path = REPORT_DIR) -> dict[str, Any] | None:
    """The most recent I-08 prior-data-eligibility report, or None."""
    if not directory.is_dir():
        return None
    reports = sorted(directory.glob("i-08-*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(reports[-1].read_text()) if reports else None


def assess_reports(
    reports: dict[str, dict[str, Any] | None], target: Any
) -> dict[str, applicability.Applicability | None]:
    """Does each report describe the selected dataset? One scan for all of them.

    ``target`` is the selected database path today; when the dashboard reads published
    versions it will be a tariff ``ReadContext``, which is used as-is (its ``database``),
    never re-resolved here. Replaces the file-name comparison the tab used to make.
    """
    return applicability.assess_reports(reports, target)


def applicability_message(fit: applicability.Applicability, selected: Path) -> str:
    """What to tell a reader when a report does not describe the selected dataset."""
    recorded = Path(fit.recorded_database).name or "an unrecorded file"
    head = (
        f"**This report does not describe `{selected.name}`.** It was recorded against "
        f"`{recorded}`"
        + (" (a different file name)" if fit.renamed else " (the same file name)")
        + f", and {fit.reason}."
    )
    if fit.outcome == applicability.UNVERIFIABLE:
        head = (
            f"**Whether this report describes `{selected.name}` cannot be established:** "
            f"{fit.reason}. It is not shown, because an unverified match is not a match."
        )
    lines = [head]
    differing = [c for c in fit.checks if not c.matches][:6]
    if differing:
        lines.append("")
        lines.append("| Recorded claim | In the report | In this dataset |")
        lines.append("|---|---|---|")
        for c in differing:
            lines.append(
                f"| `{c.field}` | {_short(c.recorded)} | {_short(c.current)} |"
            )
    lines.append("")
    lines.append(
        "Rerun the experiment for this dataset before reading its figures: "
        f"`uv run {'run-prior-eligibility' if fit.kind == applicability.I08 else 'run-forecast-experiment'}"
        f" --database {selected}`"
    )
    return "\n".join(lines)


def applicability_note(fit: applicability.Applicability, selected: Path) -> str:
    """One line for an applicable report: what was verified, and the provenance."""
    recorded = Path(fit.recorded_database).name
    where = (
        f"recorded against `{recorded}`, now read from `{selected.name}` -- same content, "
        "different file"
        if fit.renamed
        else f"recorded against and read from `{selected.name}`"
    )
    return (
        f"**Applies to this dataset**: {len(fit.checks)} recorded claims recompute "
        f"identically from its rows ({fit.definition}); {where}."
    )


def _short(value: str | None, limit: int = 60) -> str:
    if value is None:
        return "*not recorded*"
    text = value.replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def prior_comparison_table(prior: dict[str, Any]) -> pd.DataFrame:
    """Accuracy beside coverage, so neither can be read without the other."""
    accuracy = prior["accuracy"]["common_per_model"]
    rows = []
    for name, coverage in prior["coverage"].items():
        metric = accuracy.get(name, {})
        rows.append(
            {
                "Model": MODEL_LABELS.get(name, name),
                "MAE (kWh), common cases": metric.get("mae_kwh", "—"),
                "Prediction coverage": f"{coverage['prediction_coverage']:.1%}",
                "Scoring coverage": f"{coverage['scoring_coverage']:.1%}",
                "Predictions issued": f"{coverage['predictions_issued']:,}",
                "Scored": f"{coverage['scored']:,}",
                "Scheduled": f"{coverage['scheduled']:,}",
            }
        )
    order = {v: i for i, v in enumerate(MODEL_ONLY)}
    return pd.DataFrame(sorted(rows, key=lambda r: order.get(r["Model"], 99)))


def prior_population_table(prior: dict[str, Any]) -> pd.DataFrame:
    """What the population change actually was, before any accuracy is read.

    Three case counts appear on this page and they are different sets, so each row
    names its own. *Scheduled* is every (household, origin, horizon) on the calendar.
    *Scored by at least one model* is the subset with an issued prediction and a usable
    target for some model -- the set the shared/new split is over. *Scored by every
    model* is the smaller common frame the accuracy table uses.
    """
    universe, overlap = prior["universe"], prior["overlap_with_fore_001"]
    calendar = universe["origin_calendar"]
    every = overlap.get(
        "i08_cases_scored_by_every_model",
        prior["accuracy"]["common_scoreable_cases"],
    )
    return pd.DataFrame(
        [
            {
                "Measure": "Households considered",
                "Value": f"{universe['households']:,}",
            },
            {
                "Measure": "Origins (shared calendar)",
                "Value": f"{calendar['origins']} · {calendar['first']} to {calendar['last']}",
            },
            {
                "Measure": "Household-origins qualifying",
                "Value": (
                    f"{universe['household_origins_qualifying']:,} of "
                    f"{universe['household_origins_scheduled']:,}"
                ),
            },
            {
                "Measure": "Scheduled cases per model",
                "Value": f"{universe['scheduled_cases_per_model']:,}",
            },
            {
                "Measure": "Cases scored by at least one model",
                "Value": (
                    f"{overlap['i08_scored_cases']:,} of the scheduled cases; "
                    f"{every:,} of these were scored by every model"
                ),
            },
            {
                "Measure": "— of which shared with FORE-001",
                "Value": (
                    f"{overlap['shared_cases']:,} (same household, origin and days "
                    f"ahead; FORE-001 scored {overlap['fore_001_scored_cases']:,}, "
                    f"{overlap['in_fore_001_only']:,} of them on origins this calendar "
                    "does not have)"
                ),
            },
            {
                "Measure": "— of which new to this experiment",
                "Value": (
                    f"{overlap['new_to_i08']:,} "
                    f"({overlap['shared_cases']:,} + {overlap['new_to_i08']:,} = "
                    f"{overlap['i08_scored_cases']:,})"
                ),
            },
            {
                "Measure": "Reproduces FORE-001 on shared cases",
                "Value": (
                    f"{overlap['reproduces_fore_001_on_shared_cases']} "
                    f"({overlap['shared_pairs_compared']:,} pairs, "
                    f"{overlap['shared_absolute_error_mismatches']} mismatches)"
                ),
            },
        ]
    )


def prior_overlap_table(prior: dict[str, Any]) -> pd.DataFrame:
    """Shared-with-FORE-001 against newly included, per model, with the count each MAE
    is over. A model's count on either side is the cases *it* scored there, so it can be
    below the set size; the set sizes are on the population table."""
    overlap = prior["overlap_with_fore_001"]
    shared_n = overlap.get("scored_per_model_on_shared", {})
    new_n = overlap.get("scored_per_model_on_new", {})
    rows = []
    for name in prior["models"]:
        rows.append(
            {
                "Model": MODEL_LABELS.get(name, name),
                "Shared cases this model scored": (
                    f"{shared_n[name]:,}" if name in shared_n else "—"
                ),
                "MAE (kWh), shared": overlap["mae_on_shared"].get(name) or "—",
                "New cases this model scored": (
                    f"{new_n[name]:,}" if name in new_n else "—"
                ),
                "MAE (kWh), new": overlap["mae_on_new"].get(name) or "—",
            }
        )
    order = {v: i for i, v in enumerate(MODEL_ONLY)}
    return pd.DataFrame(sorted(rows, key=lambda r: order.get(r["Model"], 99)))


def config_from(recorded: dict[str, Any]) -> ExperimentConfig:
    """Rebuild the recorded configuration, ignoring keys this version does not know."""
    known = {f.name for f in fields(ExperimentConfig)}
    return ExperimentConfig(**{k: v for k, v in recorded.items() if k in known})


def long_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """One row per (target date, series) for charting; declined points are dropped."""
    out: list[dict[str, Any]] = []
    for entry in rows:
        out.append(
            {
                "target_date": entry["target_date"],
                "horizon": entry["horizon"],
                "series": MODEL_LABELS[OBSERVED],
                "value": entry["actual_kwh"],
            }
        )
        for key, value in entry.items():
            if key.endswith("_reason") or key in {
                "target_date",
                "horizon",
                "actual_kwh",
                "actual_available",
            }:
                continue
            out.append(
                {
                    "target_date": entry["target_date"],
                    "horizon": entry["horizon"],
                    "series": MODEL_LABELS.get(key, key),
                    "value": value,
                }
            )
    frame = pd.DataFrame(out)
    if not frame.empty:
        frame["target_date"] = pd.to_datetime(frame["target_date"])
    return frame


def origin_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """The same seven days as text, with a reason wherever a model declined."""
    models = [
        k
        for k in (rows[0] if rows else {})
        if not k.endswith("_reason")
        and k not in {"target_date", "horizon", "actual_kwh", "actual_available"}
    ]
    table = []
    for entry in rows:
        record = {
            "Target source date": f"{entry['target_date']:%a %-d %b %Y}",
            "Days ahead": entry["horizon"],
            "Observed kWh": (
                f"{entry['actual_kwh']:,.3f}"
                if entry["actual_available"]
                else "not usable"
            ),
        }
        for name in models:
            value = entry[name]
            reason = entry.get(f"{name}_reason")
            record[MODEL_LABELS.get(name, name)] = (
                f"{value:,.3f}" if value is not None else f"declined: {reason}"
            )
        table.append(record)
    return pd.DataFrame(table)


def model_frame(section: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {
            "model": MODEL_LABELS.get(name, name),
            "mae_kwh": float(metric["mae_kwh"]),
            "mae_label": f"{float(metric['mae_kwh']):,.3f}",
            "count": metric["count"],
        }
        for name, metric in section["by_model"].items()
    ]
    return pd.DataFrame(rows)


def horizon_frame(section: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for key, metric in section["by_model_horizon"].items():
        model, horizon = key.split("|h")
        rows.append(
            {
                "model": MODEL_LABELS.get(model, model),
                "horizon": int(horizon),
                "mae_kwh": float(metric["mae_kwh"]),
                "count": metric["count"],
            }
        )
    return pd.DataFrame(rows).sort_values(["model", "horizon"])


def model_table(section: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Model": MODEL_LABELS.get(name, name),
                "Identifier": name,
                "Scored predictions": f"{metric['count']:,}",
                "MAE (kWh)": metric["mae_kwh"],
                "Median absolute error (kWh)": metric["median_ae_kwh"],
            }
            for name, metric in sorted(
                section["by_model"].items(), key=lambda kv: float(kv[1]["mae_kwh"])
            )
        ]
    )


def exclusion_frame(section: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Model and reason": reason, "Predictions": f"{count:,}"}
            for reason, count in sorted(section["exclusions"].items())
        ]
    )


def worst_days(
    series: HouseholdSeries,
    models: tuple[Model, ...],
    config: ExperimentConfig,
    limit: int = 10,
) -> pd.DataFrame:
    """The largest absolute errors for one household, with the days each model used.

    Shown so a reader can see *what kind of day* the models miss, rather than being told.
    Each model's input is visible in its own column: the one-week naive repeats *Same
    weekday, 1 week earlier*; the 4-week mean averages the four values in *Same weekday,
    4 → 1 weeks earlier* (its prediction is exactly their mean); persistence repeats
    *Origin day*. The dates in the last column are the ones the model actually read,
    taken from the prediction record rather than recomputed here.
    """
    rows = [r for r in evaluate_series(series, models, config) if r.scored]
    rows.sort(key=lambda r: r.abs_error, reverse=True)
    out = []
    for r in rows[:limit]:
        previous = series.at(r.target_date - timedelta(days=7))
        four = [series.at(r.target_date - timedelta(days=7 * k)) for k in (4, 3, 2, 1)]
        origin_value = series.at(r.origin)
        out.append(
            {
                "Target source date": f"{r.target_date:%a %-d %b %Y}",
                "Model": MODEL_LABELS.get(r.model, r.model),
                "Days ahead": r.horizon,
                "Observed kWh": f"{round_kwh(r.actual):,}",
                "Predicted kWh": f"{round_kwh(r.predicted):,}",
                "Absolute error kWh": f"{round_kwh(r.abs_error):,}",
                "Same weekday, 1 week earlier": _kwh_or_not_usable(previous),
                "Same weekday, 4 → 1 weeks earlier": " · ".join(
                    _kwh_or_not_usable(v) for v in four
                ),
                "Origin day": (
                    f"{r.origin:%a %-d %b} = {_kwh_or_not_usable(origin_value)}"
                ),
                "Dates the model read": ", ".join(f"{d:%-d %b}" for d in r.inputs),
            }
        )
    return pd.DataFrame(out)


def _kwh_or_not_usable(value: Decimal | None) -> str:
    return f"{round_kwh(value):,}" if value is not None else "not usable"


def household_daily_series(series: HouseholdSeries) -> pd.DataFrame:
    """The whole usable run, for context."""
    return pd.DataFrame(
        [
            {"source_date": day, "kwh": float(value)}
            for day, value in sorted(series.values.items())
        ]
    )


def is_eligible(report: dict[str, Any] | None, household: str) -> bool:
    if report is None:
        return False
    return any(h["household_id"] == household for h in report["households"])


def date_from(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def as_decimal(value: float | str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def describe_cohort(selection: dict[str, Any]) -> str:
    """'40 of 71 eligible · 35 Std / 5 ToU · 26 in member 4 only, ...'."""
    if not selection:
        return "recorded experiment"
    groups = " / ".join(
        f"{n} {g}" for g, n in sorted(selection.get("cohort_tariff_groups", {}).items())
    )
    return (
        f"{selection.get('selected_households', '?')} of "
        f"{selection.get('eligible_households', '?')} eligible households · {groups} · "
        f"{describe_members(selection.get('cohort_members', {}))}"
    )


def describe_members(cohort_members: dict[str, int]) -> str:
    """'26 in member 4 only, 1 spanning members 4 and 5, 8 in member 5 only, ...'.

    Derived from the recorded membership sets: a household appearing in two members is
    its own category, because its readings straddle a file boundary. Ordered by member
    number, not by string, so 135 does not sort before 4.
    """

    def numbers(key: str) -> list[int]:
        return [
            int(m.replace("LCL-June2015v2_", "").replace(".csv", ""))
            for m in key.split("+")
        ]

    parts = []
    for key, count in sorted(cohort_members.items(), key=lambda kv: numbers(kv[0])):
        ms = numbers(key)
        if len(ms) == 1:
            parts.append(f"{count} in member {ms[0]} only")
        else:
            parts.append(f"{count} spanning members {' and '.join(str(m) for m in ms)}")
    return ", ".join(parts) if parts else "no members recorded"


def sweep_table(sweep: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, metric in sorted(
        sweep["development_mae_by_weeks"].items(),
        key=lambda kv: int(kv[0].rsplit("_", 1)[1]),
    ):
        weeks = int(name.rsplit("_", 1)[1])
        rows.append(
            {
                "Weeks averaged": weeks,
                "Development MAE (kWh), common frame": metric["mae_kwh"],
                "Scored": f"{metric['count']:,}",
                "Selected on development": "yes"
                if weeks == sweep["selected_weeks"]
                else "",
            }
        )
    return pd.DataFrame(rows)
