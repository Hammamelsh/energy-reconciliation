"""Household energy explorer.

Deliberately absent: costs, bills, forecasts, appliance guesses, savings claims,
household rankings, completeness percentages and cause explanations. This shows what
was recorded and what is unresolved about it.

Imports are absolute because Streamlit executes this file as a top-level script.

Run with:
    uv run streamlit run src/energy_reconciliation/explorer/app.py
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

from energy_reconciliation.explorer import charts
from energy_reconciliation.explorer import datasets as ds
from energy_reconciliation.explorer import forecast_view as fc
from energy_reconciliation.explorer import queries as q
from energy_reconciliation.explorer import selection as sel
from energy_reconciliation.ingest.warehouse import DEFAULT_DATABASE
from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff import flat_comparison as fcmp
from energy_reconciliation.tariff import reads
from energy_reconciliation.tariff.models import ASSUMPTION_TEXT

WAREHOUSE_DIR = Path("data/warehouse")
PAGE_SIZE = 100
PRESETS = {"7 days": 7, "14 days": 14, "30 days": 30, "Custom": None}

#: The tariff tab's three scopes. Each view answers one of them and mixes none.
SCENARIO_VIEWS = ("Selected household", "Loaded ToU sample", "Published schedule")
SCENARIO_PERIODS = ("Full coverage", "Custom")

#: The household selector's widget key. Named so that an explicit, user-pressed button
#: can move the selection -- and only a button ever does.
HOUSEHOLD_KEY = "household-select"
WAREHOUSE_KEY = "warehouse-file"
COMPARISON_KEY = "show-comparison-warehouses"

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
      .ctl-note { font-size: .8rem; opacity: .8; padding-top: 1.9rem; line-height: 1.2; }
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


# ------------------------------------------------------------ display formatting
# Exact figures are never destroyed: every formatter here has its unrounded source
# shown beside it, in a tooltip or under "Calculation details".
def fmt_count(value) -> str:
    return f"{int(value):,}"


def fmt_kwh(value) -> str:
    return f"{float(value):,.3f}"


def fmt_gbp(value) -> str:
    return f"£{float(value):,.2f}"


def fmt_pct(value) -> str:
    return f"{float(value):.1%}"


def select_household(target: str) -> None:
    """Move the household selection. Only ever called from a pressed button.

    Nothing on the tariff tab changes the household on its own: the user picks a
    household and presses, which is why this is a callback and not a side effect of
    rendering.
    """
    st.session_state[HOUSEHOLD_KEY] = target


def fmt_reason_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    out["readings"] = [fmt_count(v) for v in out["readings"]]
    return out.rename(
        columns={
            "exclusion_reason": "Exclusion reason",
            "readings": "Readings",
            "first_date": "First source date",
            "last_date": "Last source date",
        }
    )


def fmt_band_table(bands: pd.DataFrame) -> pd.DataFrame:
    """The accessible table beneath the share chart: same numbers, as text."""
    return pd.DataFrame(
        {
            "Band": bands["band_label"],
            "Price p/kWh": [f"{v:,.3f}" for v in bands["price_pence_per_kwh"]],
            "Charged readings": [fmt_count(v) for v in bands["readings"]],
            "Charged kWh": [fmt_kwh(v) for v in bands["kwh_display"]],
            "Scenario charge": [fmt_gbp(v) for v in bands["charge_gbp_display"]],
            "Consumption share": [fmt_pct(v) for v in bands["consumption_share"]],
            "Charge share": [fmt_pct(v) for v in bands["charge_share"]],
        }
    )


def fmt_household_table(totals: pd.DataFrame) -> pd.DataFrame:
    if totals.empty:
        return totals
    return pd.DataFrame(
        {
            "Household": totals["household_id"],
            "Charged readings": [fmt_count(v) for v in totals["charged_readings"]],
            "First charged date": totals["first_charged_date"],
            "Last charged date": totals["last_charged_date"],
            "Charged kWh": [fmt_kwh(v) for v in totals["kwh_display"]],
            "Scenario charge": [fmt_gbp(v) for v in totals["charge_gbp_display"]],
        }
    )


def fmt_schedule_table(totals: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Band": totals["band_label"],
            "Half-hour slots": [fmt_count(v) for v in totals["slots"]],
            "Hours": [f"{float(v):,.1f}" for v in totals["hours"]],
            "Share of schedule": [fmt_pct(v) for v in totals["slot_share"]],
        }
    )


def fmt_price_table(prices: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Tariff group": prices["tariff_group"],
            "Band": prices["band_label"],
            "Price p/kWh": [f"{float(v):,.3f}" for v in prices["price_pence_per_kwh"]],
            "Price £/kWh": [f"{float(v):,.6f}" for v in prices["price_gbp_per_kwh"]],
            "Valid from (inclusive)": [
                "UNKNOWN" if v is None or pd.isna(v) else str(v)
                for v in prices["effective_from"]
            ],
            "Valid until (exclusive)": [
                "UNKNOWN" if v is None or pd.isna(v) else str(v)
                for v in prices["effective_until"]
            ],
            "Evidence": prices["evidence_label"],
        }
    )


def render_band_view(
    bands: pd.DataFrame, scope_note: str, insights: list[ta.Insight] | None = None
) -> tuple[int, str, str]:
    """Metrics, the share chart and its accessible table, for one explicit scope.

    Returns the exact (readings, kWh, charge) of the selection so the caller can show
    the unrounded figures. An empty selection renders a statement and **no zeros**:
    "nothing was charged here" and "a charge of zero" are different facts.
    """
    if bands.empty:
        st.info(
            f"No charged readings for this selection ({scope_note}). "
            "No total is shown, and none is zero — there is nothing to total."
        )
        return 0, "0", "0"
    readings = int(bands.attrs["denominator_readings"])
    kwh = Decimal(bands.attrs["denominator_kwh_exact"])
    charge = Decimal(bands.attrs["denominator_charge_gbp_exact"])
    m = st.columns(3)
    m[0].metric("Charged readings", fmt_count(readings), help=f"Scope: {scope_note}.")
    m[1].metric(
        "Charged kWh",
        fmt_kwh(ta.round_energy(kwh)),
        help=f"Exact, unrounded: {kwh} kWh. Displayed to three decimal places.",
    )
    m[2].metric(
        "Scenario energy charge",
        fmt_gbp(ta.round_money(charge)),
        help=(
            f"Exact, unrounded: £{charge}. Rounded once here, to 2 decimal places, "
            f"half up. {ta.CHARGE_SCOPE}"
        ),
    )
    st.altair_chart(charts.band_share_chart(bands), width="stretch")
    st.caption(
        f"Both series describe the same rows — {scope_note}: **{fmt_kwh(kwh)} kWh** "
        f"and **{fmt_gbp(charge)}** over **{fmt_count(readings)} charged readings**. "
        "Shares are rounded independently, so a column need not total exactly 100%."
    )
    st.dataframe(fmt_band_table(bands), width="stretch", hide_index=True)
    if insights:
        st.markdown("**In this selection**")
        for insight in insights:
            st.markdown(f"- {insight.headline}")
        with st.expander("Figures behind these sentences"):
            for insight in insights:
                st.markdown(
                    "  \n".join(f"`{k}`: {v}" for k, v in insight.supporting.items())
                )
    return readings, str(kwh), str(charge)


def fmt_signed_gbp(value) -> str:
    v = float(value)
    return f"{'+' if v > 0 else '-' if v < 0 else ''}£{abs(v):,.2f}"


def fmt_signed_pct(value) -> str:
    v = float(value)
    return f"{'+' if v > 0 else ''}{v:.1f}%"


def fmt_comparison_table(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Household": frame["household_id"],
            "Charged readings": [fmt_count(v) for v in frame["charged_readings"]],
            "Observed coverage": [
                "—" if v is None else fmt_pct(v) for v in frame["coverage_share"]
            ],
            "First charged": frame["first_charged_date"],
            "Last charged": frame["last_charged_date"],
            "Dynamic charge": [
                fmt_gbp(ta.round_money(Decimal(v)))
                for v in frame["dynamic_charge_gbp_exact"]
            ],
            "Flat-price charge": [
                fmt_gbp(ta.round_money(Decimal(v)))
                for v in frame["flat_charge_gbp_exact"]
            ],
            "Flat − dynamic": [
                fmt_signed_gbp(ta.round_money(Decimal(v)))
                for v in frame["difference_exact"]
            ],
            "% of flat": [
                "undefined" if v is None else fmt_signed_pct(Decimal(v))
                for v in frame["pct_of_flat_exact"]
            ],
            "Under dynamic": frame["outcome_under_dynamic"],
        }
    )


def render_flat_comparison(
    database: Path,
    run_id: str,
    relations: ta.Relations,
    household: str | None,
    s_start: date,
    s_end: date,
) -> None:
    """ANL-005: the same charged readings priced two ways, for the selection on screen.

    An unavailable comparison renders one statement and leaves everything above it
    untouched: the dynamic-tariff figures never depend on the flat price existing.
    """
    st.markdown("#### The same readings priced at the flat rate")
    result = fcmp.compare(
        database, run_id, household, s_start, s_end, relations=relations
    )
    if isinstance(result, fcmp.Unavailable):
        st.info(
            f"**Flat-price comparison not available** (`{result.kind}`): "
            f"{result.reason}. The dynamic-tariff figures above are unaffected."
        )
        return
    t, price = result.totals, result.price
    scope = household or f"all {t.households:,} charged households"
    st.caption(
        f"**Fixed-consumption historical comparison** — {scope}, "
        f"{fmt_period(s_start, s_end)}: the same **{fmt_count(t.readings)} charged "
        f"readings** priced under the dynamic scenario (A1) and, under assumption "
        f"**A2**, at the documented flat price of **{price.price_pence_per_kwh} p/kWh**. "
        "**Positive means the dynamic scenario is lower.** It is not a bill, a saving, "
        "a behavioural finding or advice."
    )
    m = st.columns(4)
    m[0].metric(
        "Dynamic energy charge",
        fmt_gbp(ta.round_money(t.dynamic)),
        help=f"Exact, unrounded: £{t.dynamic}. The scenario charge under A1.",
    )
    m[1].metric(
        "Flat-price energy charge",
        fmt_gbp(ta.round_money(t.flat)),
        help=(
            f"Exact, unrounded: £{t.flat}. {t.kwh} kWh × £{price.price_gbp_per_kwh}/kWh "
            "under A2."
        ),
    )
    m[2].metric(
        "Flat minus dynamic",
        fmt_signed_gbp(ta.round_money(t.difference)),
        help=f"Exact, unrounded: £{t.difference}. Positive: dynamic scenario lower.",
    )
    m[3].metric(
        "As % of flat-price charge",
        "undefined" if t.pct_of_flat is None else fmt_signed_pct(t.pct_of_flat),
        help=(
            "Denominator: the flat-price energy charge. "
            + (
                "Undefined because that charge is exactly zero."
                if t.pct_of_flat is None
                else f"Exact: {t.pct_of_flat}%."
            )
        ),
    )
    if household is None:
        o = result.outcomes
        st.markdown(
            f"**Under the dynamic scenario, {o['lower']} household(s) are lower, "
            f"{o['higher']} higher and {o['equal']} equal** — classified on exact "
            "differences, not rounded display values."
        )
        v = result.variation
        if v:
            share = v["largest_share_of_pooled_pct"]
            st.caption(
                f"Largest single household difference: "
                f"{fmt_signed_gbp(ta.round_money(Decimal(v['largest_difference_exact'])))} "
                f"({v['largest_household']})"
                + (
                    f", {float(Decimal(share)):.1f}% of the pooled difference"
                    if share is not None
                    else ""
                )
                + f"; median household difference "
                f"{fmt_signed_gbp(ta.round_money(Decimal(v['median_household_difference_exact'])))}. "
                "Households contribute different periods — read each bar beside its "
                "observed coverage."
            )
        st.altair_chart(
            charts.household_difference_chart(result.households_frame), width="stretch"
        )
        with st.expander(
            f"Per household ({t.households:,} rows) — difference beside observed coverage"
        ):
            st.dataframe(
                fmt_comparison_table(result.households_frame),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                f"Observed coverage is charged readings against the {result.schedule_slots_in_period:,} "
                "schedule labels in this period — label coverage, never annualised, and not "
                "proof that every physical interval was metered."
            )
    with st.expander("Assumptions, price provenance and what this does not show"):
        st.markdown(
            f"""
- **A1** — {ASSUMPTION_TEXT}
- **A2** — {fcmp.A2_TEXT}
- **Flat price** — `{price.tariff_group}` / `{price.band_label}`: {price.price_pence_per_kwh} p/kWh
  (£{price.price_gbp_per_kwh}/kWh), catalogue `{price.catalogue_version}`, evidence
  **{price.evidence_label}**, validity **{price.validity}**. Read from this build's own price
  dimension (`{relations.dim_price}`), not from the current catalogue file.
- **Arithmetic** — per charged reading, `consumption_kwh × price` in exact decimal, summed;
  rounded only here for display. The per-row sum equals the kWh total × price because nothing
  is rounded, and the code asserts it.
- **Run** — `{run_id}` on the {relations.label} route; definition `{result.definition}`.
- **Not shown** — what anyone paid (no standing charge, levy or tax; these households were on
  the dynamic tariff and may have consumed differently on a flat one), any behavioural
  response, any advice about tariffs today, and anything about London beyond this sample.
"""
        )


def render_landing(
    database: Path, relations: ta.Relations, context: reads.ReadContext
) -> None:
    """The first screen: the same electricity priced two ways, for the whole scenario.

    Three questions answerable without opening a document -- what was compared, what
    varied across households, and what the result does not establish -- with the rest of
    the explorer below. A household chosen here is carried in the URL (``?household=``)
    so a view can be shared; only a household that is charged in this run is accepted.
    """
    run_id = context.run_id
    result = fcmp.compare(database, run_id, relations=relations)
    st.title("The same electricity, priced two ways")
    if isinstance(result, fcmp.Unavailable):
        st.info(
            f"The flat-price comparison is not available for this version "
            f"(`{result.kind}`): {result.reason}. The explorer below is unaffected."
        )
        return
    t, price = result.totals, result.price
    o = result.outcomes
    first = (ta.schedule_bounds(database, relations=relations) or (None, None))[0]
    st.caption(
        f"**Historical scenario, {first:%Y} · {t.households} time-of-use households from "
        f"the Low Carbon London trial · the same {fmt_count(t.readings)} charged half-hour "
        f"readings priced under the dynamic tariff they were on (A1) and, hypothetically, "
        f"at the trial's documented flat price of {price.price_pence_per_kwh} p/kWh (A2).** "
        "Coverage varies by household. Not a bill, a saving or advice."
        if first
        else "Historical scenario. Not a bill, a saving or advice."
    )
    m = st.columns(4)
    m[0].metric(
        "Dynamic energy charge",
        fmt_gbp(ta.round_money(t.dynamic)),
        help=f"Exact: £{t.dynamic}. The scenario charge under A1.",
    )
    m[1].metric(
        "Flat-price energy charge",
        fmt_gbp(ta.round_money(t.flat)),
        help=f"Exact: £{t.flat}. {t.kwh} kWh × £{price.price_gbp_per_kwh}/kWh under A2.",
    )
    m[2].metric(
        "Flat minus dynamic",
        fmt_signed_gbp(ta.round_money(t.difference)),
        help=f"Exact: £{t.difference}. Positive: the dynamic scenario is lower.",
    )
    m[3].metric(
        "As % of flat-price charge",
        "undefined" if t.pct_of_flat is None else fmt_signed_pct(t.pct_of_flat),
        help="Denominator: the flat-price energy charge.",
    )
    st.markdown(
        f"**For this recorded consumption the dynamic tariff came out "
        f"{'lower' if t.difference > 0 else 'higher' if t.difference < 0 else 'equal'}.** "
        f"Under it, **{o['lower']} households are lower, {o['higher']} higher and "
        f"{o['equal']} equal** — positive bars below mean the dynamic scenario is lower "
        "for that household; classified on exact differences."
    )
    st.altair_chart(
        charts.household_pct_difference_chart(result.households_frame), width="stretch"
    )
    st.caption(
        "A household marked *coverage* is charged for far fewer of the schedule's "
        f"{result.schedule_slots_in_period:,} half-hour labels than the others; its figure "
        "covers only the days it has readings for and is not scaled up."
    )

    # ---- inspect one household; the choice travels in the URL
    ordered = sorted(
        result.households, key=lambda r: Decimal(r["pct_of_flat_exact"] or 0)
    )
    ids = [r["household_id"] for r in ordered]
    wanted = st.query_params.get("household")
    default = ids.index(wanted) if wanted in ids else len(ids) - 1
    cols = st.columns([1.2, 3])
    pick = cols[0].selectbox(
        "Look at one household", ids, index=default, key="landing-household"
    )
    if st.query_params.get("household") != pick:
        st.query_params["household"] = pick
    row = next(r for r in result.households if r["household_id"] == pick)
    cov = row["coverage_share"]
    with cols[1]:
        st.markdown(
            f"**{pick}** — charged for **{fmt_count(row['charged_readings'])}** of "
            f"{result.schedule_slots_in_period:,} half-hour labels "
            f"({fmt_pct(cov) if cov is not None else '—'} observed coverage), "
            f"{row['first_charged_date']} to {row['last_charged_date']}. Dynamic "
            f"**{fmt_gbp(ta.round_money(Decimal(row['dynamic_charge_gbp_exact'])))}**, "
            f"flat-price **{fmt_gbp(ta.round_money(Decimal(row['flat_charge_gbp_exact'])))}**, "
            f"difference **{fmt_signed_gbp(ta.round_money(Decimal(row['difference_exact'])))}** "
            + (
                f"(**{fmt_signed_pct(Decimal(row['pct_of_flat_exact']))}** of its flat-price charge)"
                if row["pct_of_flat_exact"] is not None
                else "(percentage undefined)"
            )
            + f" — **{row['outcome_under_dynamic']}** under the dynamic scenario."
        )
        bands = ta.band_summary(database, run_id, household=pick, relations=relations)
        if not bands.empty:
            st.dataframe(fmt_band_table(bands), width="stretch", hide_index=True)
            st.caption(
                "Where its consumption fell by price band. A larger share in `High` "
                "(67.20p) narrows the gap to the flat price; a larger share in `Low` "
                "(3.99p) widens it."
            )
    with st.expander("Methods, assumptions and what this does not show"):
        st.markdown(
            f"""
- **A1** — {ASSUMPTION_TEXT}
- **A2** — {fcmp.A2_TEXT}
- **Flat price** — {price.price_pence_per_kwh} p/kWh, catalogue `{price.catalogue_version}`,
  **{price.evidence_label}**, validity **{price.validity}**; read from this build's own price
  dimension.
- **Arithmetic** — per charged reading, `consumption_kwh × price` in exact decimal, summed;
  rounded only for display. Percentages use the flat-price charge as denominator.
- **Source** — {context.label}.
- **Not shown** — what anyone paid or saved (no standing charge, levy or tax; these households
  were on the dynamic tariff and might have consumed differently on a flat one), any behavioural
  response, any advice about tariffs today, whether a particular clock time is cheaper (the
  schedule changed daily), or anything about London beyond this sample.
"""
        )


# --------------------------------------------------------------- data source
available = sorted(WAREHOUSE_DIR.glob("*.duckdb")) if WAREHOUSE_DIR.is_dir() else []

st.sidebar.header("Data source")
# Two explicitly different things to look at, never blended: a mutable warehouse file
# you pick yourself, or whatever is published right now. The publication is resolved
# ONCE here and the resolved context is threaded through every tab below, so a promotion
# part-way through a render cannot make one tab disagree with another.
snapshot_configured = sel.serving_directory() is not None
if snapshot_configured and not available:
    # A deployment: one served snapshot, no warehouse files. Offering "Warehouse file"
    # would be a control whose only effect is an error, so it is not offered.
    mode = sel.PUBLISHED_MODE
    st.sidebar.caption("Serving a published snapshot; no warehouse files on this host.")
else:
    mode = st.sidebar.radio(
        "Source",
        sel.MODES,
        index=1 if snapshot_configured else 0,
        key="source-mode",
        help=(
            "Warehouse file: a file under data/warehouse, built by build-tariff-scenario. "
            "Published version: the sealed dbt build the publication manifest names."
        ),
    )

picked: Path | None = None
hidden_pick: Path | None = None
chosen: ds.Dataset | None = None
if mode == sel.WAREHOUSE_MODE:
    # The warehouse picker exists only in this mode. In published mode it would be a
    # control with no effect, which is worse than no control.
    if not available:
        st.error(
            f"No database in `{WAREHOUSE_DIR}/`. Load one first:\n\n"
            "`uv run ingest-member --demo --database data/warehouse/demo.duckdb`"
        )
        st.stop()
    entries = ds.catalogue(available, default=DEFAULT_DATABASE)
    show_comparisons = st.sidebar.checkbox(
        "Show comparison warehouses",
        value=False,
        key=COMPARISON_KEY,
        help=(
            "Files kept for one past investigation (REC-001): a replayed baseline and "
            "the same sample with an extra source file. Useful to open deliberately, "
            "misleading to offer beside the main sample."
        ),
    )
    visible = [e for e in entries if show_comparisons or not e.is_comparison]
    # A selection is held by path, never by label text, so renaming a label cannot move
    # what is being read. If the held path is no longer offered -- the comparisons were
    # just hidden -- say so rather than silently substituting another file.
    if st.session_state.get(WAREHOUSE_KEY) not in {e.path for e in visible}:
        hidden_pick = st.session_state.pop(WAREHOUSE_KEY, None)
    labels = ds.display_labels(visible)
    picked = st.sidebar.radio(
        "Dataset",
        [e.path for e in visible],
        index=next((i for i, e in enumerate(visible) if e.path == DEFAULT_DATABASE), 0),
        format_func=labels.get,
        key=WAREHOUSE_KEY,
        help="Which warehouse file to inspect.",
    )
    chosen = next(e for e in visible if e.path == picked)
    if hidden_pick is not None:
        st.sidebar.info(
            f"`{hidden_pick.name}` is a comparison warehouse and is now hidden, so "
            f"**{chosen.label}** is selected instead. Tick *Show comparison "
            "warehouses* to choose it again."
        )

selected = sel.resolve(mode, picked)

if not selected.ready:
    # Explicit absence, never a quiet fall back to the local warehouse: "published"
    # must mean published. An absent publication is an ordinary state and is said
    # neutrally; only a publication that exists and fails validation is an error.
    if selected.absent:
        st.sidebar.info("No published version yet")
        st.info(
            "**No published version yet.** Nothing has been promoted, so there is "
            "nothing to show here.\n\n"
            "Nothing local is shown in its place: what a *warehouse file* holds is a "
            "different question from what is published. Switch **Source** to "
            "*Warehouse file* to inspect one directly."
        )
    else:
        st.sidebar.error("Published version unavailable")
        st.error(
            "**The published version could not be read, so nothing is shown.**\n\n"
            f"{selected.unavailable}\n\n"
            "Nothing local is shown in its place: what a *warehouse file* holds is a "
            "different question from what is published."
        )
    with st.expander("How to publish a version"):
        st.markdown(
            "```bash\n"
            "uv run build-candidate --source data/warehouse/energy.duckdb\n"
            "uv run publication promote <candidate> --expect-published none\n"
            "```\n"
            "`uv run publication status` reports what is published now, and "
            "`uv run publication inventory` lists every version file and its role."
        )
    st.stop()

database = selected.database
relations = selected.relations
if selected.is_published:
    context = selected.context
    if context.role == "serving snapshot":
        st.sidebar.success(f"Published {context.version} · serving snapshot")
    else:
        st.sidebar.success(f"Published {context.version}")
    st.sidebar.caption(
        f"File: `{database.name}` · dbt run `{context.run_id[:20]}…`. Tariff figures "
        "come from the sealed dbt build; readings and load history come from the same "
        "file. Resolved once for this page."
    )
else:
    st.sidebar.caption(
        f"**{chosen.label}** — {chosen.note}.\n\n{chosen.detail}. A warehouse file you "
        "selected, **not** a published version. Loaded files are listed under Source "
        "records."
    )

people = q.households(database)
if not people:
    st.warning("That database has no readings yet.")
    st.stop()

# ------------------------------------------------------------- landing view
if selected.is_published:
    render_landing(database, relations, selected.context)
    st.divider()

# ------------------------------------------------------- household and period
st.title("Household energy explorer")
st.caption(
    "Historical sample · Partial source coverage · Source timezone unresolved — "
    "details under *About this data* below."
)

# A stored selection can outlive the dataset it came from -- switching from the real
# sample to the demo leaves a household id that no longer exists. Clear it before the
# widget is built, or Streamlit raises on a value that is not in the options.
if st.session_state.get(HOUSEHOLD_KEY) not in people:
    st.session_state.pop(HOUSEHOLD_KEY, None)

row = st.columns([2, 2, 1.3, 1.3])
household = row[0].selectbox(
    f"Household ({len(people)} available)", people, key=HOUSEHOLD_KEY
)
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

overview_tab, quality_tab, tariff_tab, forecast_tab, records_tab = st.tabs(
    [
        "Overview",
        "Data quality",
        "Tariff scenario",
        "Forecast (backtest)",
        "Source records",
    ]
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
        # Any day with rows is worth looking at, including one whose only rows are
        # off-grid or in conflict. Keying this on contributing readings hid both,
        # because a conflict day contributes none by policy.
        days_with_data = list(daily.loc[daily["has_rows"], "source_date"].dt.date)
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

# The tariff section is written LAST on purpose. Streamlit executes a script top to
# bottom, so an unhandled failure here would stop everything below it from rendering.
# Placing it after the other three tabs means their content is already on the page.
# Tab order in the UI comes from st.tabs above, not from this order.
# ============================================================ TARIFF SCENARIO
with tariff_tab:
    # Schema compatibility is checked before anything is read, so a database this
    # process cannot read produces a recovery instruction here rather than a raw
    # database error that takes the rest of the page with it. Only this recognised
    # condition is contained: any other failure is still allowed to surface.
    if selected.uses_dbt_build:
        # The published route: relations, run id and identity all come from the
        # validated context. main.scenario_run is deliberately never consulted -- it
        # holds the Python scenario copied into the same file, which is a different run.
        availability = ta.ScenarioAvailability(ta.READY)
        header = sel.header_from_context(
            selected.context,
            assumption_ids=ta.assumption_ids(
                database, selected.context.run_id, relations=relations
            ),
            total_charge_exact=ta.total_charge_exact(
                database, selected.context.run_id, relations=relations
            ),
            coverage=ta.schedule_bounds(database, relations=relations),
        )
        run_id = selected.context.run_id
    else:
        availability = ta.scenario_availability(database)
        legacy_run = ta.latest_run(database) if availability.ready else None
        header = (
            sel.header_from_run(legacy_run, database)
            if legacy_run is not None
            else None
        )
        run_id = legacy_run.run_id if legacy_run is not None else None
    if header is None:
        if availability.state == ta.INCOMPATIBLE:
            st.error(
                "**The tariff scenario in this database cannot be read by the code "
                f"this app is running.** {availability.diagnosis}"
            )
            st.markdown(
                f"""
**Recovery.** {availability.recovery}

```bash
# 1. restart the app (loads the current code; rebuilds nothing)
PYTHONPATH=src uv run streamlit run src/energy_reconciliation/explorer/app.py

# 2. only if the message survives a restart, rebuild the derived tariff tables
uv run build-tariff-scenario --database {database}
```

Your readings, load history and captured baselines are untouched either way — the
tariff tables are derived, and rebuilding them reads nothing but the source archive
and the workbook. The other three tabs are unaffected and work normally.
"""
            )
        else:
            st.info(
                "No tariff scenario has been built for this database.\n\n"
                f"`uv run build-tariff-scenario --database {database}`  — add `--demo` "
                "to use the synthetic one-day schedule instead of the real workbook."
            )
    else:
        coverage = ta.schedule_bounds(database, relations=relations)
        cov_first, cov_last = coverage if coverage else (None, None)

        # --- one short, always-visible statement; the detail is in the expanders ---
        st.markdown(
            f'<span class="status-review">Scenario under assumption '
            f"{header.assumption_ids} — not a bill.</span> A consumption timestamp label "
            "and a schedule label are treated as the same half hour. That is "
            "**not established**. Charge = consumption × band price only; "
            "**no separate tax adjustment is applied**.",
            unsafe_allow_html=True,
        )
        st.caption(f"Source of these figures: {header.route}.")
        if header.is_synthetic:
            st.warning(header.synthetic_note)
        else:
            st.caption(
                f"Real evidence: schedule read from `{header.schedule_source}`, "
                f"SHA-256 `{header.schedule_sha256[:12]}…`"
                + (
                    f", {header.schedule_rows:,} labels."
                    if header.schedule_rows is not None
                    else "."
                )
            )

        # ------------------------------------------------- controls for THIS tab
        ctl = st.columns([2.4, 1.5, 1.1, 1.1])
        view = ctl[0].segmented_control(
            "View",
            list(SCENARIO_VIEWS),
            default=SCENARIO_VIEWS[0],
            key="scenario-view",
            help="Each view has one scope. Nothing is mixed between them.",
        )
        if view is None:
            view = SCENARIO_VIEWS[0]
        span = ctl[1].segmented_control(
            "Scenario period",
            list(SCENARIO_PERIODS),
            default=SCENARIO_PERIODS[0],
            key="scenario-span",
            help="Bounded by the schedule's own coverage. Separate from the period "
            "at the top of the page.",
        )
        if span is None:
            span = SCENARIO_PERIODS[0]

        s_start, s_end = cov_first, cov_last
        if coverage and span == "Custom":
            s_start = ctl[2].date_input(
                "Scenario start",
                cov_first,
                min_value=cov_first,
                max_value=cov_last,
                key="scenario-start",
            )
            s_end = ctl[3].date_input(
                "Scenario end",
                cov_last,
                min_value=cov_first,
                max_value=cov_last,
                key="scenario-end",
            )
            if s_start > s_end:
                st.error(
                    f"Scenario start ({fmt_day(s_start)}) is after scenario end "
                    f"({fmt_day(s_end)})."
                )
                st.stop()
        else:
            ctl[2].markdown(
                f"<div class='ctl-note'>From<br><b>{fmt_day(cov_first)}</b></div>"
                if cov_first
                else "",
                unsafe_allow_html=True,
            )
            ctl[3].markdown(
                f"<div class='ctl-note'>To<br><b>{fmt_day(cov_last)}</b></div>"
                if cov_last
                else "",
                unsafe_allow_html=True,
            )

        st.caption(
            f"**These two controls affect this tab only.** The scenario period is "
            f"{fmt_period(s_start, s_end) if s_start else 'unavailable'}, bounded by "
            f"the schedule's coverage ({fmt_day(cov_first)} – {fmt_day(cov_last)}). "
            "The **household** selector at the top of the page chooses which household "
            "the first view describes; the **period** selector at the top does **not** "
            "apply here — it drives Overview, Data quality and Source records."
        )
        st.divider()

        # Set by whichever view rendered, so "Calculation details" reports the exact
        # figures for the selection actually on screen and never for a different one.
        selection_totals: tuple[int, str, str] | None = None

        # ============================================ VIEW 1 — one household
        if view == SCENARIO_VIEWS[0]:
            st.markdown(f"#### Selected household — {household}")
            mine = ta.band_summary(
                database,
                run_id,
                household=household,
                start=s_start,
                end=s_end,
                relations=relations,
            )
            if mine.empty:
                groups = ta.household_tariff_groups(
                    database, household, relations=relations
                )
                # Scoped to the scenario period on purpose: a period count must never
                # silently become a whole-history count. Whole history is shown only
                # when the period holds nothing, and is labelled as whole history.
                reasons = ta.exclusion_breakdown(
                    database,
                    run_id,
                    household=household,
                    start=s_start,
                    end=s_end,
                    relations=relations,
                )
                scope_label = f"in {fmt_period(s_start, s_end)}"
                if reasons.empty:
                    reasons = ta.exclusion_breakdown(
                        database, run_id, household=household, relations=relations
                    )
                    scope_label = (
                        "in its **whole loaded history** — it has no readings at all "
                        f"in {fmt_period(s_start, s_end)}"
                    )
                if reasons.empty:
                    st.info(
                        f"{household} has no charged readings and no excluded readings "
                        "in this scenario: it has no rows in the loaded members."
                    )
                else:
                    top = reasons.iloc[0]
                    st.info(
                        f"**{household} has no charged readings in this selection.** "
                        f"Measured for this household {scope_label}: "
                        f"{int(top['readings']):,} of its "
                        f"{int(reasons['readings'].sum()):,} distinct readings are "
                        f"excluded as **`{top['exclusion_reason']}`**, spanning "
                        f"{top['first_date']} to {top['last_date']}. It is recorded "
                        f"under tariff group **{', '.join(groups) or 'none'}**, and the "
                        f"band prices apply to `{header.tariff_group}`."
                    )
                    st.dataframe(
                        fmt_reason_table(reasons),
                        width="stretch",
                        hide_index=True,
                    )
                pickable = ta.charged_households(
                    database, run_id, start=s_start, end=s_end, relations=relations
                )
                if pickable:
                    st.markdown(
                        f"**Look at a charged household instead** — "
                        f"{len(pickable):,} household(s) are charged in this run. "
                        "Nothing changes until you press the button."
                    )
                    pick_cols = st.columns([2, 1, 3])
                    target = pick_cols[0].selectbox(
                        "Charged household",
                        pickable,
                        key=f"tou-pick-{database.name}",
                        label_visibility="collapsed",
                    )
                    pick_cols[1].button(
                        "Switch to it",
                        on_click=select_household,
                        args=(target,),
                        width="stretch",
                    )
            else:
                selection_totals = render_band_view(
                    mine,
                    scope_note=(
                        f"{household}, {fmt_period(s_start, s_end)}, "
                        f"schedule `{header.schedule_source}`"
                    ),
                    insights=ta.selection_insights(
                        database,
                        run_id,
                        household,
                        s_start,
                        s_end,
                        relations=relations,
                    ),
                )
                st.altair_chart(
                    charts.band_kwh_by_hour_chart(
                        ta.household_band_distribution(
                            database,
                            run_id,
                            household=household,
                            start=s_start,
                            end=s_end,
                        )
                    ),
                    width="stretch",
                )
                st.caption(
                    f"Charged kWh for **{household}** by the hour in the source "
                    "timestamp. The hour is read from the label as recorded; no "
                    "timezone is applied, because none is established."
                )
                render_flat_comparison(
                    database, run_id, relations, household, s_start, s_end
                )

        # ======================================= VIEW 2 — the loaded ToU sample
        elif view == SCENARIO_VIEWS[1]:
            everyone = ta.band_summary(
                database, run_id, start=s_start, end=s_end, relations=relations
            )
            people_charged = ta.charged_households(
                database, run_id, start=s_start, end=s_end, relations=relations
            )
            st.markdown(
                f"#### Loaded {header.tariff_group} sample — "
                f"{len(people_charged):,} charged household(s)"
            )
            st.caption(
                "A **bounded, non-representative subset**: the households that happen "
                "to occupy the loaded members, not a sample drawn from the trial. "
                "Nothing here describes the trial, London, or anyone else."
            )
            selection_totals = render_band_view(
                everyone,
                scope_note=(
                    f"all charged households, {fmt_period(s_start, s_end)}, "
                    f"schedule `{header.schedule_source}`"
                ),
                insights=ta.selection_insights(
                    database, run_id, None, s_start, s_end, relations=relations
                ),
            )
            if not everyone.empty:
                st.altair_chart(
                    charts.band_kwh_by_hour_chart(
                        ta.household_band_distribution(
                            database,
                            run_id,
                            start=s_start,
                            end=s_end,
                            relations=relations,
                        )
                    ),
                    width="stretch",
                )
                st.caption(
                    "Charged kWh by the hour in the source timestamp, across every "
                    "charged household. Consumption and an expensive band falling in "
                    "the same hours is a coincidence of timing, not evidence of a "
                    "response."
                )
                totals = ta.household_totals(
                    database, run_id, start=s_start, end=s_end, relations=relations
                )
                with st.expander(
                    f"Per household ({len(totals):,} rows) — read the charge beside "
                    "its charged-reading count"
                ):
                    st.dataframe(
                        fmt_household_table(totals),
                        width="stretch",
                        hide_index=True,
                    )
                    st.caption(
                        "A household charged for far fewer readings than its "
                        "neighbours has **limited observed coverage** in the loaded "
                        "members. Its smaller charge follows from that, and says "
                        "nothing about how much electricity it used. Why readings are "
                        "absent is not established."
                    )
                render_flat_comparison(
                    database, run_id, relations, None, s_start, s_end
                )

        # ========================================= VIEW 3 — the schedule itself
        else:
            st.markdown(f"#### Published schedule — {header.schedule_source}")
            st.caption(
                "Describes the price schedule itself. **Independent of which "
                "households are loaded and of the scenario period above**, which is "
                "why no household or period is applied to this view."
            )
            totals = ta.schedule_totals(database, relations=relations)
            st.altair_chart(
                charts.schedule_hour_chart(
                    ta.schedule_band_distribution(database, relations=relations)
                ),
                width="stretch",
            )
            slots = totals.attrs["denominator_slots"]
            st.caption(
                f"Half-hour slots per band by hour, out of **{slots:,} slots** in the "
                f"schedule, covering {fmt_day(cov_first)} – {fmt_day(cov_last)}."
            )
            st.dataframe(fmt_schedule_table(totals), width="stretch", hide_index=True)
            st.dataframe(
                fmt_price_table(ta.price_catalogue(database, relations=relations)),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Prices are **publisher-documented**, quoted from the dataset page. "
                "The workbook contains no price at all. Validity is a half-open "
                "interval: *from* is the first instant a price applies, *until* is the "
                "first instant it no longer does, so a whole year reads "
                "2013-01-01 → 2014-01-01. **UNKNOWN** means the publisher gives the "
                "price without saying when it applied; it is never defaulted to the "
                "span of the data, and a price with unknown validity charges nothing."
            )

        # ----------------------------------------------- detail, on demand only
        st.divider()
        with st.expander("Assumption A1 in full"):
            # The Python route records the wording with the run. A dbt build stamps only
            # the identifier on every charged row, so the wording shown for it is this
            # code's text for that identifier, said plainly rather than implied.
            if header.assumption_text is not None:
                st.markdown(header.assumption_text)
            else:
                st.caption(
                    f"Every charged row in this build carries assumption "
                    f"`{header.assumption_ids}`. The wording below is this code's text "
                    "for that identifier; a dbt build records the identifier, not the "
                    "prose."
                )
                st.markdown(ASSUMPTION_TEXT)
            st.markdown(
                """
**Two things that are not evidence for A1.**

- *Regularity is not a timezone.* A schedule of exact half-hour steps with both
  clock-change hours present once shows the **schedule** is a fixed nominal grid. It
  says nothing about the convention used by the consumption timestamps.
- *A unique key is not semantic alignment.* The schedule label is a primary key and a
  duplicate is refused before loading, so a join **cannot multiply** consumption rows.
  That is arithmetic. It is not evidence that the two label sets mean the same half hour.

*Repeated identical labels* stay semantically unresolved. Collapsing them is our
analytical resolution, not proof that two rows carrying one label are one physical
interval.
"""
            )

        with st.expander("What was counted, and what was not charged"):
            led = (
                selected.context.accounting()
                if selected.uses_dbt_build
                else ta.accounting(database, run_id)
            )
            ladder_note = (
                " Counted from the built tables: a dbt build records no ladder row, so "
                "each figure here is a count rather than something it wrote down."
                if led.derived
                else " Read from the run record written when the scenario was built."
            )
            st.markdown(
                f"""
Whole run, every loaded member, unscoped by the period above.{ladder_note}

| | |
|---|---:|
| Rows recorded in this database | {led.raw_rows:,} |
| Collapsed by policy (identical rows, equivalent representations) | {led.rows_collapsed_by_policy:,} |
| **Distinct readings** | **{led.distinct_readings:,}** |
| Charged | {led.included_readings:,} |
| Excluded, each with a reason | {led.excluded_readings:,} |
| Reconciles | **{led.reconciles}** |

**No excluded reading becomes a zero charge.** It has no charge at all.
"""
            )
            st.dataframe(
                fmt_reason_table(
                    ta.exclusion_breakdown(
                        database, run_id, relations=relations
                    ).rename(columns={"readings": "readings"})
                ),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "A reading can meet several conditions at once. `exclusion_reason` is "
                "the first that applies in a fixed order — ineligible group, outside "
                "the schedule period, conflicting label, off-grid, missing value, "
                "unmatched label, unpriced band — and every condition is *also* stored "
                "as its own flag, so the ordering hides nothing."
            )

        if selection_totals is None:
            exact_block = (
                "**Exact totals for the current selection.** The "
                f"*{SCENARIO_VIEWS[2]}* view describes the schedule, which carries no "
                "charge, so there is no selection total to report here. The "
                "whole-run figure is in the run identity below."
            )
        else:
            exact_block = (
                "**Exact, unrounded totals for the current selection**\n\n"
                "| | |\n|---|---|\n"
                f"| Scope | {view}, {fmt_period(s_start, s_end)} |\n"
                f"| Charged readings | {selection_totals[0]:,} |\n"
                f"| Charged kWh (exact) | `{selection_totals[1]}` |\n"
                f"| Scenario charge (exact) | `£{selection_totals[2]}` |\n"
            )

        identity_table = "\n".join(
            f"| {name} | {value} |" for name, value in header.identity_rows
        )
        with st.expander("Calculation details and full precision"):
            st.markdown(
                f"""
`energy_charge_gbp = consumption_kwh × price_pence_per_kwh ÷ 100`, in `Decimal`.

- **No row is ever rounded.** Rounding happens once, here, for display: money to 2
  decimal places, energy to 3, shares to 4, all half up. Shares are each rounded
  independently, so a column of them need not total exactly 100%.
- The `÷ 100` is done once in Python when the price catalogue is built, **not in SQL**:
  DuckDB evaluates a `DECIMAL` divided by 100 as a binary float.
- **What this charge is.** {ta.CHARGE_SCOPE}
- **Geography.** No geographic breakdown is produced. One would be legitimate only from
  metadata properly linked to these households; none has been linked.

{exact_block}
**Run identity — what would have to match to reproduce this**

| | |
|---|---|
{identity_table}

{header.not_recorded}
"""
            )

# ============================================================ FORECAST (BACKTEST)
with forecast_tab:
    st.markdown(
        '<span class="status-review">Historical backtest — not a live forecast.</span> '
        "Every prediction was made from data dated on or before its **forecast origin** "
        "and scored against what was recorded afterwards.",
        unsafe_allow_html=True,
    )
    st.markdown(
        "**Prediction target:** one household's recorded consumption, in kWh, grouped by "
        "**source-date label**. Correspondence to local calendar days is not established."
    )

    report = fc.load_latest_report()
    prior = fc.load_prior_report()
    # Content, not file names: each report's own dataset digest and every displayed
    # context figure are recomputed from the selected database, in one scan for both
    # reports. The file the report was run against is kept as provenance only.
    # The resolved selection is what is assessed: for a published version that is the
    # context, used as passed, so the forecast check never re-resolves the manifest.
    fits = sel.forecast_applicability(selected, {"fore": report, "prior": prior})
    fit, prior_fit = fits["fore"], fits["prior"]
    if report is None:
        st.info(
            "No forecast experiment has been run for this database yet.\n\n"
            f"`uv run run-forecast-experiment --database {database}`"
        )
    elif not fit.applicable:
        st.warning(fc.applicability_message(fit, database))
    else:
        selectable = [h["household_id"] for h in report["households"]]
        cfg = report["config"]
        f = report["feasibility"]
        sel = report.get("selection", {})
        if selectable and all(h.startswith("DEMO") for h in selectable):
            st.warning(
                "**Synthetic evidence.** This experiment was run over invented demo "
                "households. Nothing on this tab is a measurement of the real trial."
            )

        st.markdown(
            f"**Dataset** `{database.name}` · **cohort** "
            f"{fc.describe_cohort(sel)} · **retrospective clean-run benchmark**: each "
            "household's longest clean run was chosen over its whole history, holdout "
            "included, so this is not operational accuracy across all households."
        )
        st.caption(fc.applicability_note(fit, database))
        scope = st.columns(4)
        scope[0].metric(
            "Households evaluated",
            fmt_count(len(selectable)),
            help=(
                f"{f['eligible_households']:,} of {f['households']:,} loaded households "
                f"have a contiguous usable run of at least {f['min_run_days']} days; "
                f"the experiment is bounded to the first {cfg['household_limit']} by "
                "household id — a documented rule, not a choice based on results."
            ),
        )
        scope[1].metric(
            "Horizon",
            f"{cfg['horizon']} days",
            help="Each origin predicts the next 7 source dates, scored separately.",
        )
        scope[2].metric(
            "Holdout",
            f"{cfg['holdout_days']} days",
            help="The final days of each household's run, scored once at the end.",
        )
        hold = report["evaluation"]["holdout"]
        dev = report["evaluation"]["development"]
        scope[3].metric(
            "Holdout household–source-date pairs",
            fmt_count(
                hold.get("unique_household_targets", hold["scored_predictions"] // 3)
            ),
            help=(
                "Each (household, target source date) pair is predicted once by every "
                f"model, so {hold['scored_predictions']:,} scored predictions across the "
                f"three. Development: "
                f"{dev.get('unique_household_targets', dev['scored_predictions'] // 3):,} "
                f"pairs. Distinct from the {f['usable_household_days']:,} usable "
                f"household-days across all {f['households']} loaded households, which "
                "is a warehouse-level figure, not this cohort."
            ),
        )
        with st.expander("What these terms mean"):
            st.markdown(
                f"""
- **Source-date label.** The date part of a timestamp exactly as the source wrote it.
  Grouping by it is a grouping, not a claim: it is not a settlement day, its
  correspondence to a local calendar day is not established, and {f["expected_intervals"]}
  observed labels are not proof the meter covered the whole day.
- **Usable day.** All {f["expected_intervals"]} nominal labels carry a finite value, no
  missing-value token is recorded, and no label disagrees with itself. Nothing is filled
  in, bridged or treated as whole when it is partial.
- **Cohort.** Households with one contiguous usable run of at least {f["min_run_days"]}
  days, taken in household-id order and bounded to {cfg["household_limit"]}. Ids track
  source members, so the mix by tariff group and member above is a property of that
  rule, not a balanced sample.
- **Retrospective.** Runs were found with hindsight over each household's whole history.
  {sel.get("runs_ending_at_warehouse_end", "?")} of {len(selectable)} runs reach the
  warehouse's last date; the rest end at a later data-quality event.
- **Not a bill, a saving, an appliance claim or a statement about tariff response.**
  Nothing here bears on tariff assumption A1.
"""
            )

        st.divider()
        st.markdown("#### One forecast origin")
        st.caption(
            "**Example scope.** The three controls below choose one household, one split "
            "and one origin, and show that origin's seven predictions. They do not change "
            "the aggregate comparison further down, which has its own control."
        )
        pick = st.columns([2, 2, 2])
        household_pick = pick[0].selectbox(
            "Household",
            selectable,
            index=selectable.index(household) if household in selectable else 0,
            key="forecast-household",
            help="Households eligible for the experiment. The sidebar household is "
            "pre-selected when it qualifies.",
        )
        series = fc.series_for(database, household_pick)
        if series is None:
            st.info(f"{household_pick} no longer has a long enough usable run.")
        else:
            development, holdout = fc.origins_for(series, fc.config_from(cfg))
            split_pick = pick[1].segmented_control(
                "Split",
                ["development", "holdout"],
                default="holdout",
                key="forecast-split",
                help="The holdout is the final window, scored once. Nothing was tuned "
                "on it.",
            )
            split_pick = split_pick or "holdout"
            origins = holdout if split_pick == "holdout" else development
            if not origins:
                st.info(f"No {split_pick} origins for this household.")
            else:
                origin = pick[2].selectbox(
                    "Forecast origin",
                    origins,
                    index=len(origins) - 1,
                    format_func=lambda d: f"{d:%a %-d %b %Y}",
                    key=f"forecast-origin-{household_pick}-{split_pick}",
                    help="Predictions use only data dated on or before this date.",
                )
                st.caption(
                    f"**{household_pick}** · origin **{origin:%A %-d %B %Y}** · "
                    f"predicting the next **{cfg['horizon']}** source dates "
                    f"(**{origin + timedelta(days=1):%-d %b}** to "
                    f"**{origin + timedelta(days=cfg['horizon']):%-d %b %Y}**) · "
                    f"split **{split_pick}** · usable run "
                    f"{series.run_start:%-d %b %Y} – {series.run_end:%-d %b %Y}."
                )
                rows = fc.observed_vs_predicted(
                    series, origin, fc.default_models(), fc.config_from(cfg)
                )
                st.altair_chart(
                    charts.observed_vs_predicted_chart(fc.long_frame(rows)),
                    width="stretch",
                )
                st.caption(
                    "**Observed** is the recorded total for that source date; the other "
                    "three are predictions made at the origin, distinguished by colour, "
                    "line pattern and point shape. Every prediction used only dates on or "
                    "before the origin; a point that is absent was declined, not forecast "
                    "as zero. Identifiers for export are listed under *Method*."
                )
                st.dataframe(fc.origin_table(rows), width="stretch", hide_index=True)

        st.divider()
        st.markdown("#### Baseline comparison")
        st.caption(
            "**Aggregate scope.** Every household and origin in the chosen split, pooled. "
            "Independent of the example household and origin above."
        )
        which = (
            st.segmented_control(
                "Results for",
                ["holdout", "development"],
                default="holdout",
                key="forecast-results-split",
            )
            or "holdout"
        )
        section = report["evaluation"][which]
        st.caption(
            f"**{which}** · {section['scored_predictions']:,} scored predictions over "
            f"{section.get('households', '?')} households and "
            f"{section.get('unique_household_targets', '?'):,} distinct target days · "
            f"{section['excluded_predictions']:,} excluded. MAE pools predictions with "
            "equal weight, in kWh per source date. All models are scored on identical "
            "cases."
            + (
                f" The holdout is rolling: "
                f"{section.get('predictions_with_an_input_inside_the_holdout_window', 0):,} "
                "of its predictions use earlier holdout days as inputs, never later ones."
                if which == "holdout"
                else ""
            )
        )
        left, right = st.columns(2)
        with left:
            st.altair_chart(
                charts.model_error_chart(
                    fc.model_frame(section), f"MAE (kWh) — {which}"
                ),
                width="stretch",
            )
        with right:
            st.altair_chart(
                charts.horizon_error_chart(fc.horizon_frame(section)), width="stretch"
            )
        st.dataframe(fc.model_table(section), width="stretch", hide_index=True)

        sweep = report.get("weeks_sweep")
        if sweep:
            with st.expander("Does averaging more weeks help? (development only)"):
                st.dataframe(fc.sweep_table(sweep), width="stretch", hide_index=True)
                st.caption(
                    f"Compared on the {sweep['compared_on_common_triples']:,} cases every "
                    f"candidate predicted; {sweep['declined_by_some_candidate']:,} early "
                    "cases were declined by the longest-history candidate, so the 4-week "
                    "figure here is over a later, smaller frame than the headline one. "
                    f"{sweep['note']}"
                )

        if prior and not prior_fit.applicable:
            with st.expander(
                "A different experiment — eligibility from prior data only (I-08)"
            ):
                st.warning(fc.applicability_message(prior_fit, database))
        elif prior:
            with st.expander(
                "A different experiment — eligibility from prior data only (I-08)"
            ):
                st.caption(fc.applicability_note(prior_fit, database))
                st.markdown(
                    "**A separate experiment, not a restatement of the figures above.** "
                    "FORE-001 chose households by a clean run found over their whole "
                    "history. This one decides eligibility at each origin from source "
                    "dates on or before it, over **every** household and one shared "
                    "origin calendar. The models and their settings are unchanged."
                )
                st.markdown(
                    "**The population changed first — read this before the accuracy**"
                )
                st.dataframe(
                    fc.prior_population_table(prior), width="stretch", hide_index=True
                )
                st.markdown("**Accuracy beside coverage**")
                st.dataframe(
                    fc.prior_comparison_table(prior), width="stretch", hide_index=True
                )
                st.caption(
                    "Coverage and accuracy must be read together: a model can look "
                    "better by declining harder cases, so both are shown against the "
                    "same denominator of scheduled cases. Accuracy is on the cases "
                    "**every** model scored."
                )
                st.markdown("**Shared with FORE-001, against newly included**")
                st.dataframe(
                    fc.prior_overlap_table(prior), width="stretch", hide_index=True
                )
                st.caption(
                    "The shared/new split is over the cases scored by **at least one** "
                    "model (the population table above), not the every-model frame. "
                    "Each MAE here is over the cases that model itself scored on that "
                    "side, so its count can be below the set size. Shared cases are a "
                    "correctness check; the newly included cases are where the "
                    "population differs. This is an as-of-source-date simulation, not a "
                    "reconstruction of historical production availability, and it "
                    "re-uses the same dates as FORE-001 including its already-inspected "
                    "holdout — it is **not** a fresh independent holdout. Full account: "
                    "`docs/i-08-prior-data-eligibility.md`."
                )

        with st.expander("Where the predictions fail"):
            if series is not None:
                worst = fc.worst_days(series, fc.default_models(), fc.config_from(cfg))
                st.markdown(
                    f"The ten largest absolute errors for **{household_pick}**, across "
                    "every origin in its run. **Each model's input has its own column, "
                    "so read the row against the column its model used.** *Same "
                    "weekday, previous week* repeats *Same weekday, 1 week earlier*. "
                    "*4-week weekday mean* averages the four values in *Same weekday, "
                    "4 → 1 weeks earlier*, and its prediction is exactly their mean — "
                    "so one unusual week among the four shifts it by a quarter of that "
                    "week's excess, and a target unlike all four is a miss no averaging "
                    "could avoid. *Origin day repeated* repeats *Origin day*, so its "
                    "weekday lag can be almost exact while the prediction is far out. "
                    "*Dates the model read* lists the inputs recorded with each "
                    "prediction."
                )
                st.dataframe(worst, width="stretch", hide_index=True)
            st.markdown(
                "**What these models are not given:** weather, occupancy, holidays, "
                "tariff band, price, or any other household's data. They see one "
                "household's earlier daily totals and nothing else."
            )

        with st.expander("Method, eligibility and run identity"):
            st.markdown(
                f"""
**Eligibility, fixed before any result was read.** A day is usable only when all
{f["expected_intervals"]} nominal half-hour labels carry a finite value, no missing-value
token is recorded, and no label disagrees with itself. A household is eligible when it has
one **contiguous** run of usable days of at least {f["min_run_days"]} days. Households are
chosen by that rule and by id, never by how well they forecast.

**Contiguity is a benchmark choice, not a correctness requirement.** Lag lookup is keyed by
date, so a hole never shifts what "seven days earlier" means -- the lookup returns nothing
and the model declines. Contiguity gives every household a dense frame of the same shape and
well-defined split boundaries, so the comparison is not confounded by differing decline
rates.

**Nothing is repaired.** Missing observations are not filled with zero, absent dates are
not bridged, and a partially observed date is never treated as whole. A prediction that
would depend on an unusable day is declined with a reason and excluded from scoring.

**Rolling origins.** Origins step weekly. At each one the models may use only usable
totals dated on or before it. The final {cfg["holdout_days"]} days of each run are a
holdout, scored once; its later origins may use earlier holdout days as inputs, never
later ones, and no model or parameter choice used holdout scores.

**Selection uses hindsight.** Each household's clean run was found over its whole history,
holdout included. That is a retrospective benchmark of the models, not operational
accuracy: {sel.get("runs_ending_at_warehouse_end", "?")} of {len(selectable)} runs reach
the warehouse's last date; the rest end at a later data-quality event.

**MAE, not MAPE.** The loaded data contains daily totals of exactly zero, where a
percentage error is undefined or explodes; MAPE would rank models by their behaviour on
the smallest days.

| Identity | |
|---|---|
| Dataset digest | `{report["identity"]["dataset_sha256"][:16]}…` ({fit.definition}), recomputed identically from `{database.name}` |
| Recorded against | `{report["database"]}` — the path at generation time, kept as provenance |
| Forecast code | `{report["identity"]["forecast_code_sha256"][:16]}…` |
| Configuration | `{report["identity"]["config_sha256"][:16]}…` |
| Runtime | {", ".join(f"{k} {v}" for k, v in sorted(report["identity"]["runtime"].items()))} |
| Generated | {report["generated_at_utc"]} |

**Timestamp convention.** {f["timestamp_convention"]}

**Model identifiers (as recorded in the report and tests)**

| Name on this page | Identifier |
|---|---|
| Same weekday, previous week | `seasonal_naive_7` |
| 4-week weekday mean | `weekday_mean_4` |
| Origin day repeated (reference) | `persistence_1` |
"""
            )
            if section["exclusions"]:
                st.markdown("**Excluded predictions, by reason**")
                st.dataframe(
                    fc.exclusion_frame(section), width="stretch", hide_index=True
                )
