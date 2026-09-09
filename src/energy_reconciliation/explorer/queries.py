"""Data access for the explorer. No Streamlit here, so every function is testable.

Nothing here resolves a conflict, fills a gap, or converts a timestamp. It reports
what was recorded and says plainly when a figure cannot be given.

**One selection scope.** Every figure for a household is computed for the same
household and the same source-date range. ``start``/``end`` of ``None`` means the whole
loaded history, and callers must label that scope when they use it.

**Three kinds of repetition at one household + source timestamp label, kept apart:**

- *Exact duplicate rows* -- identical raw text. Collapsed everywhere; the number
  collapsed is always reported (``duplicates_removed``).
- *Equivalent representations* -- different raw texts, one numeric value
  (``' 0.5 '`` and ``' 0.50 '``). Both rows are kept as evidence; the value enters a
  total **once**; they are not a conflict.
- *Conflicts* -- more than one numeric value, or a number beside a non-numeric token
  such as ``Null``. A total containing one is withheld. **This is our analytical
  policy, not a publisher rule**: the source does not say what a ``Null`` beside a
  number means, and nothing here infers that the meter produced either row.

**Which timestamps each diagnostic uses.** *Half-hour analytical totals* -- the period
total, daily totals and the detail line -- use only readings **on** the half-hour grid,
each distinct (label, value) once. Off-grid observations are excluded from those totals
under this policy, because they do not belong to the half-hourly series; they remain
counted, listed with provenance, and plotted separately. *Counts of what was recorded*
(``available_readings``, rows, missing values) include every row, grid or not. Step
diagnostics (gaps) use distinct grid labels only. The profiler's descriptive statistics
over source values are a different instrument and are not affected by this policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..ingest.warehouse import connect
from ..policy import DUPLICATE_POLICY, EXPECTED_STEP_SECONDS
from ..policy import GRID as _GRID
from ..policy import SIGNATURE as _SIGNATURE
from ..policy import TEXT_KEY as _TEXT_KEY

# The duplicate, conflict, missing-value and off-grid rules are defined once, in
# ``energy_reconciliation.policy``, and imported here. The tariff models import the
# same definitions, so the two never drift apart.
__all__ = ["DUPLICATE_POLICY", "EXPECTED_STEP_SECONDS"]


def _scope(household: str, start: date | None, end: date | None) -> tuple[str, list]:
    where, params = "household_id = ?", [household]
    if start is not None and end is not None:
        where += " AND CAST(observed_at_naive AS DATE) BETWEEN ? AND ?"
        params += [start, end]
    return where, params


def _con(database: Path):
    return connect(database, read_only=True)


# ------------------------------------------------------------------ catalogue
@dataclass(frozen=True, slots=True)
class LoadedSource:
    archive_name: str
    member_name: str
    records_read: int
    records_published: int
    records_rejected: int
    loaded_at_utc: str
    status: str


def loaded_sources(database: Path) -> list[LoadedSource]:
    con = _con(database)
    try:
        rows = con.execute(
            "SELECT archive_name, member_name, records_read, records_published, "
            "records_rejected, CAST(loaded_at_utc AS VARCHAR), status "
            "FROM load_registry ORDER BY loaded_at_utc DESC"
        ).fetchall()
    finally:
        con.close()
    return [LoadedSource(*r) for r in rows]


@dataclass(frozen=True, slots=True)
class DatasetSummary:
    """What one warehouse file holds, in the terms a picker needs.

    ``all_demo`` is a property of the data, not of the file name: the synthetic archive
    writes household ids beginning ``DEMO``, and no real household id does.
    """

    households: int
    members: tuple[str, ...]
    all_demo: bool


def dataset_summary(database: Path) -> DatasetSummary:
    """One read of a warehouse: how many households, which source files, demo or not."""
    con = _con(database)
    try:
        total, demo = con.execute(
            "SELECT COUNT(DISTINCT household_id), "
            "COUNT(DISTINCT household_id) FILTER (WHERE household_id LIKE 'DEMO%') "
            "FROM readings"
        ).fetchone()
        members = tuple(
            r[0].split("/")[-1]
            for r in con.execute(
                "SELECT DISTINCT member_name FROM load_registry WHERE status = 'published' "
                "ORDER BY member_name"
            ).fetchall()
        )
    finally:
        con.close()
    return DatasetSummary(
        households=int(total),
        members=members,
        all_demo=bool(total) and total == demo,
    )


def dataset_label(database: Path) -> str:
    """A friendly name derived from the contents, not the filename.

    Kept for callers that want a content-derived description of any warehouse. The
    dashboard's picker uses :mod:`explorer.datasets` instead, which adds the *role* a
    file plays -- something no amount of reading its contents can establish.
    """
    summary = dataset_summary(database)
    if summary.all_demo:
        return "Synthetic demo (invented data)"
    tags = ", ".join(
        m.replace("LCL-June2015v2_", "member ").replace(".csv", "")
        for m in summary.members
    )
    return f"Low Carbon London sample ({tags})" if tags else "Low Carbon London sample"


def households(database: Path) -> list[str]:
    con = _con(database)
    try:
        return [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT household_id FROM readings ORDER BY household_id"
            ).fetchall()
        ]
    finally:
        con.close()


def date_bounds(database: Path, household: str) -> tuple[date, date] | None:
    con = _con(database)
    try:
        row = con.execute(
            "SELECT MIN(CAST(observed_at_naive AS DATE)), MAX(CAST(observed_at_naive AS DATE)) "
            "FROM readings WHERE household_id = ?",
            [household],
        ).fetchone()
    finally:
        con.close()
    return (row[0], row[1]) if row and row[0] is not None else None


def preset_window(
    database: Path, household: str, days: int
) -> tuple[date, date] | None:
    """The most recent ``days`` of THIS household's data, ending on its last date."""
    bounds = date_bounds(database, household)
    if bounds is None:
        return None
    first, last = bounds
    return max(first, last - timedelta(days=days - 1)), last


def default_window(database: Path, household: str, days: int = 14):
    return preset_window(database, household, days)


# ------------------------------------------------- agreement at one timestamp
def label_agreement(
    database: Path, household: str, start: date | None = None, end: date | None = None
) -> pd.DataFrame:
    """Every source timestamp label carrying more than one row, classified.

    kind is ``exact_duplicate`` (one raw text), ``equivalent_representation``
    (several texts, one signature) or ``conflict`` (several signatures).
    """
    where, params = _scope(household, start, end)
    con = _con(database)
    try:
        frame = con.execute(
            f"""
            SELECT source_timestamp_text,
                   COUNT(*)                                  AS rows_raw,
                   COUNT(DISTINCT consumption_raw_text)      AS distinct_texts,
                   COUNT(DISTINCT {_SIGNATURE})              AS distinct_signatures,
                   COUNT(DISTINCT member_name)               AS members_involved,
                   MIN(member_name)                          AS first_member,
                   MIN(source_record_no)                     AS first_record_no,
                   STRING_AGG(DISTINCT consumption_raw_text, ' | ') AS texts
            FROM readings WHERE {where}
            GROUP BY source_timestamp_text HAVING COUNT(*) > 1
            ORDER BY source_timestamp_text
            """,
            params,
        ).df()
    finally:
        con.close()
    if frame.empty:
        frame["kind"] = pd.Series(dtype="object")
        return frame
    frame["kind"] = [
        "conflict"
        if sig > 1
        else ("equivalent_representation" if txt > 1 else "exact_duplicate")
        for sig, txt in zip(
            frame["distinct_signatures"], frame["distinct_texts"], strict=True
        )
    ]
    return frame


def conflicting_keys(
    database: Path, household: str, start: date | None = None, end: date | None = None
) -> pd.DataFrame:
    """Labels whose readings do not agree on one meaning. These withhold totals."""
    frame = label_agreement(database, household, start, end)
    out = frame[frame["kind"] == "conflict"].copy()
    out.insert(0, "household_id", household)
    return out.rename(
        columns={"rows_raw": "rows_at_key", "distinct_signatures": "distinct_values"}
    ).reset_index(drop=True)


def equivalent_representations(
    database: Path, household: str, start: date | None = None, end: date | None = None
) -> pd.DataFrame:
    """Labels with several raw texts but one numeric value. Kept as evidence, counted once."""
    frame = label_agreement(database, household, start, end)
    return frame[frame["kind"] == "equivalent_representation"].reset_index(drop=True)


# ----------------------------------------------------------------- the steps
def step_anomalies(
    database: Path, household: str, start: date | None = None, end: date | None = None
) -> dict[str, pd.DataFrame]:
    """Gaps between consecutive distinct GRID timestamp labels, plus off-grid rows.

    Steps are taken over distinct labels, so no amount of repetition at one label
    can create or hide a step. Labels off the half-hour grid are excluded from the
    sequence and listed under ``off_grid`` instead: they are not part of the
    half-hourly series and would otherwise manufacture spurious short steps.

    Steps are computed only between labels inside the selection. A step that would
    cross the selection edge is not counted, because the reading on the far side is
    outside scope; nothing outside the selection is ever read for context.

    Each gap is one row, attributed to the source date of ``to_timestamp`` (the first
    reading after it). An overnight gap therefore belongs to the later date, and once.
    """
    where, params = _scope(household, start, end)
    con = _con(database)
    try:
        gaps = con.execute(
            f"""
            WITH labels AS (
                SELECT DISTINCT observed_at_naive AS ts
                FROM readings WHERE {where} AND {_GRID}
            ),
            ordered AS (
                SELECT ts, LAG(ts) OVER (ORDER BY ts) AS prev FROM labels
            )
            SELECT prev AS from_timestamp, ts AS to_timestamp,
                   CAST(date_diff('second', prev, ts) AS BIGINT) AS step_seconds,
                   CAST(ts AS DATE) AS attributed_date
            FROM ordered
            WHERE prev IS NOT NULL AND date_diff('second', prev, ts) > {EXPECTED_STEP_SECONDS}
            ORDER BY ts
            """,
            params,
        ).df()
        off_grid = con.execute(
            f"""
            SELECT DISTINCT source_timestamp_text, observed_at_naive, value_category
            FROM readings WHERE {where} AND NOT {_GRID}
            ORDER BY observed_at_naive
            """,
            params,
        ).df()
    finally:
        con.close()
    return {"gaps": gaps, "off_grid": off_grid}


# ---------------------------------------------------------- quality counters
@dataclass(frozen=True, slots=True)
class QualitySummary:
    scope: str
    start: date | None
    end: date | None
    observed_records: int
    distinct_readings: int
    duplicates_removed: int
    equivalent_representations: int
    finite_values: int
    null_tokens: int
    other_non_numeric: int
    zero_values: int
    candidate_key_collisions: int
    exact_duplicate_extras: int
    conflicting_keys: int
    repeated_timestamps: int
    gaps: int
    off_grid_observations: int
    members: tuple[str, ...]


def quality_summary(
    database: Path, household: str, start: date | None = None, end: date | None = None
) -> QualitySummary:
    where, params = _scope(household, start, end)
    con = _con(database)
    try:
        base = con.execute(
            f"""
            SELECT COUNT(*),
                   SUM(CASE WHEN value_category = 'finite_numeric' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN value_category = 'null_token' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN value_category NOT IN ('finite_numeric','null_token')
                            THEN 1 ELSE 0 END),
                   SUM(CASE WHEN consumption_kwh = 0 THEN 1 ELSE 0 END)
            FROM readings WHERE {where}
            """,
            params,
        ).fetchone()
        distinct = con.execute(
            f"SELECT COUNT(*) FROM (SELECT DISTINCT {_TEXT_KEY} FROM readings WHERE {where})",
            params,
        ).fetchone()[0]
        members = tuple(
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT member_name FROM readings WHERE {where} ORDER BY 1",
                params,
            ).fetchall()
        )
    finally:
        con.close()
    agreement = label_agreement(database, household, start, end)
    steps = step_anomalies(database, household, start, end)
    observed = int(base[0] or 0)
    kinds = agreement["kind"].value_counts() if not agreement.empty else {}
    return QualitySummary(
        scope="selected period" if start is not None else "whole loaded history",
        start=start,
        end=end,
        observed_records=observed,
        distinct_readings=int(distinct),
        duplicates_removed=observed - int(distinct),
        equivalent_representations=int(kinds.get("equivalent_representation", 0)),
        finite_values=int(base[1] or 0),
        null_tokens=int(base[2] or 0),
        other_non_numeric=int(base[3] or 0),
        zero_values=int(base[4] or 0),
        candidate_key_collisions=len(agreement),
        exact_duplicate_extras=observed - int(distinct),
        conflicting_keys=int(kinds.get("conflict", 0)),
        repeated_timestamps=int(
            kinds.get("conflict", 0) + kinds.get("equivalent_representation", 0)
        ),
        gaps=len(steps["gaps"]),
        off_grid_observations=len(steps["off_grid"]),
        members=members,
    )


# ----------------------------------------------------------------- the period
@dataclass(frozen=True, slots=True)
class PeriodSummary:
    start: date
    end: date
    total_kwh: Decimal | None
    contributing_readings: int
    available_readings: int
    duplicates_removed: int
    equivalent_representations: int
    null_values: int
    gaps: int
    off_grid_observations: int
    conflicts_in_period: int
    days_with_rows: int
    days_without_rows: int
    boundary_days: tuple[date, ...]
    withheld_reason: str | None
    duplicate_policy: str = DUPLICATE_POLICY

    @property
    def issues_for_review(self) -> int:
        """Items for review: missing values + gaps + conflicting timestamps + off-grid
        observations, within this period.

        A **sum of items across four categories**, not a count of unique records: one
        row can be counted under more than one heading (a ``Null`` at a conflicting
        label, for instance). Off-grid observations are included so that readings
        excluded from the half-hour totals can never disappear from view. Exact
        duplicates and equivalent representations are not items: the policy resolves
        them and reports the counts alongside.
        """
        return (
            self.null_values
            + self.gaps
            + self.conflicts_in_period
            + self.off_grid_observations
        )


@dataclass(frozen=True, slots=True)
class ReviewStatus:
    level: str
    headline: str
    detail: str
    standing_caveat: str = (
        "Boundary coverage and clock semantics remain unresolved: whether the first "
        "and last days are complete, and what timezone or interval convention the "
        "timestamps use, is not established from the sources reviewed."
    )


def review_status(period: PeriodSummary) -> ReviewStatus:
    """Never says "no concerns". Always keeps resolved repetition visible."""
    resolved = []
    if period.duplicates_removed:
        resolved.append(
            f"{period.duplicates_removed} repeated identical reading(s) collapsed"
        )
    if period.equivalent_representations:
        resolved.append(
            f"{period.equivalent_representations} timestamp(s) with equivalent "
            "representations of one value, counted once"
        )
    tail = (" " + "; ".join(resolved).capitalize() + ".") if resolved else ""
    if period.conflicts_in_period:
        return ReviewStatus(
            "blocking",
            f"Conflicting readings on {period.conflicts_in_period} timestamp(s) — total withheld",
            "The source carries different values for the same household and source "
            "timestamp. A total would mean choosing between them, which is an "
            "unresolved decision." + tail,
        )
    if period.issues_for_review:
        parts = []
        if period.null_values:
            parts.append(f"{period.null_values} missing value(s)")
        if period.gaps:
            parts.append(f"{period.gaps} gap(s) between consecutive grid readings")
        if period.off_grid_observations:
            parts.append(
                f"{period.off_grid_observations} off-grid observation(s), excluded "
                "from half-hour totals"
            )
        return ReviewStatus(
            "review",
            f"{period.issues_for_review} item(s) for review",
            ", ".join(parts).capitalize() + ". The total covers only what was "
            "recorded; a smaller total does not by itself mean less electricity was "
            "used." + tail,
        )
    return ReviewStatus(
        "clear",
        "No detected conflicts or internal gaps",
        "Every consecutive pair of distinct grid readings in this period is half an "
        "hour apart, with no missing values." + tail,
    )


def _exact_total(database: Path, household: str, start: date, end: date) -> Decimal:
    """Sum over distinct (label, value) of finite readings -- each meaning once.

    Computed in the database as Decimal; never from a chart frame.
    """
    where, params = _scope(household, start, end)
    con = _con(database)
    try:
        value = con.execute(
            f"""
            SELECT SUM(consumption_kwh) FROM (
                SELECT DISTINCT source_timestamp_text, consumption_kwh
                FROM readings WHERE {where} AND value_category = 'finite_numeric'
                  AND {_GRID})
            """,
            params,
        ).fetchone()[0]
    finally:
        con.close()
    return Decimal(str(value)) if value is not None else Decimal(0)


def daily_totals(
    database: Path, household: str, start: date, end: date
) -> pd.DataFrame:
    """One row per source date in scope, with the total withheld on conflict days.

    Grouped by the date in the source timestamp -- not a settlement day, not a
    local calendar day. ``recorded_kwh`` is NULL and ``total_status`` is ``withheld``
    on any day holding a conflicting label; the readings that exist are still counted
    in ``available_readings``. A day inside the recorded span with no rows appears
    with ``total_status`` ``none``. Days outside the span are not invented.

    Totals use every finite reading, grid or not, each distinct (label, value) once.
    ``gaps_observed`` uses grid labels only and attributes each gap to the date of
    the reading after it, so summing this column over days equals the period count.
    """
    where, params = _scope(household, start, end)
    con = _con(database)
    try:
        frame = con.execute(
            f"""
            WITH raw AS (
                SELECT CAST(observed_at_naive AS DATE) AS source_date,
                       COUNT(*) AS rows_raw,
                       COUNT(DISTINCT consumption_raw_text || '|' || source_timestamp_text)
                           AS rows_distinct,
                       SUM(CASE WHEN value_category = 'null_token' THEN 1 ELSE 0 END)
                           AS missing_values,
                       SUM(CASE WHEN NOT {_GRID} THEN 1 ELSE 0 END) AS off_grid_rows
                FROM readings WHERE {where} GROUP BY 1
            ),
            vals AS (
                SELECT DISTINCT CAST(observed_at_naive AS DATE) AS source_date,
                       source_timestamp_text, consumption_kwh, {_GRID} AS on_grid
                FROM readings WHERE {where} AND value_category = 'finite_numeric'
            ),
            perday AS (
                SELECT source_date,
                       SUM(CASE WHEN on_grid THEN consumption_kwh END) AS recorded_kwh,
                       COUNT(*) AS available_readings,
                       SUM(CASE WHEN on_grid THEN 1 ELSE 0 END) AS grid_readings
                FROM vals GROUP BY 1
            )
            SELECT raw.source_date,
                   perday.recorded_kwh,
                   CAST(perday.recorded_kwh AS VARCHAR) AS recorded_kwh_text,
                   COALESCE(perday.available_readings, 0) AS available_readings,
                   COALESCE(perday.grid_readings, 0) AS grid_readings,
                   raw.missing_values,
                   raw.rows_raw - raw.rows_distinct AS duplicates_removed,
                   raw.off_grid_rows
            FROM raw LEFT JOIN perday USING (source_date) ORDER BY 1
            """,
            params + params,
        ).df()
    finally:
        con.close()

    bounds = date_bounds(database, household)
    if bounds is None or frame.empty and (start > bounds[1] or end < bounds[0]):
        return frame.iloc[0:0]
    first, last = bounds
    lo, hi = max(start, first), min(end, last)
    if lo > hi:
        return frame.iloc[0:0]

    frame["source_date"] = pd.to_datetime(frame["source_date"]).dt.date
    span = pd.DataFrame(
        {"source_date": [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]}
    )
    frame = span.merge(frame, on="source_date", how="left")
    for col in (
        "available_readings",
        "grid_readings",
        "missing_values",
        "duplicates_removed",
        "off_grid_rows",
    ):
        frame[col] = frame[col].fillna(0).astype(int)

    agreement = label_agreement(database, household, start, end)
    conflict_dates: set[date] = set()
    equivalent_by_day: dict[date, int] = {}
    if not agreement.empty:
        labelled = agreement.assign(
            d=pd.to_datetime(agreement["source_timestamp_text"], format="mixed").dt.date
        )
        conflict_dates = set(labelled.loc[labelled["kind"] == "conflict", "d"])
        equivalent_by_day = (
            labelled[labelled["kind"] == "equivalent_representation"]
            .groupby("d")
            .size()
            .to_dict()
        )
    gaps = step_anomalies(database, household, start, end)["gaps"]
    gap_by_day = (
        pd.to_datetime(gaps["attributed_date"]).dt.date.value_counts().to_dict()
        if len(gaps)
        else {}
    )

    frame["equivalent_representations"] = [
        int(equivalent_by_day.get(d, 0)) for d in frame["source_date"]
    ]
    frame["gaps_observed"] = [int(gap_by_day.get(d, 0)) for d in frame["source_date"]]
    frame["has_conflict"] = [d in conflict_dates for d in frame["source_date"]]
    frame["is_boundary_day"] = [d in (first, last) for d in frame["source_date"]]

    # A conflict day publishes no total. The value column is emptied so nothing
    # downstream can draw a bar from it; the readings that exist stay visible.
    frame.loc[frame["has_conflict"], ["recorded_kwh", "recorded_kwh_text"]] = [
        None,
        None,
    ]
    frame["recorded_kwh"] = frame["recorded_kwh"].astype("float64")
    frame["recorded_kwh_text"] = [
        ""
        if pd.isna(v) or v in ("", None)
        else format(Decimal(str(v)).normalize(), "f")
        for v in frame["recorded_kwh_text"]
    ]
    has_rows = (frame["available_readings"] + frame["missing_values"]) > 0
    # Published only when an undisputed grid reading exists. A day with rows but no
    # grid reading (only off-grid or Null) has nothing to total, and is not zero.
    frame["total_status"] = [
        "withheld" if c else ("published" if g > 0 else "none")
        for c, g in zip(frame["has_conflict"], frame["grid_readings"], strict=True)
    ]
    frame["contributing_readings"] = [
        0 if st != "published" else g
        for st, g in zip(frame["total_status"], frame["grid_readings"], strict=True)
    ]
    frame["has_rows"] = has_rows

    def status(row) -> str:
        if row["has_conflict"]:
            return "conflicting readings"
        if row["total_status"] == "none":
            return "no readings recorded" if not row["has_rows"] else "for review"
        if row["is_boundary_day"]:
            return "boundary date"
        if row["missing_values"] or row["gaps_observed"]:
            return "for review"
        return "recorded"

    frame["status"] = frame.apply(status, axis=1)
    frame["source_date"] = pd.to_datetime(frame["source_date"])
    return frame


def period_summary(
    database: Path, household: str, start: date, end: date
) -> PeriodSummary:
    quality = quality_summary(database, household, start, end)
    daily = daily_totals(database, household, start, end)
    empty = daily.empty
    days_with = int((daily["total_status"] != "none").sum()) if not empty else 0
    common = {
        "start": start,
        "end": end,
        "available_readings": int(daily["available_readings"].sum())
        if not empty
        else 0,
        "duplicates_removed": quality.duplicates_removed,
        "equivalent_representations": quality.equivalent_representations,
        "null_values": quality.null_tokens,
        "gaps": quality.gaps,
        "off_grid_observations": quality.off_grid_observations,
        "conflicts_in_period": quality.conflicting_keys,
        "days_with_rows": days_with,
        "days_without_rows": int(len(daily) - days_with) if not empty else 0,
        "boundary_days": tuple(
            daily.loc[daily["is_boundary_day"], "source_date"].dt.date
        )
        if not empty
        else (),
    }
    if quality.conflicting_keys:
        return PeriodSummary(
            total_kwh=None,
            contributing_readings=0,
            withheld_reason=(
                f"{quality.conflicting_keys} timestamp(s) in this period carry "
                "disagreeing readings. A total would mean choosing between them, "
                "which is an unresolved decision."
            ),
            **common,
        )
    return PeriodSummary(
        total_kwh=_exact_total(database, household, start, end),
        contributing_readings=int(daily["contributing_readings"].sum())
        if not empty
        else 0,
        withheld_reason=None,
        **common,
    )


# ---------------------------------------------------------------- the detail
@dataclass(frozen=True, slots=True)
class DetailFrames:
    """One day's readings for charting.

    ``series`` holds one point per distinct (label, value) that is NOT in conflict,
    each carrying ``on_half_hour_grid`` so an off-grid point stays distinguishable,
    with a blank ``line_break`` row at every gap and at every conflicting label, so a
    line never passes through a gap or through a disputed timestamp. ``conflicts``
    holds every raw row at a conflicting label, with its member and record number.
    ``off_grid`` holds every raw off-grid row with provenance; such rows are excluded
    from ``series`` and from all half-hour totals under the current policy.
    """

    series: pd.DataFrame
    conflicts: pd.DataFrame
    off_grid: pd.DataFrame


def _with_line_breaks(
    frame: pd.DataFrame, ts_col: str, value_col: str, break_at: set[pd.Timestamp]
) -> pd.DataFrame:
    if frame.empty:
        return frame
    times = pd.to_datetime(frame[ts_col])
    gap_after = times.diff().shift(-1).dt.total_seconds() > EXPECTED_STEP_SECONDS
    rows = [frame]
    if gap_after.any():
        b = frame[gap_after].copy()
        b[ts_col] = times[gap_after] + pd.Timedelta(seconds=1)
        b[value_col] = pd.NA
        b["value_category"] = "line_break"
        rows.append(b)
    for t in sorted(break_at):
        rows.append(
            pd.DataFrame(
                {ts_col: [t], value_col: [pd.NA], "value_category": ["line_break"]}
            )
        )
    return pd.concat(rows, ignore_index=True).sort_values(ts_col).reset_index(drop=True)


def half_hour_detail(database: Path, household: str, day: date) -> DetailFrames:
    where, params = _scope(household, day, day)
    con = _con(database)
    try:
        distinct = con.execute(
            f"""
            SELECT DISTINCT observed_at_naive AS source_timestamp, source_timestamp_text,
                   CAST(consumption_kwh AS DOUBLE) AS recorded_kwh, value_category,
                   on_half_hour_grid
            FROM readings WHERE {where} AND {_GRID}
            ORDER BY observed_at_naive, recorded_kwh
            """,
            params,
        ).df()
        conflict_labels = [
            r[0]
            for r in con.execute(
                f"""
            SELECT source_timestamp_text FROM readings WHERE {where}
            GROUP BY 1 HAVING COUNT(DISTINCT {_SIGNATURE}) > 1
            """,
                params,
            ).fetchall()
        ]
        conflicts = con.execute(
            f"""
            SELECT observed_at_naive AS source_timestamp, source_timestamp_text,
                   consumption_raw_text, CAST(consumption_kwh AS DOUBLE) AS recorded_kwh,
                   value_category, member_name, source_record_no
            FROM readings WHERE {where} AND source_timestamp_text IN (
                SELECT source_timestamp_text FROM readings WHERE {where}
                GROUP BY 1 HAVING COUNT(DISTINCT {_SIGNATURE}) > 1)
            ORDER BY observed_at_naive, source_record_no
            """,
            params + params,
        ).df()
    finally:
        con.close()
    series = distinct[
        ~distinct["source_timestamp_text"].isin(conflict_labels)
    ].reset_index(drop=True)
    break_at = {
        pd.Timestamp(t)
        for t in distinct.loc[
            distinct["source_timestamp_text"].isin(conflict_labels), "source_timestamp"
        ]
    }
    series = _with_line_breaks(series, "source_timestamp", "recorded_kwh", break_at)
    off_grid = _off_grid_rows(database, where, params)
    return DetailFrames(series=series, conflicts=conflicts, off_grid=off_grid)


def _off_grid_rows(database: Path, where: str, params: list) -> pd.DataFrame:
    """Raw off-grid rows in scope, with provenance, for separate plotting."""
    con = _con(database)
    try:
        return con.execute(
            f"""
            SELECT observed_at_naive AS source_timestamp, source_timestamp_text,
                   consumption_raw_text, CAST(consumption_kwh AS DOUBLE) AS recorded_kwh,
                   value_category, member_name, source_record_no
            FROM readings WHERE {where} AND NOT {_GRID}
            ORDER BY observed_at_naive, source_record_no
            """,
            params,
        ).df()
    finally:
        con.close()


def chart_series(
    database: Path, household: str, start: date, end: date
) -> pd.DataFrame:
    where, params = _scope(household, start, end)
    con = _con(database)
    try:
        frame = con.execute(
            f"""
            SELECT DISTINCT observed_at_naive AS source_timestamp,
                   CAST(consumption_kwh AS DOUBLE) AS recorded_kwh, value_category
            FROM readings WHERE {where} ORDER BY 1, 2
            """,
            params,
        ).df()
    finally:
        con.close()
    return _with_line_breaks(frame, "source_timestamp", "recorded_kwh", set())


# --------------------------------------------------------------- raw records
def observations(
    database: Path,
    household: str,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> pd.DataFrame:
    where, params = _scope(household, start, end)
    con = _con(database)
    try:
        return con.execute(
            f"""
            SELECT member_name, source_record_no, source_timestamp_text,
                   consumption_raw_text, value_category, on_half_hour_grid,
                   tariff_group, timezone_status
            FROM readings WHERE {where}
            ORDER BY observed_at_naive, source_record_no LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).df()
    finally:
        con.close()


def observation_count(
    database: Path, household: str, start: date | None = None, end: date | None = None
) -> int:
    where, params = _scope(household, start, end)
    con = _con(database)
    try:
        return con.execute(
            f"SELECT COUNT(*) FROM readings WHERE {where}", params
        ).fetchone()[0]
    finally:
        con.close()
