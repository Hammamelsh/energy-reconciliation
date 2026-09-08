"""Run the FORE-001 backtest and write its result.

    uv run run-forecast-experiment --database data/warehouse/energy.duckdb

Produces a **historical backtest**, never a live forecast, and prints development results
before the holdout so the holdout is read last.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from ..ingest.warehouse import DEFAULT_DATABASE
from .evaluate import DEVELOPMENT, HOLDOUT, ExperimentConfig, run_experiment

REPORT_DIR = Path("data/forecasts")


def _table(title: str, section: dict) -> str:
    lines = [
        f"  {title}",
        f"    {'model':<20} {'n':>7}  {'MAE kWh':>9}  {'median AE':>9}",
    ]
    for name, m in sorted(
        section.items(), key=lambda kv: Decimal(kv[1]["mae_kwh_exact"])
    ):
        lines.append(
            f"    {name:<20} {m['count']:>7,}  {m['mae_kwh']:>9}  {m['median_ae_kwh']:>9}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="run-forecast-experiment", description=__doc__)
    p.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    p.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    p.add_argument("--households", type=int, default=None, help="bound the selection")
    args = p.parse_args(argv)
    if not args.database.exists():
        print(f"error: no warehouse at {args.database}", file=sys.stderr)
        return 2

    config = ExperimentConfig()
    if args.households is not None:
        config = ExperimentConfig(household_limit=args.households)
    report = run_experiment(args.database, config)

    f = report["feasibility"]
    print("FORE-001 — historical backtest, not a live forecast")
    print(f"target : {report['target']}")
    print()
    print("feasibility of the loaded data")
    print(f"  households loaded            : {f['households']:,}")
    print(f"  household-days               : {f['household_days']:,}")
    print("  usable (48 labels, no Null,")
    print(f"          no disagreement)     : {f['usable_household_days']:,}")
    print(
        f"  eligible households          : {f['eligible_households']:,} "
        f"(contiguous usable run >= {f['min_run_days']} days)"
    )
    print(f"  selected for this run        : {len(report['households']):,}")
    print()
    for split in (DEVELOPMENT, HOLDOUT):
        section = report["evaluation"][split]
        print(
            f"{split.upper()}  scored {section['scored_predictions']:,}  "
            f"excluded {section['excluded_predictions']:,}"
        )
        print(_table("by model", section["by_model"]))
        if section["exclusions"]:
            print("    exclusions:")
            for reason, count in sorted(section["exclusions"].items()):
                print(f"      {reason:<48} {count:,}")
        print()

    print("by horizon (holdout)")
    holdout = report["evaluation"][HOLDOUT]["by_model_horizon"]
    models = sorted({k.split("|")[0] for k in holdout})
    print(f"    {'horizon':<9}" + "".join(f"{m:>20}" for m in models))
    for h in range(1, report["config"]["horizon"] + 1):
        cells = "".join(
            f"{holdout.get(f'{m}|h{h}', {}).get('mae_kwh', '-'):>20}" for m in models
        )
        print(f"    h+{h:<7}" + cells)
    print()

    sweep = report["weeks_sweep"]
    print("does averaging more same-weekday history help? (development only)")
    print(
        f"    compared on {sweep['compared_on_common_triples']:,} triples every "
        f"candidate predicted; {sweep['declined_by_some_candidate']:,} declined by at "
        "least one"
    )
    for name, m in sorted(
        sweep["development_mae_by_weeks"].items(),
        key=lambda kv: int(kv[0].rsplit("_", 1)[1]),
    ):
        print(f"    {name:<20} MAE {m['mae_kwh']:>9}")
    chosen = sweep["holdout_of_selected_only"]
    print(f"    selected on development: {sweep['selected_weeks']} weeks")
    for name, m in chosen.items():
        print(f"    holdout, scored once for {name}: MAE {m['mae_kwh']} kWh")
    print()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = report["identity"]["dataset_sha256"][:12]
    path = args.output_dir / f"fore-001-{stem}.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"report : {path}")
    print(
        "This is a backtest over recorded history. It is not a bill, a saving, or a "
        "claim about appliances or tariff response."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
