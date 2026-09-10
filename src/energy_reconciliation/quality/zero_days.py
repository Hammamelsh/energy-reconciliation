"""Whole days of zero recorded consumption: where they are, and nothing about why.

A *zero day* is a **usable** day -- 48 distinct on-grid finite readings, no missing-value
token, no conflicting label, exactly the FORE-001 rule -- whose recorded total is exactly
``0``. An unusable day is not evidence of zero, so it can neither be a zero day nor bridge
two of them. Runs are maximal stretches of consecutive calendar dates that are all zero
days; a run *touches an edge* when it starts on the household's first usable date or ends
on its last, because a run at the edge of what was loaded may continue outside it.

Contract: ``docs/tickets/ANL-004-zero-days.md``. Results: ``docs/anl-004-zero-days.md``.
The cause of a zero day is not established from readings and is not inferred here.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from ..forecast.dataset import DayRecord, daily_records, usable_days_digest

#: Run-length buckets, fixed before the data was queried (ANL-004 contract).
BUCKETS: Final[tuple[tuple[str, int, int | None], ...]] = (
    ("1", 1, 1),
    ("2-6", 2, 6),
    ("7-27", 7, 27),
    ("28+", 28, None),
)

ZERO: Final[Decimal] = Decimal(0)


@dataclass(frozen=True, slots=True)
class ZeroRun:
    """One maximal run of consecutive zero days for one household."""

    household_id: str
    start: date
    end: date
    days: int
    touches_first_usable: bool
    touches_last_usable: bool

    @property
    def touches_edge(self) -> bool:
        return self.touches_first_usable or self.touches_last_usable

    @property
    def bucket(self) -> str:
        return bucket_of(self.days)


@dataclass(frozen=True, slots=True)
class HouseholdZeroDays:
    household_id: str
    usable_days: int
    zero_days: int
    runs: int
    longest_run_days: int
    zero_day_share: str  # exact ratio as text, e.g. "0.0123"; None-free by construction


def bucket_of(days: int) -> str:
    for label, low, high in BUCKETS:
        if days >= low and (high is None or days <= high):
            return label
    raise ValueError(f"run length {days} fits no bucket")  # pragma: no cover


def zero_runs(records: dict[str, list[DayRecord]]) -> list[ZeroRun]:
    """Every maximal run of consecutive zero days, per household, in date order."""
    out: list[ZeroRun] = []
    for household, days in records.items():
        usable = sorted((d for d in days if d.usable), key=lambda d: d.source_date)
        if not usable:
            continue
        first, last = usable[0].source_date, usable[-1].source_date
        zero_dates = [d.source_date for d in usable if d.kwh == ZERO]
        run_start: date | None = None
        previous: date | None = None
        for day in zero_dates:
            if run_start is None:
                run_start = day
            elif previous is not None and day != previous + timedelta(days=1):
                out.append(_run(household, run_start, previous, first, last))
                run_start = day
            previous = day
        if run_start is not None and previous is not None:
            out.append(_run(household, run_start, previous, first, last))
    return out


def _run(household: str, start: date, end: date, first: date, last: date) -> ZeroRun:
    return ZeroRun(
        household_id=household,
        start=start,
        end=end,
        days=(end - start).days + 1,
        touches_first_usable=start == first,
        touches_last_usable=end == last,
    )


def per_household(
    records: dict[str, list[DayRecord]], runs: list[ZeroRun]
) -> list[HouseholdZeroDays]:
    by_household: dict[str, list[ZeroRun]] = {}
    for run in runs:
        by_household.setdefault(run.household_id, []).append(run)
    rows: list[HouseholdZeroDays] = []
    for household, days in sorted(records.items()):
        usable = sum(1 for d in days if d.usable)
        mine = by_household.get(household, [])
        zero = sum(r.days for r in mine)
        share = (Decimal(zero) / Decimal(usable)) if usable else Decimal(0)
        rows.append(
            HouseholdZeroDays(
                household_id=household,
                usable_days=usable,
                zero_days=zero,
                runs=len(mine),
                longest_run_days=max((r.days for r in mine), default=0),
                zero_day_share=f"{share:.4f}",
            )
        )
    return rows


def summarise(records: dict[str, list[DayRecord]]) -> dict:
    """The full report as a JSON-ready dict. Reconciliation is asserted, not assumed."""
    runs = zero_runs(records)
    households = per_household(records, runs)
    zero_total = sum(r.days for r in runs)
    assert zero_total == sum(h.zero_days for h in households), "runs vs households"
    assert zero_total == sum(
        1 for days in records.values() for d in days if d.usable and d.kwh == ZERO
    ), "runs vs direct count"
    buckets = {label: 0 for label, _, _ in BUCKETS}
    bucket_days = {label: 0 for label, _, _ in BUCKETS}
    for r in runs:
        buckets[r.bucket] += 1
        bucket_days[r.bucket] += r.days
    edge = [r for r in runs if r.touches_edge]
    longest = max(runs, key=lambda r: (r.days, r.household_id), default=None)
    return {
        "definition": "anl-004-zero-days-1",
        "usable_days_digest": usable_days_digest(records),
        "households": len(records),
        "households_with_zero_days": sum(1 for h in households if h.zero_days),
        "usable_days": sum(h.usable_days for h in households),
        "zero_days": zero_total,
        "runs": len(runs),
        "runs_by_length": buckets,
        "zero_days_by_run_length": bucket_days,
        "runs_touching_an_edge": len(edge),
        "zero_days_in_edge_runs": sum(r.days for r in edge),
        "runs_touching_first_usable": sum(1 for r in runs if r.touches_first_usable),
        "runs_touching_last_usable": sum(1 for r in runs if r.touches_last_usable),
        "longest_run": _json_run(longest) if longest else None,
        "runs_of_28_days_or_more": [_json_run(r) for r in runs if r.days >= 28],
        "per_household": [asdict(h) for h in households],
    }


def _json_run(run: ZeroRun) -> dict:
    d = asdict(run)
    d["start"], d["end"] = run.start.isoformat(), run.end.isoformat()
    return d


def render(report: dict) -> str:
    """The report as text. Every line is a count; nothing here says why."""
    lines = [
        "ANL-004 whole zero days -- usable days whose 48 readings are all exactly 0",
        f"  data          : usable-days digest {report['usable_days_digest'][:16]}…",
        (
            f"  households    : {report['households']} loaded, "
            f"{report['households_with_zero_days']} with at least one zero day"
        ),
        f"  usable days   : {report['usable_days']:,}",
        f"  zero days     : {report['zero_days']:,} in {report['runs']} runs",
        "  runs by length: "
        + ", ".join(
            f"{k}: {v} runs / {report['zero_days_by_run_length'][k]} days"
            for k, v in report["runs_by_length"].items()
        ),
        (
            f"  at an edge    : {report['runs_touching_an_edge']} runs "
            f"({report['zero_days_in_edge_runs']} days) start on a household's first "
            f"usable date or end on its last; the rest are bounded by non-zero usable days"
        ),
    ]
    if report["longest_run"]:
        r = report["longest_run"]
        lines.append(
            f"  longest run   : {r['days']} days, {r['household_id']}, "
            f"{r['start']} to {r['end']}"
            + (
                " (touches an edge)"
                if r["touches_first_usable"] or r["touches_last_usable"]
                else ""
            )
        )
    lines.append("  cause         : not established from readings; not inferred here")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zero-day-runs",
        description=(
            "Count whole days of zero recorded consumption in a warehouse: per household, "
            "in runs, and relative to each household's recorded span. Read-only. Says "
            "nothing about why."
        ),
    )
    parser.add_argument(
        "--database", type=Path, default=Path("data/warehouse/energy.duckdb")
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the full JSON report here (names household ids; keep it out of git)",
    )
    args = parser.parse_args(argv)
    if not args.database.exists():
        print(f"zero-day-runs: no warehouse at {args.database}", file=sys.stderr)
        return 2
    report = summarise(daily_records(args.database))
    print(render(report))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=1))
        print(f"  report        : {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
