# I-08 — What changes when eligibility is decided from prior data only

**Date:** 2026-09-08. **Contract:** [`tickets/I-08-prior-data-eligibility.md`](tickets/I-08-prior-data-eligibility.md),
written and committed (`b304c77`) **before** any figure below was computed.

**Status of the data.** An **as-of-source-date simulation**: "available at the origin"
means the source-date label is on or before it. Whether a reading would have been
*published* by then depends on ingestion and publication timing, which this archive does
not record, so **no claim of historical production availability is made**. It re-uses the
same warehouse and the same dates as FORE-001, **including its already-inspected holdout
window**, so it is **not** a fresh independent holdout and is not described as one.

## 1. What changed, and what did not

| | FORE-001 | I-08 |
|---|---|---|
| Household universe | 40 of 83, first by id, with a ≥168-day clean run | **all 83** |
| Run selection | longest clean run over the **whole** history | none |
| Origins | relative to each household's clean-run start | **one fixed calendar** from the warehouse span |
| Eligibility | membership of that run | ≥20 usable days in the 28 ending at the origin, **and** a usable origin day — all from dates ≤ origin |
| Models and settings | three, fixed | **identical, unretuned** |

## 2. The new population, before any accuracy figure

- **83 households**, against 40.
- **114 origins** on one shared calendar, **2011-12-20 to 2014-02-18**, every 7 days,
  derived from the warehouse span alone and never from a clean-run endpoint.
- **9,462 scheduled household-origins**, of which **8,467 (89.5%)** qualify.
- **66,234 scheduled cases per model** (household × origin × horizon), against FORE-001's
  9,555 scored.

## 3. Coverage, with explicit denominators

Denominator throughout: the **66,234 scheduled cases per model**.

| Model | Prediction coverage | Scoring coverage | Declines |
|---|---:|---:|---|
| `seasonal_naive_7` | **88.8%** (58,816) | **87.8%** (58,169) | 6,370 unusable origin · 595 thin window · 453 missing lag day |
| `weekday_mean_4` | **89.0%** (58,980) | **88.0%** (58,317) | 6,370 · 595 · 289 insufficient same-weekday history |
| `persistence_1` | **89.5%** (59,269) | **88.5%** (58,604) | 6,370 · 595 |

**Target availability is a separate axis**: 5,363 scheduled targets are absent from the
warehouse entirely and 744 are recorded but unusable. **5,460 cases are both declined and
unscoreable** and are counted under both — no scheduled case is dropped from the
accounting.

Coverage differs slightly by model, and in the direction that matters: `persistence_1`
declines least (it needs only the origin day) and `seasonal_naive_7` most (it also needs a
specific lag day). That is exactly why accuracy is reported on a common frame.

## 4. Accuracy, on the 57,885 cases every model scored

| Model | MAE (kWh) | Median AE | FORE-001 holdout MAE |
|---|---:|---:|---:|
| `weekday_mean_4` | **2.069** | 1.154 | 1.901 |
| `persistence_1` | **2.250** | 1.241 | 2.322 |
| `seasonal_naive_7` | **2.319** | 1.256 | 2.121 |

Each model's own scored set gives 2.069 / 2.252 / 2.320 — within a thousandth of the
common-frame figures, so the small coverage differences are not driving the result.

**Two findings.**

**The winner is unchanged; the order of the other two flips.** `weekday_mean_4` is still
best. But `persistence_1` (2.250) now **beats** `seasonal_naive_7` (2.319), where in
FORE-001 it was the worst of the three on both splits. The FORE-001 ordering of those two
was therefore **cohort-dependent**, and reporting it as a general fact would have been
wrong. *Why* it flips is **not established** — a plausible reading is that on households
with patchier histories a one-week-old value is more often stale than yesterday's, but
nothing here tests that, and it is recorded as I-12 rather than asserted.

**Accuracy did not simply worsen, and it was not predicted to.** It is not comparable
head-to-head with FORE-001's 1.901 either, because the population is different — which is
the point of the experiment, and why §5 separates the cases.

## 5. Shared with FORE-001, versus newly included

| | Cases |
|---|---:|
| FORE-001 scored | 9,555 |
| I-08 scored | 58,604 |
| **Shared** (same household, origin and horizon) | **1,722** |
| New to I-08 | 56,882 |
| In FORE-001 only | 7,833 |

The two calendars differ by construction — FORE-001 places origins relative to each
household's own clean-run start, I-08 uses one shared calendar — so only 74 of 402 origin
dates coincide and most cases do not overlap.

**On the 1,722 shared cases the two implementations agree exactly**: 5,166 (case, model)
pairs compared, **0 absolute-error mismatches**. That is a correctness check, not a
comparison population.

| Model | MAE on shared cases | MAE on newly included cases |
|---|---:|---:|
| `weekday_mean_4` | 1.446 | 2.088 |
| `seasonal_naive_7` | 1.653 | 2.340 |
| `persistence_1` | 2.179 | 2.254 |

The shared cases are markedly **easier** for the weekday models — they sit inside clean
runs, which is what FORE-001 selected for. The newly included cases are where the
populations differ, and they are harder for the two weekday models while barely moving
persistence. **This is the measured size of what the clean-run selection was contributing**
for those models; it is an association between selection and difficulty, not a decomposition
of bias.

## 6. What remains unknown

- **Why the persistence/seasonal ordering flips.** Recorded as I-12; untested here.
- **Whether 20-of-28 is the right eligibility threshold.** It was fixed in the contract and
  not swept; a different threshold would admit a different population.
- **What an operational system would actually have had.** This is an as-of-source-date
  simulation, not publication timing.
- **Whether the flip is driven by the 43 newly included households or by the new origins.**
  Both changed at once; separating them needs a third run holding one fixed.

## 7. Reproduction

```bash
uv run run-prior-eligibility --database data/warehouse/energy.duckdb
```

FORE-001's report, identities and figures are untouched; I-08 writes its own
`data/forecasts/i-08-*.json` with its own dataset, code and configuration digests.
