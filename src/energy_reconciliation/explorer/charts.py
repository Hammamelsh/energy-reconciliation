"""The Altair specifications the explorer actually renders.

Built here, not inline in the app, so a test can inspect the exact chart data and
encodings the UI uses -- in particular that a withheld day never becomes a bar.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

TEAL, AMBER, RED, GREY = "#2bb3a3", "#d98c1f", "#d64545", "#6b7a90"

#: Legend order and colour. Colour never carries state alone: every status is text
#: in the legend, the tooltip and the day marker.
STATUS_COLOURS = {
    "recorded": TEAL,
    "for review": AMBER,
    "boundary date": AMBER,
    "conflicting readings": RED,
    "no readings recorded": GREY,
}
_STATUS_SCALE = alt.Scale(
    domain=list(STATUS_COLOURS), range=list(STATUS_COLOURS.values())
)
_LEGEND = alt.Legend(title=None, orient="top", labelFontSize=11)


def daily_frame_for_chart(daily: pd.DataFrame) -> pd.DataFrame:
    """Add display columns. Bars are drawn only for published totals."""
    out = daily.copy()
    out["weekday"] = out["source_date"].dt.strftime("%A %-d %B %Y")
    out["recorded_label"] = [
        f"{t} kWh"
        if t
        else (
            "withheld — conflicting readings"
            if st == "withheld"
            else ("no half-hour-grid readings" if hr else "no observations")
        )
        for t, st, hr in zip(
            out["recorded_kwh_text"], out["total_status"], out["has_rows"], strict=True
        )
    ]
    out["contributing_label"] = [
        "not applicable (total withheld)" if s == "withheld" else str(int(c))
        for c, s in zip(out["contributing_readings"], out["total_status"], strict=True)
    ]
    return out


def daily_chart(daily: pd.DataFrame) -> alt.LayerChart:
    """Bars for published totals; a labelled marker for every other day.

    The marker layer encodes **no energy quantity**: it sits at the baseline and
    carries only the status text. A withheld day can therefore never be read as a
    kWh value, and an absent day is visibly present rather than silently omitted.
    """
    frame = daily_frame_for_chart(daily)
    if not (frame["total_status"] == "published").any():
        return status_strip(frame)
    many = len(frame) > 16
    x = alt.X(
        "source_date:O",
        title=None,
        timeUnit="yearmonthdate",
        axis=alt.Axis(
            format="%-d %b" if not many else "%-d",
            labelAngle=0,
            labelOverlap="greedy",
            labelFontSize=11,
        ),
    )
    tooltip = [
        alt.Tooltip("weekday:N", title="Source date"),
        alt.Tooltip("recorded_label:N", title="Recorded"),
        alt.Tooltip("contributing_label:N", title="Readings in total"),
        alt.Tooltip("available_readings:Q", title="Readings recorded"),
        alt.Tooltip("duplicates_removed:Q", title="Duplicates collapsed"),
        alt.Tooltip("equivalent_representations:Q", title="Equivalent representations"),
        alt.Tooltip("missing_values:Q", title="Missing values"),
        alt.Tooltip("gaps_observed:Q", title="Gaps observed"),
        alt.Tooltip("off_grid_rows:Q", title="Off-grid observations"),
        alt.Tooltip("status:N", title="Status"),
    ]
    bars = (
        alt.Chart(frame[frame["total_status"] == "published"])
        .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
        .encode(
            x=x,
            y=alt.Y("recorded_kwh:Q", title="Recorded kWh", scale=alt.Scale(zero=True)),
            color=alt.Color("status:N", scale=_STATUS_SCALE, legend=_LEGEND),
            tooltip=tooltip,
        )
    )
    markers = (
        alt.Chart(frame[frame["total_status"] != "published"])
        .mark_text(text="◆", size=16, baseline="bottom", dy=-2)
        .encode(
            x=x,
            y=alt.value(0),  # baseline only: no quantity is encoded
            color=alt.Color("status:N", scale=_STATUS_SCALE, legend=_LEGEND),
            tooltip=tooltip,
        )
    )
    return alt.layer(bars, markers).properties(height=250).resolve_scale(color="shared")


def detail_chart(
    series: pd.DataFrame, conflicts: pd.DataFrame, off_grid: pd.DataFrame
) -> alt.LayerChart:
    """A line through undisputed readings, broken at gaps and at disputed labels,
    plus flagged points for each conflicting observation with its source reference.
    """
    line = (
        alt.Chart(series)
        .mark_line(point=alt.OverlayMarkDef(size=28), color=TEAL)
        .encode(
            x=alt.X(
                "source_timestamp:T",
                title=None,
                axis=alt.Axis(format="%H:%M", labelFontSize=11),
            ),
            y=alt.Y(
                "recorded_kwh:Q", title="kWh per half hour", scale=alt.Scale(zero=True)
            ),
            tooltip=[
                alt.Tooltip("source_timestamp_text:N", title="Source timestamp"),
                alt.Tooltip("recorded_kwh:Q", title="kWh", format=",.4f"),
                alt.Tooltip("value_category:N", title="Value"),
                alt.Tooltip("on_half_hour_grid:N", title="On half-hour grid"),
            ],
        )
    )
    flagged = (
        alt.Chart(conflicts)
        .mark_point(shape="diamond", size=110, filled=True, color=RED)
        .encode(
            x=alt.X("source_timestamp:T"),
            y=alt.Y("recorded_kwh:Q"),
            tooltip=[
                alt.Tooltip("source_timestamp_text:N", title="Source timestamp"),
                alt.Tooltip("consumption_raw_text:N", title="Source text"),
                alt.Tooltip("member_name:N", title="Member"),
                alt.Tooltip("source_record_no:Q", title="Record no."),
                alt.Tooltip("value_category:N", title="Value"),
            ],
        )
    )
    off = (
        alt.Chart(off_grid)
        .mark_point(shape="triangle-up", size=90, filled=True, color=AMBER)
        .encode(
            x=alt.X("source_timestamp:T"),
            y=alt.Y("recorded_kwh:Q"),
            tooltip=[
                alt.Tooltip(
                    "source_timestamp_text:N", title="Source timestamp (off-grid)"
                ),
                alt.Tooltip("consumption_raw_text:N", title="Source text"),
                alt.Tooltip("member_name:N", title="Member"),
                alt.Tooltip("source_record_no:Q", title="Record no."),
                alt.Tooltip("value_category:N", title="Value"),
            ],
        )
    )
    return alt.layer(line, flagged, off).properties(height=210)


def status_strip(frame: pd.DataFrame) -> alt.Chart:
    """The daily view when no selected date has a publishable total.

    A compact strip: one labelled marker per date, coloured by status, with **no
    kWh axis at all** -- there is no quantity to scale. Withheld-by-conflict and
    no-observations are different statuses in the legend, the text and the tooltip,
    and neither is zero.
    """
    many = len(frame) > 16
    return (
        alt.Chart(frame)
        .mark_text(text="◆", size=18)
        .encode(
            x=alt.X(
                "source_date:O",
                title="No publishable daily total in this selection",
                timeUnit="yearmonthdate",
                axis=alt.Axis(
                    format="%-d %b" if not many else "%-d",
                    labelAngle=0,
                    labelOverlap="greedy",
                    labelFontSize=11,
                ),
            ),
            color=alt.Color("status:N", scale=_STATUS_SCALE, legend=_LEGEND),
            tooltip=[
                alt.Tooltip("weekday:N", title="Source date"),
                alt.Tooltip("recorded_label:N", title="Recorded"),
                alt.Tooltip("available_readings:Q", title="Readings recorded"),
                alt.Tooltip("missing_values:Q", title="Missing values"),
                alt.Tooltip("off_grid_rows:Q", title="Off-grid observations"),
                alt.Tooltip("status:N", title="Status"),
            ],
        )
        .properties(height=80)
    )
