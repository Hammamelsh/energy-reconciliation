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

from ..forecast.baselines import Model, default_models
from ..forecast.dataset import HouseholdSeries, series_for
from ..forecast.evaluate import (
    ExperimentConfig,
    evaluate_series,
    observed_vs_predicted,
    origins_for,
    round_kwh,
)
from .charts import MODEL_LABELS

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
    "long_frame",
    "model_frame",
    "model_table",
    "observed_vs_predicted",
    "origin_table",
    "origins_for",
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
    """
    rows = [r for r in evaluate_series(series, models, config) if r.scored]
    rows.sort(key=lambda r: r.abs_error, reverse=True)
    out = []
    for r in rows[:limit]:
        previous = series.at(r.target_date - timedelta(days=7))
        out.append(
            {
                "Target source date": f"{r.target_date:%a %-d %b %Y}",
                "Model": MODEL_LABELS.get(r.model, r.model),
                "Days ahead": r.horizon,
                "Observed kWh": f"{round_kwh(r.actual):,}",
                "Predicted kWh": f"{round_kwh(r.predicted):,}",
                "Absolute error kWh": f"{round_kwh(r.abs_error):,}",
                "Same weekday a week earlier": (
                    f"{round_kwh(previous):,}" if previous is not None else "not usable"
                ),
            }
        )
    return pd.DataFrame(out)


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
