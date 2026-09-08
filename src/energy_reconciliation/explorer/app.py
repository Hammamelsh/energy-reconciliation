"""Household energy explorer.

Deliberately absent: costs, bills, forecasts, appliance guesses, savings claims,
household rankings, completeness percentages and cause explanations. This shows what
was recorded and what is unresolved about it.

Imports are absolute because Streamlit executes this file as a top-level script.

Run with:
    uv run streamlit run src/energy_reconciliation/explorer/app.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from energy_reconciliation.explorer import charts
from energy_reconciliation.explorer import queries as q
from energy_reconciliation.ingest.warehouse import DEFAULT_DATABASE

WAREHOUSE_DIR = Path("data/warehouse")
PAGE_SIZE = 100
PRESETS = {"7 days": 7, "14 days": 14, "30 days": 30, "Custom": None}

st.set_page_config(page_title="Household energy explorer", layout="wide")
st.markdown(
    """
    <style>
      h1 { font-size: 1.6rem; margin: 0 0 .2rem 0; }
      [data-testid="stMetric"] { padding: .25rem 0; }
      [data-testid="stMetricValue"] { font-size: 1.5rem; }
      [data-testid="stCaptionContainer"] { margin-top: -.35rem; }
      .status-clear   { color: #2bb3a3; font-weight: 600; }
      .status-review  { color: #d98c1f; font-weight: 600; }
      .status-blocking{ color: #d64545; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


def fmt_day(d: date) -> str:
    return f"{d:%-d %b %Y}"


def fmt_period(s: date, e: date) -> str:
    if s == e:
        return f"{s:%A %-d %B %Y} (one day)"
    days = (e - s).days + 1
    return f"{fmt_day(s)} – {fmt_day(e)} · {days} days"


# --------------------------------------------------------------- data source
available = sorted(WAREHOUSE_DIR.glob("*.duckdb")) if WAREHOUSE_DIR.is_dir() else []
if not available:
    st.error(
        f"No database in `{WAREHOUSE_DIR}/`. Load one first:\n\n"
        "`uv run ingest-member --demo --database data/warehouse/demo.duckdb`"
    )
    st.stop()

labels = {p: q.dataset_label(p) for p in available}
st.sidebar.header("Data source")
database = st.sidebar.radio(
    "Dataset",
    available,
    index=next((i for i, p in enumerate(available) if p == DEFAULT_DATABASE), 0),
    format_func=labels.get,
)
st.sidebar.caption(
    f"File: `{database.name}`. Loaded files are listed under Source records."
)

people = q.households(database)
if not people:
    st.warning("That database has no readings yet.")
    st.stop()

# ------------------------------------------------------- household and period
st.title("Household energy explorer")
st.caption(
    "Historical sample · Partial source coverage · Source timezone unresolved — "
    "details under *About this data* below."
)

row = st.columns([2, 2, 1.3, 1.3])
household = row[0].selectbox(f"Household ({len(people)} available)", people)
bounds = q.date_bounds(database, household)
first, last = bounds

# Widget keys include the household so a switch resets the period to a valid
# default instead of carrying a date that may lie outside the new bounds.
preset = row[1].segmented_control(
    "Period",
    list(PRESETS),
    default="14 days",
    key=f"preset-{household}",
    help="Presets are anchored to the last date recorded for this household, not today.",
)
if preset is None:
    preset = "14 days"

if PRESETS[preset] is not None:
    start, end = q.preset_window(database, household, PRESETS[preset])
    row[2].date_input("Start", start, disabled=True, key=f"s-{household}-{preset}")
    row[3].date_input("End", end, disabled=True, key=f"e-{household}-{preset}")
else:
    dflt_s, dflt_e = q.preset_window(database, household, 14)
    start = row[2].date_input(
        "Start", dflt_s, min_value=first, max_value=last, key=f"cs-{household}"
    )
    end = row[3].date_input(
        "End", dflt_e, min_value=first, max_value=last, key=f"ce-{household}"
    )
    if start > end:
        st.error(
            f"Start ({fmt_day(start)}) is after end ({fmt_day(end)}). "
            "Choose an end date on or after the start."
        )
        st.stop()

period = q.period_summary(database, household, start, end)
status = q.review_status(period)
quality = q.quality_summary(database, household, start, end)

st.markdown(
    f"**{household}** · {fmt_period(start, end)} · recorded data spans "
    f"{fmt_day(first)} – {fmt_day(last)}"
)

overview_tab, quality_tab, records_tab = st.tabs(
    ["Overview", "Data quality", "Source records"]
)

# ================================================================== OVERVIEW
with overview_tab:
    m = st.columns(3)
    if period.total_kwh is None:
        m[0].metric("Recorded consumption", "withheld")
    else:
        m[0].metric(
            "Recorded consumption",
            f"{period.total_kwh:,.3f} kWh",
            help=(
                "Shown to three decimal places. The exact recorded figure is a Decimal "
                "summed in the database; per-day exact values are in the bar tooltips."
            ),
        )
    if period.total_kwh is None:
        m[1].metric(
            "Readings in total",
            "Not applicable",
            help=(
                f"{period.available_readings:,} reading(s) are recorded in this period, "
                "but none contribute to a total because the total is withheld."
            ),
        )
    else:
        m[1].metric(
            "Readings in total",
            f"{period.contributing_readings:,}",
            help=(
                f"{period.available_readings:,} recorded; each distinct value at a "
                "timestamp counted once."
            ),
        )
    m[2].metric(
        "Items for review",
        f"{period.issues_for_review:,}",
        help=(
            "A sum of items across four categories in the selected period: missing "
            "values + gaps between consecutive grid readings + conflicting timestamps "
            "+ off-grid observations. Not a count of unique records: one row can "
            "appear under more than one heading. Exact duplicates and equivalent "
            "representations are not items; their counts are shown separately."
        ),
    )

    css = {
        "clear": "status-clear",
        "review": "status-review",
        "blocking": "status-blocking",
    }[status.level]
    st.markdown(
        f'<span class="{css}">{status.headline}.</span> {status.detail}',
        unsafe_allow_html=True,
    )
    st.caption(status.standing_caveat)

    # ------------------------------------------------------------- daily bars
    daily = q.daily_totals(database, household, start, end)
    if daily.empty:
        st.info(
            "No readings recorded for this household between "
            f"{fmt_day(start)} and {fmt_day(end)}."
        )
    else:
        st.altair_chart(charts.daily_chart(daily), width="stretch")
        year_note = (
            f"{start.year}" if start.year == end.year else f"{start.year}–{end.year}"
        )
        st.caption(
            f"Recorded totals by **source date**, {year_note}. Grouped by the date in "
            "the source timestamp — not a settlement day, not a local calendar day. "
            "Bars start at zero. A ◆ marker means no total is published for that day: "
            "conflicting readings, no observations, or no half-hour-grid readings. When "
            "no day has a publishable total the view is a status strip with no kWh axis. "
            "Off-grid observations are excluded from these totals but counted in the "
            "tooltip. A short bar is a smaller "
            "*recorded* total; hover for readings, missing values and gaps before "
            "reading it as lower usage. A boundary date is the first or last day "
            "recorded for this household and may be partial."
        )

        # ------------------------------------------------------ half-hour day
        days_with_data = list(
            daily.loc[
                daily["contributing_readings"] + daily["missing_values"] > 0,
                "source_date",
            ].dt.date
        )
        if days_with_data:
            pick = st.selectbox(
                "Half-hour detail for",
                days_with_data,
                index=len(days_with_data) - 1,
                format_func=lambda d: f"{d:%A %-d %B %Y}",
                key=f"day-{household}-{start}-{end}",
            )
            detail = q.half_hour_detail(database, household, pick)
            series = detail.series
            real = series[series["value_category"] != "line_break"]
            st.altair_chart(
                charts.detail_chart(series, detail.conflicts, detail.off_grid),
                width="stretch",
            )
            breaks = int((series["value_category"] == "line_break").sum())
            nulls = int((real["value_category"] == "null_token").sum())
            note = (
                f"{len(real)} undisputed grid reading(s) on this source date"
                + (f", {nulls} missing" if nulls else "")
                + (f", line broken at {breaks} point(s)" if breaks else "")
                + ". Timezone unresolved. Missing values are blank points, not zeros."
            )
            if not detail.off_grid.empty:
                note += (
                    f" ▲ {len(detail.off_grid)} off-grid observation(s) are plotted "
                    "separately with member and record number; they are excluded from "
                    "half-hour totals under the current policy."
                )
            if not detail.conflicts.empty:
                labels = detail.conflicts["source_timestamp_text"].nunique()
                note += (
                    f" ◆ {len(detail.conflicts)} conflicting observation(s) at {labels} "
                    "timestamp(s) are plotted as flagged points with their member and "
                    "record number; the line does not pass through them."
                )
            st.caption(note)

    with st.expander("About this data"):
        st.markdown(
            f"""
- **Historical sample.** Readings from the Low Carbon London trial, ending in 2014.
  Nothing is live.
- **Partial source coverage.** {
                len([s for s in q.loaded_sources(database) if s.status == "published"])
            } source file(s) loaded of 168 in the archive. Files
  are cut on row count, so a household's readings can continue into a file that is
  not loaded. The loaded history for any household may be incomplete.
- **Source timezone unresolved.** Timestamps carry no timezone. The timezone, and
  whether a timestamp marks the start or end of its half hour, are not established
  from the sources reviewed. Timestamps are shown as recorded and never converted.
- **Resolution policy.** Identical source rows are collapsed. Different texts for one
  numeric value at the same timestamp (`0.5` and `0.50`) are kept as evidence and
  counted once. Different values at the same timestamp are a conflict and withhold
  the total. Missing values are excluded, not treated as zero.
- **Steps and gaps.** Gaps are steps longer than half an hour between consecutive
  distinct timestamps on the half-hour grid, counted across midnight, each once,
  attributed to the date of the reading after the step. Off-grid observations are
  counted separately and never create a gap. A gap is an observed step, not a
  confirmed missing interval or a meter failure.
"""
        )

# ============================================================== DATA QUALITY
with quality_tab:
    st.markdown(f"Scope: **{household}**, {fmt_period(start, end)}.")
    g = st.columns(4)
    g[0].metric("Rows recorded", f"{quality.observed_records:,}")
    g[1].metric(
        "Distinct readings",
        f"{quality.distinct_readings:,}",
        help="Rows recorded minus repeated identical readings.",
    )
    g[2].metric("Repeated identical readings", f"{quality.duplicates_removed:,}")
    g[3].metric("Missing values", f"{quality.null_tokens:,}")
    g2 = st.columns(5)
    g2[0].metric("Conflicting timestamps", f"{quality.conflicting_keys:,}")
    g2[1].metric(
        "Equivalent representations",
        f"{quality.equivalent_representations:,}",
        help="One value written two ways at one timestamp. Counted once.",
    )
    g2[2].metric(
        "Gaps",
        f"{quality.gaps:,}",
        help="Steps over half an hour between consecutive grid timestamps.",
    )
    g2[3].metric(
        "Off-grid observations",
        f"{quality.off_grid_observations:,}",
        help="Timestamps not on the half-hour grid. Never counted as gaps.",
    )
    g2[4].metric(
        "Zero readings",
        f"{quality.zero_values:,}",
        help="A subset of the finite values. A zero is a measurement.",
    )

    st.markdown("**Findings**")
    conflicts = q.conflicting_keys(database, household, start, end)
    steps = q.step_anomalies(database, household, start, end)
    missing = q.observations(database, household, start, end, limit=2000)
    missing = missing[missing["value_category"] == "null_token"]
    equivalents = q.equivalent_representations(database, household, start, end)

    if (
        conflicts.empty
        and steps["gaps"].empty
        and steps["off_grid"].empty
        and missing.empty
        and equivalents.empty
    ):
        st.caption(
            "No conflicts, gaps, off-grid observations, equivalent representations "
            "or missing values in this period."
        )
    if not conflicts.empty:
        st.markdown(
            f'<span class="status-blocking">Conflicting readings — {len(conflicts)} '
            "timestamp(s).</span> Investigate each in Source records by its member "
            "and record number.",
            unsafe_allow_html=True,
        )
        st.dataframe(
            conflicts.rename(
                columns={
                    "source_timestamp_text": "Source timestamp",
                    "rows_at_key": "Rows",
                    "distinct_values": "Distinct values",
                    "texts": "Source texts",
                    "members_involved": "Members",
                    "first_member": "First member",
                    "first_record_no": "First record no.",
                }
            ).drop(columns=["household_id", "distinct_texts", "kind"]),
            width="stretch",
            hide_index=True,
        )
    if not steps["gaps"].empty:
        st.markdown(
            f'<span class="status-review">Gaps — {len(steps["gaps"])} step(s) longer '
            "than half an hour.</span> Narrow the period to the timestamps shown to "
            "inspect the surrounding readings.",
            unsafe_allow_html=True,
        )
        st.dataframe(
            steps["gaps"]
            .head(50)
            .rename(
                columns={
                    "from_timestamp": "Last grid reading before",
                    "to_timestamp": "First grid reading after",
                    "step_seconds": "Step (seconds)",
                    "attributed_date": "Attributed to",
                }
            ),
            width="stretch",
            hide_index=True,
        )
    if not equivalents.empty:
        st.markdown(
            f'<span class="status-review">Equivalent representations — '
            f"{len(equivalents)}.</span> One numeric value written more than one way "
            "at the same timestamp. Both rows are kept; the value is counted once.",
            unsafe_allow_html=True,
        )
        st.dataframe(
            equivalents[
                [
                    "source_timestamp_text",
                    "texts",
                    "rows_raw",
                    "first_member",
                    "first_record_no",
                ]
            ].rename(
                columns={
                    "source_timestamp_text": "Source timestamp",
                    "texts": "Source texts",
                    "rows_raw": "Rows",
                    "first_member": "First member",
                    "first_record_no": "First record no.",
                }
            ),
            width="stretch",
            hide_index=True,
        )
    if not steps["off_grid"].empty:
        st.markdown(
            f'<span class="status-review">Off-grid observations — '
            f"{len(steps['off_grid'])}.</span> Timestamps not on the half-hour grid. "
            "Excluded from the step sequence, so they never appear as gaps.",
            unsafe_allow_html=True,
        )
        st.dataframe(steps["off_grid"].head(50), width="stretch", hide_index=True)
    if not missing.empty:
        st.markdown(
            f'<span class="status-review">Missing values — {len(missing)}.</span> Rows '
            "recorded as `Null`. They are blank in the charts, not zero.",
            unsafe_allow_html=True,
        )
        st.dataframe(
            missing[
                ["member_name", "source_record_no", "source_timestamp_text"]
            ].rename(
                columns={
                    "member_name": "Source member",
                    "source_record_no": "Record no.",
                    "source_timestamp_text": "Source timestamp",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    st.caption(
        f"These counters overlap on purpose: rows recorded ({quality.observed_records:,}) "
        f"− repeated identical readings ({quality.duplicates_removed:,}) = distinct "
        f"readings ({quality.distinct_readings:,}). Zero readings sit inside the finite "
        "values. A missing value has a row; a gap has none. Do not add these together."
    )

    with st.expander("Definitions"):
        st.markdown(
            """
- **Missing value** — a row exists but carries no number; the source recorded `Null`.
  Not a zero, and never filled in.
- **Repeated identical reading** — the same household, source timestamp and value on
  more than one row. Counted once in totals; the number collapsed is always shown.
- **Conflicting readings** — the same household and source timestamp with *different*
  values. No total is produced for a period containing one.
- **Equivalent representations** — one numeric value written more than one way at the
  same timestamp, such as `0.5` and `0.50`. Kept as evidence, counted once, not a
  conflict.
- **Gap** — a step longer than half an hour between consecutive distinct timestamps on
  the half-hour grid, counted across midnight. An observed step only; never a confirmed
  missing interval, a meter failure, or a completeness figure.
- **Off-grid observation** — a timestamp not on the half-hour grid. Counted and listed
  separately; never part of the gap sequence.
"""
        )

    whole = q.quality_summary(database, household)
    with st.expander(f"Whole loaded history for {household} (not the selected period)"):
        w = st.columns(4)
        w[0].metric("Rows recorded", f"{whole.observed_records:,}")
        w[1].metric("Repeated identical", f"{whole.duplicates_removed:,}")
        w[2].metric("Conflicting timestamps", f"{whole.conflicting_keys:,}")
        w[3].metric("Gaps", f"{whole.gaps:,}")
        st.caption(
            f"Equivalent representations: {whole.equivalent_representations:,}; "
            f"off-grid observations: {whole.off_grid_observations:,}."
        )
        st.caption(
            f"Across {fmt_day(first)} – {fmt_day(last)} in the loaded files: "
            f"{', '.join(m.split('/')[-1] for m in whole.members)}. These figures are "
            "not filtered by the period above."
        )

# ============================================================= SOURCE RECORDS
with records_tab:
    total_rows = q.observation_count(database, household, start, end)
    st.markdown(
        f"**Recorded rows** for {household}, {fmt_period(start, end)}: "
        f"{total_rows:,} rows as loaded, including repeats "
        f"({quality.duplicates_removed:,} repeated identical, "
        f"{quality.distinct_readings:,} distinct)."
    )
    if total_rows == 0:
        st.caption("No rows in this period.")
    else:
        pages = (total_rows + PAGE_SIZE - 1) // PAGE_SIZE
        page = st.number_input(
            f"Page of {pages} ({PAGE_SIZE} rows each)",
            min_value=1,
            max_value=pages,
            value=1,
            step=1,
            key=f"page-{household}-{start}-{end}",
        )
        frame = q.observations(
            database,
            household,
            start,
            end,
            limit=PAGE_SIZE,
            offset=(int(page) - 1) * PAGE_SIZE,
        )
        st.dataframe(
            frame.rename(
                columns={
                    "member_name": "Source member",
                    "source_record_no": "Record no. in member",
                    "source_timestamp_text": "Source timestamp (as recorded)",
                    "consumption_raw_text": "Consumption (source text)",
                    "value_category": "Value category",
                    "on_half_hour_grid": "On half-hour grid",
                    "tariff_group": "Tariff group",
                    "timezone_status": "Timezone",
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Every row keeps its source member and record number, so any value can be "
            "traced to its exact place in the source."
        )

    st.markdown("**Loaded files**")
    sources = q.loaded_sources(database)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "archive": s.archive_name,
                    "member": s.member_name,
                    "status": s.status,
                    "records read": s.records_read,
                    "published": s.records_published,
                    "rejected": s.records_rejected,
                    "loaded (UTC)": s.loaded_at_utc,
                }
                for s in sources
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        f"{sum(1 for s in sources if s.status == 'published')} file(s) published of 168 "
        "in the archive. Superseded rows are earlier loads that were replaced."
    )
