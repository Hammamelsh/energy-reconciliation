"""The Altair specifications the explorer actually renders.

Built here, not inline in the app, so a test can inspect the exact chart data and
encodings the UI uses -- in particular that a withheld day never becomes a bar.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

TEAL, AMBER, RED, GREY = "#2bb3a3", "#d98c1f", "#d64545", "#6b7a90"

#: The theme's text colour (see .streamlit/config.toml). Text marks default to black,
#: which is invisible on the dark background; every text mark sets this explicitly.
TEXT = "#e6edf3"

#: Axis number formats, spelled with an explicit type so the renderer never falls back
#: to its own choice (which can be scientific notation for round thousands).
#: ``,.0f`` -> 5,000   ``,~f`` -> 4,380.2 (grouped, trailing zeros trimmed)
COUNT_FORMAT = ",.0f"
QUANTITY_FORMAT = ",~f"

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


# ------------------------------------------------------------ tariff scenario
BLUE = "#4a7fb5"

#: One colour per price band, used in every tariff view. Band names are always shown
#: as text as well, so colour never carries the meaning on its own. Cheapest first.
BAND_COLOURS = {"Low": BLUE, "Normal": TEAL, "High": RED}
BAND_ORDER = tuple(BAND_COLOURS)
_BAND_SCALE = alt.Scale(domain=list(BAND_COLOURS), range=list(BAND_COLOURS.values()))

#: Short series names. The long form lives in the caption and the table header, not on
#: an axis where it overlaps its neighbour.
CONSUMPTION_SERIES = "Consumption"
CHARGE_SERIES = "Charge"
SERIES_ORDER = (CONSUMPTION_SERIES, CHARGE_SERIES)
_SERIES_SCALE = alt.Scale(domain=list(SERIES_ORDER), range=[TEAL, AMBER])

LABEL_SIZE = 12
AXIS_TITLE_SIZE = 12


def share_frame(bands: pd.DataFrame) -> pd.DataFrame:
    """Long form of the two shares: one row per band per series.

    Both series come from the same ``band_summary`` frame, so both are shares of the
    same rows over the same period. Nothing here can pair a share of one scope with a
    share of another.
    """
    rows = []
    for series, column in (
        (CONSUMPTION_SERIES, "consumption_share"),
        (CHARGE_SERIES, "charge_share"),
    ):
        for _, band in bands.iterrows():
            rows.append(
                {
                    "band_label": band["band_label"],
                    "series": series,
                    "share": float(band[column]),
                    "share_label": f"{float(band[column]):.1%}",
                    "readings": int(band["readings"]),
                    "kwh_display": float(band["kwh_display"]),
                    "charge_gbp_display": float(band["charge_gbp_display"]),
                    "price_pence_per_kwh": float(band["price_pence_per_kwh"]),
                }
            )
    return pd.DataFrame(rows)


def band_share_chart(bands: pd.DataFrame) -> alt.Chart | alt.LayerChart:
    """Horizontal grouped bars: one row per band, two series, one shared 0-100% axis.

    Horizontal because the two series names are words, and words fit beside a bar but
    collide under one. The axis is pinned to 0-100% so the two panels of a comparison
    can never be read against different scales, and each bar carries its own percentage
    label so the value does not have to be estimated from the axis.

    An empty selection returns a plain statement with **no axis at all**. It never
    draws a zero-length bar, because "no charged readings here" and "a share of zero"
    are different facts.
    """
    if bands.empty:
        return empty_note(
            "No charged readings in this selection — no shares to show, and no zero."
        )
    frame = share_frame(bands)
    order = [b for b in BAND_ORDER if b in set(frame["band_label"])]
    y = alt.Y(
        "band_label:N",
        title=None,
        sort=order,
        axis=alt.Axis(labelFontSize=LABEL_SIZE + 1, labelFontWeight="bold"),
    )
    offset = alt.YOffset("series:N", sort=list(SERIES_ORDER))
    x = alt.X(
        "share:Q",
        title="Share of this selection",
        scale=alt.Scale(domain=[0, 1], nice=False),
        axis=alt.Axis(
            format="%", labelFontSize=LABEL_SIZE, titleFontSize=AXIS_TITLE_SIZE
        ),
    )
    tooltip = [
        alt.Tooltip("band_label:N", title="Band"),
        alt.Tooltip("series:N", title="Series"),
        alt.Tooltip("share:Q", title="Share", format=".2%"),
        alt.Tooltip("readings:Q", title="Charged readings", format=","),
        alt.Tooltip("kwh_display:Q", title="kWh", format=",.3f"),
        alt.Tooltip("charge_gbp_display:Q", title="Scenario charge £", format=",.2f"),
        alt.Tooltip("price_pence_per_kwh:Q", title="Price p/kWh"),
    ]
    base = alt.Chart(frame)
    bars = base.mark_bar(cornerRadiusTopRight=2, cornerRadiusBottomRight=2).encode(
        y=y,
        yOffset=offset,
        x=x,
        color=alt.Color(
            "series:N",
            scale=_SERIES_SCALE,
            legend=alt.Legend(title=None, orient="top", labelFontSize=LABEL_SIZE),
        ),
        tooltip=tooltip,
    )
    labels = base.mark_text(
        align="left", baseline="middle", dx=4, fontSize=LABEL_SIZE, color=TEXT
    ).encode(y=y, yOffset=offset, x=x, text=alt.Text("share_label:N"), tooltip=tooltip)
    return alt.layer(bars, labels).properties(height=alt.Step(26))


def empty_note(message: str) -> alt.Chart:
    """A statement where a chart would go, carrying **no quantitative encoding**.

    Used wherever a selection has nothing to show. A chart with an axis and no bars
    invites the reader to supply a zero; a sentence does not.
    """
    return (
        alt.Chart(pd.DataFrame({"message": [message]}))
        .mark_text(align="center", baseline="middle", fontSize=13, color=GREY)
        .encode(text=alt.Text("message:N"))
        .properties(height=64)
    )


def schedule_hour_chart(distribution: pd.DataFrame) -> alt.Chart:
    """SCHEDULE-WIDE. Half-hour slots per band by source hour of the schedule label.

    This describes the published schedule, not anyone's consumption.
    """
    if distribution.empty:
        return empty_note("No schedule loaded for this database.")
    return (
        alt.Chart(distribution)
        .mark_bar()
        .encode(
            x=alt.X(
                "source_hour:O",
                title="Hour of the schedule label",
                axis=alt.Axis(
                    labelAngle=0,
                    labelFontSize=LABEL_SIZE,
                    titleFontSize=AXIS_TITLE_SIZE,
                ),
            ),
            y=alt.Y(
                "sum(slots):Q",
                title="Half-hour slots",
                axis=alt.Axis(
                    format=COUNT_FORMAT,
                    labelFontSize=LABEL_SIZE,
                    titleFontSize=AXIS_TITLE_SIZE,
                ),
            ),
            color=alt.Color(
                "band_label:N",
                scale=_BAND_SCALE,
                sort=list(BAND_ORDER),
                legend=alt.Legend(title=None, orient="top", labelFontSize=LABEL_SIZE),
            ),
            order=alt.Order("color_band_label_sort_index:Q"),
            tooltip=[
                alt.Tooltip("band_label:N", title="Band"),
                alt.Tooltip("source_hour:O", title="Hour"),
                alt.Tooltip("sum(slots):Q", title="Slots", format=","),
            ],
        )
        .properties(height=300)
    )


def band_kwh_by_hour_chart(distribution: pd.DataFrame) -> alt.Chart:
    """LOADED SAMPLE. Charged kWh per band by source hour."""
    if distribution.empty:
        return empty_note("No charged readings in this selection.")
    return (
        alt.Chart(distribution)
        .mark_bar()
        .encode(
            x=alt.X(
                "source_hour:O",
                title="Hour of the source timestamp",
                axis=alt.Axis(
                    labelAngle=0,
                    labelFontSize=LABEL_SIZE,
                    titleFontSize=AXIS_TITLE_SIZE,
                ),
            ),
            y=alt.Y(
                "sum(kwh_display):Q",
                title="Charged kWh",
                axis=alt.Axis(
                    format=QUANTITY_FORMAT,
                    labelFontSize=LABEL_SIZE,
                    titleFontSize=AXIS_TITLE_SIZE,
                ),
            ),
            color=alt.Color(
                "band_label:N",
                scale=_BAND_SCALE,
                sort=list(BAND_ORDER),
                legend=alt.Legend(title=None, orient="top", labelFontSize=LABEL_SIZE),
            ),
            order=alt.Order("color_band_label_sort_index:Q"),
            tooltip=[
                alt.Tooltip("band_label:N", title="Band"),
                alt.Tooltip("source_hour:O", title="Hour"),
                alt.Tooltip("sum(kwh_display):Q", title="Charged kWh", format=",.3f"),
                alt.Tooltip("sum(readings):Q", title="Charged readings", format=","),
            ],
        )
        .properties(height=300)
    )


# ---------------------------------------------------------------- forecasting
#: User-facing names. Identifiers stay in method and export detail; a legend or a table
#: header uses these. Order is the order series appear in legends.
MODEL_LABELS = {
    "observed": "Observed",
    "seasonal_naive_7": "Same weekday, previous week",
    "weekday_mean_4": "4-week weekday mean",
    "persistence_1": "Origin day repeated (reference)",
}
#: One colour per series. "Observed" is the teal used for recorded quantities everywhere
#: else in the app, so a prediction is never mistaken for a reading. Colour is not the
#: only distinction: lines carry a dash pattern and points a shape per series.
FORECAST_COLOURS = {
    MODEL_LABELS["observed"]: TEAL,
    MODEL_LABELS["seasonal_naive_7"]: AMBER,
    MODEL_LABELS["weekday_mean_4"]: BLUE,
    MODEL_LABELS["persistence_1"]: GREY,
}
MODEL_ONLY = [v for k, v in MODEL_LABELS.items() if k != "observed"]
_SERIES_DASH = {
    MODEL_LABELS["observed"]: [1, 0],
    MODEL_LABELS["seasonal_naive_7"]: [6, 3],
    MODEL_LABELS["weekday_mean_4"]: [2, 2],
    MODEL_LABELS["persistence_1"]: [8, 2, 2, 2],
}
_SERIES_SHAPE = {
    MODEL_LABELS["observed"]: "circle",
    MODEL_LABELS["seasonal_naive_7"]: "triangle-up",
    MODEL_LABELS["weekday_mean_4"]: "square",
    MODEL_LABELS["persistence_1"]: "diamond",
}


def _series_scale(names: list[str]) -> alt.Scale:
    """A colour scale whose domain is exactly the series being drawn -- never more."""
    return alt.Scale(domain=names, range=[FORECAST_COLOURS[n] for n in names])


def _legend() -> alt.Legend:
    return alt.Legend(title=None, orient="top", labelFontSize=LABEL_SIZE, symbolSize=90)


def observed_vs_predicted_chart(frame: pd.DataFrame) -> alt.Chart | alt.LayerChart:
    """One forecast origin's horizon: the recorded total beside each model's prediction.

    One tick per target source date: the axis is temporal, so ticks are pinned to whole
    days rather than left to the renderer, which otherwise halves the interval and
    repeats every label. A missing point is missing -- nothing is interpolated across it
    and no zero is drawn, so a day a model declined is visibly absent.
    """
    if frame.empty or frame["value"].isna().all():
        return empty_note("Nothing to plot for this origin.")
    points = frame.dropna(subset=["value"])
    present = [n for n in FORECAST_COLOURS if n in set(points["series"])]
    base = alt.Chart(points)
    x = alt.X(
        "target_date:T",
        title="Target source date",
        axis=alt.Axis(
            format="%a %-d %b",
            tickCount={"interval": "day", "step": 1},
            labelAngle=0,
            labelFontSize=LABEL_SIZE,
        ),
    )
    y = alt.Y(
        "value:Q",
        title="Daily total (kWh)",
        axis=alt.Axis(format=QUANTITY_FORMAT, labelFontSize=LABEL_SIZE),
    )
    color = alt.Color(
        "series:N", scale=_series_scale(present), sort=present, legend=_legend()
    )
    tooltip = [
        alt.Tooltip("series:N", title="Series"),
        alt.Tooltip("target_date:T", title="Target source date", format="%A %-d %b %Y"),
        alt.Tooltip("horizon:Q", title="Days ahead"),
        alt.Tooltip("value:Q", title="kWh", format=",.3f"),
    ]
    lines = base.mark_line(strokeWidth=2).encode(
        x=x,
        y=y,
        color=color,
        strokeDash=alt.StrokeDash(
            "series:N",
            scale=alt.Scale(domain=present, range=[_SERIES_DASH[n] for n in present]),
            legend=None,
        ),
        tooltip=tooltip,
    )
    marks = base.mark_point(size=70, filled=True).encode(
        x=x,
        y=y,
        color=color,
        shape=alt.Shape(
            "series:N",
            scale=alt.Scale(domain=present, range=[_SERIES_SHAPE[n] for n in present]),
            legend=None,
        ),
        tooltip=tooltip,
    )
    return alt.layer(lines, marks).properties(height=320)


def model_error_chart(frame: pd.DataFrame, title: str) -> alt.Chart:
    """MAE per model, horizontal so the names sit beside their bars.

    The renderer truncates axis labels wider than 180 px by default, which cut every
    model name to "4-week weekda..." at the widths this page is read at. ``labelLimit=0``
    removes the limit, so the left margin grows to fit the longest name at full size
    rather than the name shrinking or being cut.
    """
    if frame.empty:
        return empty_note("No scored predictions in this scope.")
    order = list(frame.sort_values("mae_kwh")["model"])
    base = alt.Chart(frame)
    encoding = {
        "y": alt.Y(
            "model:N",
            title=None,
            sort=order,
            axis=alt.Axis(labelFontSize=LABEL_SIZE + 1, labelLimit=0),
        ),
        "x": alt.X(
            "mae_kwh:Q",
            title=title,
            axis=alt.Axis(format=QUANTITY_FORMAT, labelFontSize=LABEL_SIZE),
        ),
        "color": alt.Color("model:N", scale=_series_scale(order), legend=None),
        "tooltip": [
            alt.Tooltip("model:N", title="Model"),
            alt.Tooltip("mae_kwh:Q", title="MAE kWh", format=",.3f"),
            alt.Tooltip("count:Q", title="Scored predictions", format=","),
        ],
    }
    bars = base.mark_bar(cornerRadiusTopRight=2, cornerRadiusBottomRight=2).encode(
        **encoding
    )
    labels = base.mark_text(
        align="left", baseline="middle", dx=4, fontSize=LABEL_SIZE, color=TEXT
    ).encode(**{**encoding, "text": alt.Text("mae_label:N")})
    return alt.layer(bars, labels).properties(height=alt.Step(30))


def horizon_error_chart(frame: pd.DataFrame) -> alt.Chart:
    """MAE against days ahead. The legend lists exactly the models drawn."""
    if frame.empty:
        return empty_note("No scored predictions in this scope.")
    present = [n for n in MODEL_ONLY if n in set(frame["model"])]
    return (
        alt.Chart(frame)
        .mark_line(point=alt.OverlayMarkDef(size=55), strokeWidth=2)
        .encode(
            x=alt.X(
                "horizon:O",
                title="Days ahead of the forecast origin",
                axis=alt.Axis(labelAngle=0, labelFontSize=LABEL_SIZE),
            ),
            y=alt.Y(
                "mae_kwh:Q",
                title="MAE (kWh)",
                scale=alt.Scale(zero=False),
                axis=alt.Axis(format=QUANTITY_FORMAT, labelFontSize=LABEL_SIZE),
            ),
            color=alt.Color(
                "model:N", scale=_series_scale(present), sort=present, legend=_legend()
            ),
            strokeDash=alt.StrokeDash(
                "model:N",
                scale=alt.Scale(
                    domain=present, range=[_SERIES_DASH[n] for n in present]
                ),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("model:N", title="Model"),
                alt.Tooltip("horizon:O", title="Days ahead"),
                alt.Tooltip("mae_kwh:Q", title="MAE kWh", format=",.3f"),
                alt.Tooltip("count:Q", title="Scored predictions", format=","),
            ],
        )
        .properties(height=300)
    )


# ------------------------------------------------- ANL-005 flat-price comparison
OUTCOME_COLOURS = {
    "lower under dynamic": TEAL,
    "higher under dynamic": AMBER,
    "equal": GREY,
}


def household_difference_chart(frame: pd.DataFrame) -> alt.Chart | alt.LayerChart:
    """One horizontal bar per household: flat-price charge minus dynamic charge, in £.

    Positive bars (right of the zero rule) mean the dynamic scenario is lower for that
    household. Colour repeats the sign as words in the legend and the tooltip, so it never
    carries the outcome alone. Bars are sorted by difference so the spread reads top to
    bottom; the tooltip carries the household's observed coverage, because a small bar
    on a household charged for few readings is a coverage fact before it is a price one.
    """
    if frame.empty:
        return empty_note("No charged readings in this selection — nothing to compare.")
    data = pd.DataFrame(
        {
            "household_id": frame["household_id"],
            "difference": [float(v) for v in frame["difference_exact"]],
            "outcome": [
                {"lower": "lower under dynamic", "higher": "higher under dynamic"}.get(
                    o, "equal"
                )
                for o in frame["outcome_under_dynamic"]
            ],
            "charged_readings": frame["charged_readings"],
            "coverage": [
                float(v) if v is not None else float("nan")
                for v in frame["coverage_share"]
            ],
            "dynamic": [float(v) for v in frame["dynamic_charge_gbp_exact"]],
            "flat": [float(v) for v in frame["flat_charge_gbp_exact"]],
            "pct": [
                float(v) if v is not None else float("nan")
                for v in frame["pct_of_flat_exact"]
            ],
        }
    )
    order = list(data.sort_values("difference")["household_id"])
    height = max(160, 18 * len(order) + 40)
    bars = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            y=alt.Y(
                "household_id:N",
                title=None,
                sort=order,
                axis=alt.Axis(labelFontSize=LABEL_SIZE - 1),
            ),
            x=alt.X(
                "difference:Q",
                title="Flat-price charge minus dynamic charge (£) — positive: dynamic lower",
                axis=alt.Axis(
                    format=",.2f",
                    labelFontSize=LABEL_SIZE,
                    titleFontSize=AXIS_TITLE_SIZE,
                ),
            ),
            color=alt.Color(
                "outcome:N",
                scale=alt.Scale(
                    domain=list(OUTCOME_COLOURS), range=list(OUTCOME_COLOURS.values())
                ),
                legend=alt.Legend(title=None, orient="top", labelFontSize=11),
            ),
            tooltip=[
                alt.Tooltip("household_id:N", title="Household"),
                alt.Tooltip("outcome:N", title="Outcome"),
                alt.Tooltip("difference:Q", title="Flat − dynamic £", format=",.2f"),
                alt.Tooltip("pct:Q", title="% of flat-price charge", format=".1f"),
                alt.Tooltip("dynamic:Q", title="Dynamic £", format=",.2f"),
                alt.Tooltip("flat:Q", title="Flat-price £", format=",.2f"),
                alt.Tooltip("charged_readings:Q", title="Charged readings", format=","),
                alt.Tooltip("coverage:Q", title="Observed coverage", format=".1%"),
            ],
        )
    )
    zero = (
        alt.Chart(pd.DataFrame({"x": [0.0]}))
        .mark_rule(color=TEXT, strokeWidth=1)
        .encode(x="x:Q")
    )
    return (bars + zero).properties(height=height)


def household_pct_difference_chart(frame: pd.DataFrame) -> alt.Chart | alt.LayerChart:
    """The landing chart: each household's difference as a percentage of its flat charge.

    Same sign convention as :func:`household_difference_chart` (positive: dynamic lower),
    a zero rule, and the household label carries its observed coverage in words when it
    is below 99%, so a partially covered household is marked by text and not by colour.
    Pounds are in the tooltip.
    """
    if frame.empty:
        return empty_note("No charged readings — nothing to compare.")
    rows = []
    for r in frame.to_dict(orient="records"):
        cov = r["coverage_share"]
        cov_f = float(cov) if cov is not None else float("nan")
        label = r["household_id"] + (
            f" ({cov_f:.1%} coverage)" if cov is not None and cov_f < 0.99 else ""
        )
        pct = r["pct_of_flat_exact"]
        rows.append(
            {
                "label": label,
                "pct": float(pct) if pct is not None else float("nan"),
                "outcome": {
                    "lower": "lower under dynamic",
                    "higher": "higher under dynamic",
                }.get(r["outcome_under_dynamic"], "equal"),
                "difference": float(r["difference_exact"]),
                "dynamic": float(r["dynamic_charge_gbp_exact"]),
                "flat": float(r["flat_charge_gbp_exact"]),
                "charged_readings": r["charged_readings"],
                "coverage": cov_f,
            }
        )
    data = pd.DataFrame(rows)
    order = list(data.sort_values("pct")["label"])
    # 24 px per bar: below ~20 px Altair drops every other category label, and a bar
    # without its household name cannot be read against the table.
    height = max(180, 24 * len(order) + 40)
    bars = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            y=alt.Y(
                "label:N",
                title=None,
                sort=order,
                axis=alt.Axis(labelFontSize=LABEL_SIZE - 1),
            ),
            x=alt.X(
                "pct:Q",
                title="Difference as % of the flat-price charge — positive: dynamic lower",
                axis=alt.Axis(
                    format=".1f",
                    labelFontSize=LABEL_SIZE,
                    titleFontSize=AXIS_TITLE_SIZE,
                ),
            ),
            color=alt.Color(
                "outcome:N",
                scale=alt.Scale(
                    domain=list(OUTCOME_COLOURS), range=list(OUTCOME_COLOURS.values())
                ),
                legend=alt.Legend(title=None, orient="top", labelFontSize=11),
            ),
            tooltip=[
                alt.Tooltip("label:N", title="Household"),
                alt.Tooltip("outcome:N", title="Outcome"),
                alt.Tooltip("pct:Q", title="% of flat-price charge", format="+.1f"),
                alt.Tooltip("difference:Q", title="Flat − dynamic £", format="+,.2f"),
                alt.Tooltip("dynamic:Q", title="Dynamic £", format=",.2f"),
                alt.Tooltip("flat:Q", title="Flat-price £", format=",.2f"),
                alt.Tooltip("charged_readings:Q", title="Charged readings", format=","),
                alt.Tooltip("coverage:Q", title="Observed coverage", format=".1%"),
            ],
        )
    )
    zero = (
        alt.Chart(pd.DataFrame({"x": [0.0]}))
        .mark_rule(color=TEXT, strokeWidth=1)
        .encode(x="x:Q")
    )
    return (bars + zero).properties(height=height)
