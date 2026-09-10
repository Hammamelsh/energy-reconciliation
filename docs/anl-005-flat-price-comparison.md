# ANL-005 — The same recorded consumption priced at the flat rate: results

**Date:** 2026-09-10. **Contract:**
[`tickets/ANL-005-flat-price-comparison.md`](tickets/ANL-005-flat-price-comparison.md), frozen
before the real warehouse was queried. **Command:** `uv run compare-flat-price`. **Definition:**
`flat-comparison-1`. The JSON reports name household ids and are kept out of git
(`data/quality/`).

Labels: **VERIFIED** (measured here), **UNKNOWN** (not established).

## 1. What was compared, and under what assumptions

The **456,096 charged readings** of the 27 `ToU` households in source file 135, for 2013 — the
scenario population of ANL-002 — priced two ways:

- **Dynamic:** the scenario charge already stored on each row, under **A1** (a consumption
  timestamp label and a schedule label denote the same half hour).
- **Flat:** the same rows at the publisher-documented flat price, **14.228 p/kWh**
  (£0.14228/kWh; catalogue `2026-09-08.1`, PUBLISHER-DOCUMENTED, read from the build's own
  price dimension), under **A2**: *the flat price is hypothetically applied to every selected
  charged reading throughout the period.* Its effective dates are **UNKNOWN**; A2 is a
  comparison assumption, not a claim about when the price was in force.

Per row, `consumption_kwh × price` in exact decimal, summed; nothing rounded before display.
The per-row sum equals `SUM(kWh) × price`, asserted in code.

This is a **fixed-consumption historical price comparison**. It does not establish what
anyone paid or saved (no standing charge, levy or tax is modelled; these households were on
the dynamic tariff and might have consumed differently on a flat one), any behavioural
response, tariff advice, or anything representative of London.

## 2. Pooled result — VERIFIED

| | |
|---|---:|
| Charged readings | 456,096 |
| Charged kWh | 85,467.1329968 |
| Dynamic energy charge (A1) | **£11,675.4339216532500000** |
| Flat-price energy charge (A2) | **£12,160.2636827847040000** |
| Flat minus dynamic (positive: dynamic lower) | **+£484.8297611314540000** |
| As a percentage of the flat-price charge | **+3.987%** |

For this recorded consumption, the dynamic price schedule produces an energy charge **4.0%
lower** than the flat price would. The figure reproduces the provisional cross-check in the
ticket exactly, and is identical on both routes: the Python scenario run
`4b3ee235d7ac@20260908T133236854164` in `data/warehouse/energy.duckdb`, and the certified dbt
build `dbtcand-fbd1f2566700@20260909T093452754963` read through the publication contract.

## 3. Household variation and coverage — VERIFIED

**25 of the 27 households are lower under the dynamic scenario; 2 are higher; none is equal**
(classified on exact differences).

| | |
|---|---:|
| Household differences, as % of each household's flat-price charge | −1.2% to +11.4% |
| Median household difference | +£11.94 |
| Households within ±2 points of the pooled +4.0% | 16 of 27 |
| Largest single household difference | +£63.05 (+11.4%), 13.0% of the pooled £484.83 |
| The two households higher under dynamic | −£2.37 (−1.2%) and −£1.02 (−0.3%) |

**Coverage.** The schedule carries 17,520 half-hour labels for 2013. 26 of the 27 households
are charged for 17,375–17,520 of them (99.2–100% observed label coverage). One,
`MAC000146`, is charged for 864 (4.9%): its readings in the loaded files stop on 18 January.
Its difference (+£1.54, +8.5%) is a figure about 18 days, not a year, and is listed with its
coverage rather than scaled. Observed coverage is label coverage: it is never annualised and
is not proof that every physical interval was metered.

The pooled result is therefore **broadly shared rather than concentrated**: the direction
holds for 25 of 27 households, the largest household contributes 13% of the pooled
difference, and most households fall within a few points of the pooled percentage. The two
exceptions are small in both pounds and percentage.

Per-household table (27 rows, exact values in the JSON report):

| Household | Charged readings | Coverage | Dynamic £ | Flat £ | Flat − dynamic | % of flat | Under dynamic |
|---|---:|---:|---:|---:|---:|---:|---|
| `MAC000186` | 17,515 | 100.0% | 194.87 | 192.50 | −2.37 | −1.2% | higher |
| `MAC000173` | 17,515 | 100.0% | 294.42 | 293.40 | −1.02 | −0.3% | higher |
| `MAC000146` | 864 | 4.9% | 16.64 | 18.18 | +1.54 | +8.5% | lower |
| `MAC000290` | 17,518 | 100.0% | 348.72 | 352.29 | +3.57 | +1.0% | lower |
| `MAC000261` | 17,518 | 100.0% | 382.58 | 386.62 | +4.04 | +1.0% | lower |
| `MAC000219` | 17,515 | 100.0% | 314.51 | 318.73 | +4.22 | +1.3% | lower |
| `MAC000158` | 17,512 | 100.0% | 207.31 | 212.07 | +4.77 | +2.2% | lower |
| `MAC000292` | 17,514 | 100.0% | 226.65 | 231.56 | +4.90 | +2.1% | lower |
| `MAC000265` | 17,469 | 99.7% | 394.34 | 399.53 | +5.19 | +1.3% | lower |
| `MAC000165` | 17,520 | 100.0% | 640.37 | 645.87 | +5.51 | +0.9% | lower |
| `MAC000236` | 17,512 | 100.0% | 185.96 | 192.63 | +6.67 | +3.5% | lower |
| `MAC000266` | 17,513 | 100.0% | 283.86 | 293.25 | +9.40 | +3.2% | lower |
| `MAC000298` | 17,518 | 100.0% | 189.40 | 200.75 | +11.36 | +5.7% | lower |
| `MAC000293` | 17,518 | 100.0% | 356.55 | 368.49 | +11.94 | +3.2% | lower |
| `MAC000278` | 17,518 | 100.0% | 267.93 | 283.81 | +15.88 | +5.6% | lower |
| `MAC000259` | 17,375 | 99.2% | 547.68 | 565.65 | +17.98 | +3.2% | lower |
| `MAC000187` | 17,520 | 100.0% | 423.33 | 441.50 | +18.17 | +4.1% | lower |
| `MAC000147` | 17,520 | 100.0% | 300.04 | 322.68 | +22.65 | +7.0% | lower |
| `MAC000170` | 17,515 | 100.0% | 633.44 | 659.20 | +25.76 | +3.9% | lower |
| `MAC000194` | 17,505 | 99.9% | 482.09 | 508.47 | +26.38 | +5.2% | lower |
| `MAC000247` | 17,511 | 99.9% | 563.73 | 590.91 | +27.18 | +4.6% | lower |
| `MAC000198` | 17,519 | 100.0% | 841.58 | 871.72 | +30.14 | +3.5% | lower |
| `MAC000288` | 17,518 | 100.0% | 482.92 | 517.81 | +34.89 | +6.7% | lower |
| `MAC000286` | 17,519 | 100.0% | 629.05 | 667.18 | +38.13 | +5.7% | lower |
| `MAC000195` | 17,518 | 100.0% | 678.52 | 717.02 | +38.49 | +5.4% | lower |
| `MAC000257` | 17,517 | 100.0% | 1,301.30 | 1,357.72 | +56.41 | +4.2% | lower |
| `MAC000193` | 17,520 | 100.0% | 487.65 | 550.71 | +63.05 | +11.4% | lower |

Pounds are rounded here for display only; the classification and the totals use the exact
values.

## 4. What this shows, and what it does not

**It shows** that, for the consumption these 27 households actually recorded in 2013, the
three-band dynamic schedule priced that consumption 4.0% below the documented flat price, and
that the direction is shared by 25 of 27 households with a spread of about −1% to +11%. Where a
household sits in that spread depends on how much of its consumption fell in `High` half hours
(67.20p) against `Low` (3.99p) and `Normal` (11.76p); a household with a larger share in `High`
gains less, and two gained nothing.

**It does not show** what anyone paid or saved. Three things stand between this figure and a
bill: the flat price's period is UNKNOWN (A2 assumes it); the comparison holds consumption
fixed, whereas households on a dynamic tariff may have shifted usage in response to it, so the
same households on a flat tariff might have consumed differently; and no standing charge, levy
or tax is modelled. It does not show a behavioural response — it cannot, with no comparison
group and no before-and-after. It is not tariff advice and says nothing about tariffs today. It
does not say that any particular clock time is cheaper: the schedule changed daily, and that
would be a separate analysis.

**It does not change any stored figure.** The scenario facts and their identity are untouched;
this is a read over them, and the new module is explicitly outside the calculation identity.

## 5. Reproducing this

```bash
# the Python scenario in the local warehouse
uv run compare-flat-price --database data/warehouse/energy.duckdb \
    --output data/quality/flat-comparison-warehouse.json

# a certified published build, through the read contract
uv run compare-flat-price --published-root <publication root> \
    --output data/quality/flat-comparison-published.json

# one household, or a period, exactly as the dashboard selects them
uv run compare-flat-price --household MAC000193 --start 2013-06-01 --end 2013-06-30
```

The dashboard's **Tariff scenario** tab shows the same comparison for the selection on
screen, in both the *Selected household* and *Loaded ToU sample* views, with assumptions and
price provenance in an expander. `tests/test_flat_comparison.py` fixes the arithmetic against a
hand-derived fixture (a household favouring each price, an exact tie, a zero-consumption
household, a difference that rounds to £0.00 but is still classified), selection by period and
household, coverage, every unavailable state and the empty selection;
`tests/test_reads.py` proves the published route prices the dbt facts with the dbt build's own
price row.
