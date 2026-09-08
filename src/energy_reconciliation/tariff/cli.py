"""Build the tariff scenario for a warehouse.

    uv run build-tariff-scenario --database data/warehouse/energy.duckdb
    uv run build-tariff-scenario --demo --database data/warehouse/demo.duckdb

Rerunning with unchanged inputs is a no-op. Any change to the schedule, the price
catalogue version, the modelling code, the ingestion pipeline or the set of loaded
files rebuilds the scenario, because a result produced by different inputs must never
be presented as the current one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..ingest.warehouse import DEFAULT_DATABASE
from . import prices as pr
from .models import ASSUMPTION_ID, build_scenario
from .schedule import DEFAULT_WORKBOOK, ScheduleError, demo_schedule, read_workbook


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build-tariff-scenario",
        description=(
            "Materialise the tariff band schedule, the publisher-documented price "
            "catalogue and an assumption-labelled interval charge scenario. This "
            "produces a scenario, not a bill."
        ),
    )
    p.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    p.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    p.add_argument(
        "--demo",
        action="store_true",
        help="use the synthetic one-day schedule instead of the real workbook",
    )
    p.add_argument(
        "--tariff-group",
        default=pr.TOU_GROUP,
        help="tariff group the band prices apply to (default: ToU)",
    )
    p.add_argument(
        "--force", action="store_true", help="rebuild even if the inputs are unchanged"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.demo and not args.workbook.exists():
        print(f"error: workbook not found: {args.workbook}", file=sys.stderr)
        return 2
    if not args.database.exists():
        print(
            f"error: no warehouse at {args.database}; run ingest-member first",
            file=sys.stderr,
        )
        return 2
    try:
        schedule = demo_schedule() if args.demo else read_workbook(args.workbook)
    except ScheduleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = build_scenario(
        args.database, schedule, tariff_group=args.tariff_group, force=args.force
    )
    print(
        f"schedule : {schedule.source} ({len(schedule.rows):,} labels, "
        f"{schedule.first_label} to {schedule.last_label})"
    )
    print(f"sha256   : {schedule.source_sha256}")
    print(f"prices   : catalogue {pr.PRICE_CATALOGUE_VERSION}, PUBLISHER-DOCUMENTED")
    if result.skipped:
        print(f"skipped  : inputs unchanged; run {result.run_id} still current")
    else:
        action = "rebuilt" if result.replaced_previous else "built  "
        print(f"{action}  : run {result.run_id}")
    print(f"assumption: {ASSUMPTION_ID} stamped on every charged row")
    print(f"rows recorded      : {result.raw_rows:,}")
    print(f"collapsed by policy: {result.rows_collapsed_by_policy:,}")
    print(f"distinct readings  : {result.distinct_readings:,}")
    print(f"charged            : {result.included_readings:,}")
    print(f"excluded           : {result.excluded_readings:,}")
    for reason, count in sorted(result.reasons.items(), key=lambda kv: -kv[1]):
        print(f"    {reason:<26} {count:,}")
    print(f"reconciles         : {result.reconciles}")
    print(
        f"scenario charge    : GBP {result.total_energy_charge_gbp_exact} (exact, unrounded)"
    )
    print("This is a scenario energy charge under a stated assumption, not a bill.")
    return 0 if result.reconciles else 1


if __name__ == "__main__":
    raise SystemExit(main())
