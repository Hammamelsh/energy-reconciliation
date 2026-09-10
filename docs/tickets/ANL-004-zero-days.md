# ANL-004 — Whole days of zero recorded consumption

| Field | Value |
|---|---|
| Ticket | ANL-004 |
| Status | **Contract frozen 2026-09-10 before the warehouse was queried; analysis run the same day.** Results: [`../anl-004-zero-days.md`](../anl-004-zero-days.md) |
| Depends on | ING-001 (warehouse), FORE-001 (`DayRecord.usable`, the usable-day rule) |
| Out of scope | Any statement about *why* a day is zero; metadata; any change to a stored figure |

**This document was written before the analysis ran.** The results live in
[`../anl-004-zero-days.md`](../anl-004-zero-days.md).

## The question

The profiler separates a recorded zero from a missing value, and FORE-001 noted that the
loaded data contains many daily totals of exactly zero. A single half hour at zero is
ordinary. A **whole day** at zero — 48 distinct on-grid readings, every one exactly `0` —
is a different observation, and a run of such days more so. Anyone building a charge or a
forecast on this data needs to know where those days are before deciding what to do with
them.

**In the loaded warehouse, how are whole zero days distributed — across households, in
runs of consecutive dates, and relative to each household's recorded span?**

No cause is predicted or inferred. A zero day is a recorded observation; what produced it
(an empty property, a supply interruption, a metering fault, a genuine absence of use) is
**not established** from readings alone and is not guessed at here.

## The frozen contract

**Population.** Every household in `data/warehouse/energy.duckdb` (83, from source files
4, 5 and 135). Every day is classified by the FORE-001 rule already in
`forecast.dataset.DayRecord.usable`: 48 distinct on-grid labels with finite values, no
missing-value token, no conflicting label. Only **usable** days are eligible to be zero
days, because an unusable day is not evidence of zero.

**Zero day.** A usable day whose recorded total is exactly `0` — a `Decimal` comparison
over the same distinct values FORE-001 sums, never a threshold.

**Run.** A maximal set of consecutive calendar dates that are all zero days. A date that
is not a zero day ends a run, whether it is a non-zero day or an unusable day; an unusable
day never bridges two runs.

**Edge.** A run *touches an edge* when it starts on the household's first usable date or
ends on its last. Edge runs and interior runs are reported separately because a run at
the edge of what was loaded may continue outside it — file 134 and file 136 are not
loaded — while an interior run is bounded on both sides by recorded, non-zero, usable
days.

**Run-length buckets**, fixed in advance: `1`, `2–6`, `7–27`, `28+` days (a single day;
under a week; a week to under four; four weeks or more).

**What is reported.** Counts of households, usable days, zero days and runs; the bucket
distribution; the longest run; the number of runs and zero days touching an edge; and,
per household, its usable days, zero days, longest run and zero-day share. The report
carries the I-08 usable-days digest of the data it was computed from.

**Reconciliation, asserted in code.** Zero days summed over households equals zero days
summed over runs equals the total. Any mismatch is a defect, not a finding.

**Cross-check.** FORE-001 recorded 975 daily totals of exactly zero. That figure is
reported beside this one. If they differ, the difference is explained by population or
definition, not reconciled by adjustment.

## Before building — one understanding question for Hammam

A household whose zero days form one run of forty dates ending on its last loaded date
looks, in the summary, very like a household with forty scattered single zero days. Both
have forty zero days. Why does the report keep runs and edges rather than only the count,
and what would each of those two households mean for a monthly charge computed over the
same period?

## Acceptance

- `uv run zero-day-runs --database <warehouse>` prints the report and exits 0.
- Synthetic tests fix the run, edge and bucket logic against hand-counted fixtures,
  including an unusable day splitting a run.
- The results document states the population, the digest, every count, and what the
  counts do not show.
