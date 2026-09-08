"""Run the I-08 prior-data-eligibility experiment.

    uv run run-prior-eligibility --database data/warehouse/energy.duckdb

Prints the population and coverage **before** any accuracy figure, because the point of
this experiment is what changes about the population, not a leaderboard.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..ingest.warehouse import DEFAULT_DATABASE
from .prior_eligibility import PriorConfig, run_prior_eligibility

REPORT_DIR = Path("data/forecasts")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="run-prior-eligibility", description=__doc__)
    p.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    p.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    args = p.parse_args(argv)
    if not args.database.exists():
        print(f"error: no warehouse at {args.database}", file=sys.stderr)
        return 2

    report = run_prior_eligibility(args.database, PriorConfig())
    u, cov, ta, acc = (
        report["universe"],
        report["coverage"],
        report["target_availability"],
        report["accuracy"],
    )
    print("I-08 — eligibility from source dates at or before each origin")
    print(f"contract : {report['contract']}")
    print(f"status   : {report['kind']}")
    print()
    print("population (described before any accuracy figure)")
    print(f"  households considered        : {u['households']:,}")
    cal = u["origin_calendar"]
    print(
        f"  origin calendar              : {cal['origins']} origins, {cal['first']} to "
        f"{cal['last']}, every {cal['step_days']} days"
    )
    print(f"  derived from                 : {cal['derived_from']}")
    print(f"  household-origins scheduled  : {u['household_origins_scheduled']:,}")
    print(
        f"  household-origins qualifying : {u['household_origins_qualifying']:,} "
        f"({u['household_origins_qualifying'] / u['household_origins_scheduled']:.1%})"
    )
    print(f"  scheduled cases per model    : {u['scheduled_cases_per_model']:,}")
    print()
    print("coverage, with denominators")
    for model, c in cov.items():
        print(
            f"  {model:<18} prediction {c['prediction_coverage']:>7.1%} "
            f"({c['predictions_issued']:,}/{c['scheduled']:,})   "
            f"scoring {c['scoring_coverage']:>7.1%} ({c['scored']:,}/{c['scheduled']:,})"
        )
        for reason, n in sorted(c["declined_by_reason"].items(), key=lambda kv: -kv[1]):
            print(f"      declined {reason:<38} {n:,}")
    print()
    print("target availability (an independent axis)")
    for reason, n in sorted(ta["unavailable_by_reason"].items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<42} {n:,}")
    print(
        f"  declined AND unavailable                   {ta['declined_and_unavailable']:,}"
    )
    print()
    print(f"accuracy on the {acc['common_scoreable_cases']:,} cases every model scored")
    for model, m in sorted(
        acc["common_per_model"].items(), key=lambda kv: float(kv[1]["mae_kwh"])
    ):
        print(
            f"  {model:<18} MAE {m['mae_kwh']:>8} kWh   median {m['median_ae_kwh']:>8}   n={m['count']:,}"
        )
    print()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"i-08-{report['identity']['dataset_sha256'][:12]}.json"
    path.write_text(
        json.dumps(
            {k: v for k, v in report.items() if k != "_cases"}, indent=2, default=str
        )
        + "\n"
    )
    print(f"report : {path}")
    print(
        "Coverage and accuracy must be read together: a model can look better by "
        "declining harder cases, which is why both are published."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
