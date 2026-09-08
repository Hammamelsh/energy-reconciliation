"""The daily series the experiment forecasts, and the rules that decide what is usable.

The prediction target
---------------------

**The sum of a household's recorded half-hourly consumption over one source date, in
kWh.** "Source date" is the date part of the timestamp label exactly as the source wrote
it. Grouping by it is a grouping, **not** a claim:

- it is **not** a local calendar day -- the timezone convention is unresolved (AQ-01);
- it is **not** a settlement day;
- a date carrying 48 labels is **not** proof that the meter covered the whole day, only
  that all 48 nominal half-hour labels carried a reading.

Eligibility, decided before any forecast was run
------------------------------------------------

A **usable day** for a household is one where all of the following hold:

1. exactly ``EXPECTED_INTERVALS`` (48) distinct on-grid labels carry a finite value --
   the full nominal grid, observed;
2. no missing-value token (``Null``) is recorded on that date;
3. no label on that date carries disagreeing readings, so no total is withheld.

Off-grid observations on the date are permitted and counted: policy already excludes them
from the half-hour total, and their presence does not make the grid total unusable.

Anything else is **not usable**, and is never repaired. Missing observations are not
filled with zero, absent dates are not bridged, and a partially observed date is never
treated as a whole one -- it is simply unavailable, and every prediction that would have
depended on it is excluded with a reason.

A household is eligible when it has one **contiguous run** of usable days at least
``MIN_RUN_DAYS`` long. Households are selected by that rule and by household id,
**never** by how well anything forecasts them.

**Contiguity is a benchmark choice, not a correctness requirement.** Lag lookup is keyed
by date, not by row position: a model asks for ``target - 7 days`` and receives that
date's value or nothing. A hole therefore never shifts what "seven days earlier" means;
it makes the lookup return nothing, and the model declines. Contiguity is imposed so that
every household contributes a dense frame of the same shape and the warm-up, development
and holdout boundaries are well defined in calendar days -- which keeps the model
comparison from being confounded by differing decline rates. Relaxing it is a separate
experiment (I-08 in ``docs/ideas.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from ..ingest.warehouse import connect
from ..policy import FINITE, GRID, SIGNATURE

#: A source date carries 48 nominal half-hour labels, 00:00 to 23:30. Measured, not
#: assumed: the loaded members contain exactly 48 distinct times of day on the grid.
EXPECTED_INTERVALS: Final[int] = 48

#: Enough contiguous usable days for a 28-day model warm-up, weekly rolling origins and
#: an untouched 28-day holdout, with room to spare. Chosen from the data's shape before
#: any model was run: 73 of 83 loaded households have a run of at least 180 days.
MIN_RUN_DAYS: Final[int] = 168

_DAILY_SQL: Final[str] = f"""
WITH shape AS (
    SELECT household_id,
           CAST(observed_at_naive AS DATE) AS source_date,
           COUNT(DISTINCT source_timestamp_text)
               FILTER (WHERE {GRID} AND value_category = '{FINITE}')      AS grid_intervals,
           COUNT(*) FILTER (WHERE value_category <> '{FINITE}')           AS non_numeric_rows,
           COUNT(*) FILTER (WHERE NOT {GRID})                             AS off_grid_rows
    FROM readings WHERE {{household_filter}} GROUP BY 1, 2
),
conflicting AS (
    SELECT DISTINCT household_id, CAST(observed_at_naive AS DATE) AS source_date
    FROM (
        SELECT household_id, source_timestamp_text,
               MIN(CAST(observed_at_naive AS DATE)) AS observed_at_naive
        FROM readings WHERE {{household_filter}}
        GROUP BY household_id, source_timestamp_text
        HAVING COUNT(DISTINCT {SIGNATURE}) > 1
    )
),
distinct_values AS (
    SELECT DISTINCT household_id, CAST(observed_at_naive AS DATE) AS source_date,
           source_timestamp_text, consumption_kwh
    FROM readings WHERE {{household_filter}} AND {GRID} AND value_category = '{FINITE}'
),
totals AS (
    SELECT household_id, source_date, SUM(consumption_kwh) AS kwh
    FROM distinct_values GROUP BY 1, 2
)
SELECT s.household_id,
       s.source_date,
       CAST(t.kwh AS VARCHAR)                       AS kwh_exact,
       s.grid_intervals,
       s.non_numeric_rows,
       s.off_grid_rows,
       (c.household_id IS NOT NULL)                 AS has_conflict
FROM shape s
LEFT JOIN totals t USING (household_id, source_date)
LEFT JOIN conflicting c USING (household_id, source_date)
ORDER BY s.household_id, s.source_date
"""


@dataclass(frozen=True, slots=True)
class DayRecord:
    """One household-day, with everything the eligibility rules need."""

    source_date: date
    kwh: Decimal | None
    grid_intervals: int
    non_numeric_rows: int
    off_grid_rows: int
    has_conflict: bool

    @property
    def usable(self) -> bool:
        return (
            self.grid_intervals == EXPECTED_INTERVALS
            and self.non_numeric_rows == 0
            and not self.has_conflict
            and self.kwh is not None
        )

    @property
    def unusable_reason(self) -> str | None:
        if self.has_conflict:
            return "conflicting_readings"
        if self.non_numeric_rows:
            return "missing_value_recorded"
        if self.grid_intervals != EXPECTED_INTERVALS:
            return f"partial_grid_{self.grid_intervals}_of_{EXPECTED_INTERVALS}"
        if self.kwh is None:
            return "no_total"
        return None


@dataclass(frozen=True, slots=True)
class HouseholdSeries:
    """A household's longest contiguous run of usable days, and nothing outside it."""

    household_id: str
    run_start: date
    run_end: date
    values: dict[date, Decimal]

    @property
    def length(self) -> int:
        return (self.run_end - self.run_start).days + 1

    def at(self, day: date) -> Decimal | None:
        """The recorded total for a date, or None. **Never a substituted zero.**"""
        return self.values.get(day)

    def history_upto(self, origin: date) -> list[date]:
        """Dates available at a forecast origin: run start to origin, inclusive."""
        if origin < self.run_start:
            return []
        last = min(origin, self.run_end)
        n = (last - self.run_start).days + 1
        return [self.run_start + timedelta(days=i) for i in range(n)]


def daily_records(
    database: Path, household: str | None = None
) -> dict[str, list[DayRecord]]:
    """Every household-day in the warehouse, with its usability evidence.

    ``household`` narrows the scan to one household -- the same rules applied to the
    same rows, without reading three million of them. The filter is a bound parameter
    substituted into the one template, so the scoped query cannot drift from the full one.
    """
    scope = "household_id = ?" if household is not None else "TRUE"
    sql = _DAILY_SQL.replace("{household_filter}", scope)
    params: list[str] = [household] * 3 if household is not None else []
    con = connect(database, read_only=True)
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    out: dict[str, list[DayRecord]] = {}
    for name, day, kwh, intervals, non_numeric, off_grid, conflict in rows:
        out.setdefault(name, []).append(
            DayRecord(
                source_date=day,
                kwh=Decimal(kwh) if kwh is not None else None,
                grid_intervals=int(intervals),
                non_numeric_rows=int(non_numeric),
                off_grid_rows=int(off_grid),
                has_conflict=bool(conflict),
            )
        )
    return out


def longest_usable_run(records: list[DayRecord]) -> tuple[date, date] | None:
    """The longest run of consecutive **calendar-adjacent** usable days.

    A gap of even one date ends a run. That is deliberate, but not because a gap would
    corrupt the lag: lookups are date-keyed, so an absent date yields nothing and the
    model declines. It is so that each household contributes one dense window of the same
    shape, with split boundaries well defined in calendar days.
    """
    usable = sorted(r.source_date for r in records if r.usable)
    if not usable:
        return None
    best = start = prev = usable[0]
    best_start, best_len, run_len = start, 1, 1
    for day in usable[1:]:
        if day == prev + timedelta(days=1):
            run_len += 1
        else:
            start, run_len = day, 1
        if run_len > best_len:
            best_len, best_start, best = run_len, start, day
        prev = day
    return best_start, best


def eligible_series(
    database: Path, min_run_days: int = MIN_RUN_DAYS, limit: int | None = None
) -> list[HouseholdSeries]:
    """Households with a long enough contiguous usable run, ordered by household id.

    ``limit`` bounds the experiment's size. It takes the **first** qualifying households
    by id -- a deterministic rule that has nothing to do with how well any model does on
    them.
    """
    series: list[HouseholdSeries] = []
    for household, records in sorted(daily_records(database).items()):
        run = longest_usable_run(records)
        if run is None:
            continue
        start, end = run
        if (end - start).days + 1 < min_run_days:
            continue
        values = {
            r.source_date: r.kwh
            for r in records
            if r.usable and start <= r.source_date <= end and r.kwh is not None
        }
        series.append(HouseholdSeries(household, start, end, values))
    return series[:limit] if limit is not None else series


def feasibility(database: Path) -> dict:
    """What the loaded data can and cannot support, measured before any modelling."""
    records = daily_records(database)
    total_days = sum(len(v) for v in records.values())
    usable_days = sum(1 for v in records.values() for r in v if r.usable)
    reasons: dict[str, int] = {}
    for rows in records.values():
        for r in rows:
            if not r.usable:
                reasons[r.unusable_reason or "unknown"] = (
                    reasons.get(r.unusable_reason or "unknown", 0) + 1
                )
    runs = {h: longest_usable_run(v) for h, v in records.items()}
    lengths = sorted((e - s).days + 1 for run in runs.values() if run for s, e in [run])
    return {
        "households": len(records),
        "household_days": total_days,
        "usable_household_days": usable_days,
        "unusable_by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "off_grid_rows": sum(r.off_grid_rows for v in records.values() for r in v),
        "missing_value_rows": sum(
            r.non_numeric_rows for v in records.values() for r in v
        ),
        "longest_run_days": {
            "min": lengths[0] if lengths else 0,
            "median": lengths[len(lengths) // 2] if lengths else 0,
            "max": lengths[-1] if lengths else 0,
        },
        "eligible_households": sum(1 for n in lengths if n >= MIN_RUN_DAYS),
        "min_run_days": MIN_RUN_DAYS,
        "expected_intervals": EXPECTED_INTERVALS,
        "timestamp_convention": (
            "UNRESOLVED. Source dates group timestamp labels as written. Their "
            "correspondence to local calendar days is not established, they are not "
            "settlement days, and a 48-label date is not proof "
            "that the meter covered the whole day. A daylight-saving transition, if the "
            "labels are local time, would make one date 46 or 50 half hours long; such "
            "dates fail the 48-interval rule and are excluded rather than adjusted."
        ),
    }


def series_for(
    database: Path, household: str, min_run_days: int = MIN_RUN_DAYS
) -> HouseholdSeries | None:
    """One household's longest contiguous usable run, or None if it is too short."""
    records = daily_records(database, household).get(household, [])
    run = longest_usable_run(records)
    if run is None:
        return None
    start, end = run
    if (end - start).days + 1 < min_run_days:
        return None
    values = {
        r.source_date: r.kwh
        for r in records
        if r.usable and start <= r.source_date <= end and r.kwh is not None
    }
    return HouseholdSeries(household, start, end, values)
