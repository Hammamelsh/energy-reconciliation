# I-08 — Prior-data eligibility evaluation

| Field | Value |
|---|---|
| Ticket | I-08 (from `docs/ideas.md`) |
| Status | **Contract frozen 2026-09-08, before any I-08 score was computed.** |
| Depends on | FORE-001 (`74ac326`) |
| Out of scope | New models, new settings, external data, live forecasting |

**This document was written and committed before the experiment ran.** It is the
pre-registration; the results live in `docs/i-08-prior-data-eligibility.md`.

## The question

FORE-001 chose households by a clean run found over their **whole** history, holdout
included. What does the same comparison look like when eligibility at each origin is
decided only from source dates **at or before that origin**?

**No direction is predicted.** Prior-data eligibility admits households and origins that
FORE-001 excluded and may admit easier or harder cases; it does not guarantee a worse MAE,
and on its own it does not isolate selection bias, because a household's *later* data
quality still decides whether a target can be scored at all. That is why prediction
coverage and scoring coverage are reported separately below.

## The frozen contract

**Household universe.** Every household in the warehouse. No run-length rule, no id
bound, no exclusion computed from data after an origin. FORE-001 used 40 of 83; I-08
considers all 83 and lets the per-origin rules decide.

**Origin calendar.** A fixed calendar, identical for every household, derived only from
the warehouse's date span — **never** from any household's clean-run endpoint. Origins are
every 7th date from the first date on which a 28-day window could exist
(`warehouse_first + 27`) up to `warehouse_last - 7`, so every origin has a full horizon of
scheduled target dates inside the span.

**Required history at an origin.** The household must have at least
`MIN_USABLE_IN_WINDOW = 20` usable days among the 28 dates ending at the origin, **and**
the origin date itself must be usable. Both are computed from source dates ≤ origin only.
20 of 28 is fixed here in advance; it is not tuned.

**Target-quality rules.** A scheduled target is **scoreable** when its own source date is
usable by the FORE-001 definition (48 nominal labels, no missing-value token, no
disagreement). Otherwise it is unavailable/unusable and is recorded as such — it is never
dropped from the accounting and never zero-filled.

**Information available at an origin.** Usable daily totals dated ≤ origin, for that
household only. Lag lookup stays keyed by date. No row positions, no zero fill, no
bridging.

**Models and settings.** The three FORE-001 methods, unchanged and unretuned:
`seasonal_naive_7`, `weekday_mean_4`, `persistence_1`.

## Accounting, published with explicit denominators

Every scheduled (household, origin, horizon) case is classified on **two independent
axes**, and both are reported:

| Axis | Values |
|---|---|
| Prediction | issued · declined *(with reason: insufficient window, missing lag day, insufficient same-weekday history, origin day not usable)* |
| Target | scoreable · unavailable *(with reason: not usable, or absent from the warehouse)* |

- **Prediction coverage** = predictions issued ÷ scheduled cases.
- **Scoring coverage** = cases scored ÷ scheduled cases, where scored requires *both* a
  prediction and a scoreable target.

A case with a declined prediction **and** an unusable target appears under both reasons;
the two classifications are never collapsed.

## Comparison rules

1. Models are compared on the **common scoreable cases** — those every model predicted —
   so no model can look better by declining harder ones.
2. **Model-specific coverage** is reported beside accuracy, so a decline advantage is
   visible.
3. Cases **shared with FORE-001** are reported separately from **newly included** cases,
   and the shared-case figures must reproduce FORE-001's for the same models.
4. The new population and its dates are described **before** any aggregate MAE comparison.

## Status of the data

An **as-of-source-date simulation**. "Available at the origin" means the source-date label
is ≤ the origin. Whether a reading would have been *published* by then depends on
ingestion and publication timing, which the archive does not record; no claim of
historical production availability is made.

**Overlap with previously inspected data is total and is not hidden.** I-08 re-uses the
same warehouse and the same dates, including FORE-001's already-inspected holdout window.
It is **not** a fresh independent holdout and is not described as one.

## Acceptance criteria

| # | Criterion |
|---|---|
| 1 | Contract committed before any I-08 score is computed |
| 2 | Origins derived from the warehouse span alone, never from clean-run endpoints |
| 3 | Models and settings byte-identical to FORE-001 |
| 4 | Eligibility uses only source dates ≤ origin — tested against future mutation |
| 5 | Every scheduled case classified on both axes; nothing disappears |
| 6 | Prediction and scoring coverage published with denominators |
| 7 | Common-case comparison plus per-model coverage |
| 8 | Shared-with-FORE-001 cases separated from newly included ones, and shared figures reproduce FORE-001 |
| 9 | FORE-001 outputs, identities and report untouched; I-08 has its own |
