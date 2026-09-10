# ANL-005 — The same recorded consumption priced at the flat rate

| Field | Value |
|---|---|
| Ticket | ANL-005 (from idea I-21) |
| Status | **Contract frozen 2026-09-10 before the real warehouse was queried; analysis run the same day.** Results: [`../anl-005-flat-price-comparison.md`](../anl-005-flat-price-comparison.md) |
| Depends on | ANL-002 (the scenario facts and assumption A1), ANL-003 (the read contract, `Relations`), the price catalogue (`tariff/prices.py`) |
| Out of scope | Any statement about what anyone paid or saved; behavioural response; tariff advice; representativeness; a new dbt model or stored figure |

**This document was written before the analysis ran.** Results:
[`../anl-005-flat-price-comparison.md`](../anl-005-flat-price-comparison.md).

## The question

For exactly the same selected charged readings, how does the calculated energy charge
differ between the dynamic tariff scenario (ANL-002) and the publisher-documented flat
price?

This is a **fixed-consumption historical price comparison**: the recorded consumption
is held constant and priced two ways. It does not establish actual bill savings — the
households on the dynamic tariff might have consumed differently on a flat one, and no
standing charge, levy or tax is modelled. It does not establish a behavioural response,
does not constitute tariff advice, and describes only the loaded sample.

## Assumptions, both stored on the output

- **A1** (unchanged, from ANL-002): a consumption timestamp label and a schedule label
  denote corresponding half-hour intervals. It governs which band each reading falls in.
- **A2** (new, for this comparison only): *the publisher-documented flat price is
  hypothetically applied to every selected charged reading throughout the scenario
  period.* The flat price's effective dates are **UNKNOWN** (ANL-001 §4; `prices.py`),
  which is why the price catalogue prices nothing with it and no `Std` household is
  costed. A2 is a comparison assumption, not a claim about when the price was in force.

## The frozen contract

**Population.** The charged rows of `fact_interval_charge_scenario` for the selected
run, household and source-date period — the same rows, the same selection controls and
the same period helper the tariff tab already uses. Nothing outside the charged fact is
priced: excluded readings stay excluded under both prices.

**Flat price.** Read from the **same build's** price dimension (`dim_tariff_price`,
`tariff_group = 'Std'`), through `Relations`, so a published dbt build is priced by the
catalogue it was built with and never by today's `prices.py`. Its catalogue version,
evidence label, citation and (UNKNOWN) effective dates are retained on the output. No
second price constant is introduced anywhere.

**Arithmetic.** Per charged row, `consumption_kwh × price_gbp_per_kwh` cast to
`DECIMAL(38,16)`, summed — the existing exact path, never a float. Because no rounding
occurs, this equals `SUM(consumption_kwh) × price`; the code asserts it. Rounding is for
display only.

**Reported, pooled over the selection.** Dynamic energy charge; flat-price energy
charge; **flat minus dynamic** (positive means the dynamic scenario is lower); and that
difference as a **percentage of the flat-price charge**, with the denominator named.

**Reported, per household.** The same four figures, the household's charged readings,
first and last charged date, and **observed coverage**: charged readings against the
schedule's half-hour labels in the selected period. Each household is classified
**lower / higher / equal** under the dynamic scenario by the sign of its exact
difference — never by a rounded display value. Coverage is observed label coverage and
is never annualised; households contribute different periods and the report says so.

**Two questions, kept distinct.** (1) The pooled difference for the selected readings.
(2) How that difference varies between households with their observed coverage. The
second is described only as measured: how many households fall on each side, and how
much of the pooled difference the largest household contributes.

**Explicit unavailable states, none of which hides the dynamic-tariff figures.**

| Condition | Result |
|---|---|
| No charged readings in the selection | *empty* — no totals, no zero |
| No `Std` row in the build's price dimension | *no price* |
| More than one `Std` row | *non-unique price* |
| A `Std` price that is missing, non-positive or not finite | *invalid price* |
| Flat-price charge exactly zero (all selected consumption zero) | totals shown; the percentage is *undefined*, not 0 |

**Routing.** The comparison takes `Relations` like every other tariff query. On the
published route it reads `scenario_build` facts and prices only; a fallback to the copied
`main` tables must be visible to the existing doctored-fixture test.

**Identity.** Nothing here changes a stored figure, so the calculation identity
(`identity.py`, `candidate_identity.py`) is unchanged and the new module is explicitly
listed as reporting code, not calculation code. An output carries: the definition id,
the run id and route, the price row's identity, A1 and A2, and the selection.

## Cross-checks, from previously reported totals

ANL-002 §7.2 reports 85,467.1329968 kWh charged and £11,675.4339216532500000. A
provisional figure computed outside the repository was
85,467.1329968 × £0.14228 = £12,160.263682784704, a difference of
£484.8297611314540000, about 4.0% of the flat-price charge. These are cross-checks
against the intended relations, not values to be forced.

## Acceptance

- Hand-derived fixture with a household favouring each price and an exact tie, plus a
  zero-consumption household; tests cover selection by period and household, household-
  to-aggregate reconciliation, incomplete coverage, routing on the published fixture,
  every unavailable state, the empty selection and the zero denominator.
- The tariff tab shows the comparison for the current selection with population,
  period, direction and the historical-scenario qualification visible, and assumptions
  and provenance in an expander; an unavailable comparison leaves the rest of the tab
  intact.
- `uv run compare-flat-price` reproduces the figures from a warehouse or a published root
  and writes a report carrying its identity.
- The results document states the pooled and household findings, coverage, and what the
  comparison does not show.
