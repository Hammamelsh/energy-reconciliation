# ANL-004 — Whole days of zero recorded consumption: results

**Date:** 2026-09-10 (neighbour states measured and wording corrected the same day; definition `anl-004-zero-days-2`). **Contract:** [`tickets/ANL-004-zero-days.md`](tickets/ANL-004-zero-days.md),
frozen before the warehouse was queried. **Command:** `uv run zero-day-runs`. **Data:**
`data/warehouse/energy.duckdb`, source files 4, 5 and 135; I-08 usable-days digest
`59e64ecb9a2be365…`. The JSON report names real household ids and is kept out of git
(`data/quality/`).

Labels: **VERIFIED** (measured here), **UNKNOWN** (not established from readings).

## 1. What was measured

A *zero day* is a **usable** day — 48 distinct on-grid finite readings, no missing-value
token, no conflicting label, exactly the FORE-001 rule — whose total is exactly `0`. Every
one of its 48 readings is the text `0` in the source. Runs are consecutive calendar dates
that are all zero days; an unusable day never bridges two runs. For every run, the date
immediately before its start and after its end is classified — a non-zero usable day, an
unusable day with its reason, absent (no row), or beyond the household's recorded span —
and a run is called **bounded** only when both neighbours are non-zero usable days. That
is a measurement of the adjacent dates, distinct from whether a run touches the first or
last usable date. The buckets and the reconciliation checks were fixed in the contract.

## 2. Results — VERIFIED

| | |
|---|---:|
| Households loaded | 83 |
| Usable days | 61,799 |
| **Zero days** | **963** (1.56% of usable days) |
| Households with at least one zero day | **5** |
| Runs | 52 |
| Runs of 28 days or more | 13, holding 595 of the 963 days |
| Runs **bounded** by a non-zero usable day on both sides | **38** (725 days) |
| Runs with an unusable day as one neighbour (never both) | 14 (238 days): 7 next to a day missing one or two of its 48 labels, 4 next to a day carrying a `Null`, 3 next to a day with only 1, 22 or 33 labels |
| Runs touching the household's recorded span | 0 |
| Runs starting on the first usable date or ending on the last | 2 (13 days) |
| Longest run | 90 days, 2012-04-25 to 2012-07-23 |

Runs by length, as fixed in advance:

| Length | Runs | Zero days |
|---|---:|---:|
| 1 day | 2 | 2 |
| 2–6 days | 17 | 69 |
| 7–27 days | 20 | 297 |
| 28+ days | 13 | 595 |

Reconciliation held: 963 summed over households = 963 summed over runs = 963 counted
directly. All five households are in the `Std` (flat-rate) group, from files 4 and 5; none
is in the tariff scenario, whose 456,096 charged readings include only 133 individual zero
readings and no zero day.

## 3. The five households

| Household | Usable days | Zero days | Share | Runs | Longest run |
|---|---:|---:|---:|---:|---:|
| `MAC000197` | 816 | **780** | 95.6% | 36 | 90 |
| `MAC000134` | 392 | **143** | 36.5% | 10 | 32 |
| `MAC000148` | 818 | 21 | 2.6% | 2 | 20 |
| `MAC000172` | 627 | 12 | 1.9% | 3 | 5 |
| `MAC000144` | 631 | 7 | 1.1% | 1 | 7 |

Two of them carry 923 of the 963 zero days, and they are different shapes:

**`MAC000197` reads zero for almost its whole history.** Recorded 2011-11-28 to 2014-02-28
(824 dates, 816 usable), it has 780 zero days and 36 usable non-zero days. Those 36 are what
separate its 36 runs, and they are barely non-zero: their median daily total is **0.012 kWh**
and 30 of them are below 0.1 kWh; only three exceed 1 kWh (1.984, 5.014 and 8.259 kWh).
Eleven of the 13 runs of four weeks or longer are this household's; nine of those eleven
are bounded by non-zero usable days, and two sit next to a day with 47 of its 48 labels.
Over 27 months the recorded consumption is, in total, a few kWh.

**`MAC000134` records tens of kWh a day, and zero for a month at a time.** Recorded
2011-12-15 to 2013-01-15 (392 usable days), its non-zero usable days have a median recorded
total of **38.3 kWh**, yet 143 days are exactly zero, in ten runs including two of 32 and
31 consecutive days (2012-09-18 to 10-19 and 2012-10-21 to 11-20), separated by a single
day at 0.4 kWh. Both month-long runs have a non-zero usable day immediately before and
after. Its record ends on 2013-01-15, inside the loaded file.

The other three have between 7 and 21 zero days each, in runs of at most 20.

## 4. Cross-check with FORE-001 — reconciled by definition, not by adjustment

FORE-001 reported **975** daily totals of exactly zero. This analysis reports **963**. The
difference is exactly the 12 days whose total is zero but which are **not usable**: five
with a single reading on the date (a household's first or last recorded day), two with a
missing-value token, and five with 33–47 of the 48 grid labels. FORE-001 counted every
daily total; this analysis counts only days that meet the usable rule, because a partial
day totalling zero is not evidence that the whole day was zero. Both figures are correct
for their definitions. (963 + 12 = 975, VERIFIED.)

## 5. What this does and does not show

**It shows** where whole zero days are: concentrated in five of 83 households, two of them
heavily; mostly in runs of a week or more; 38 of the 52 runs have recorded, non-zero usage
on the day before and the day after, and none touches the edge of a household's recorded
span — so within the loaded data they are bounded events, not artefacts of where a file
was cut. Whether any household continues into a source file that was not loaded is not
knowable from the warehouse and is not claimed. It shows that a per-household total or
mean over this warehouse is dominated, for two households, by long stretches of exact
zeros that a summary statistic would silently absorb.

**It does not show why.** An empty property, a disconnected supply, a metering or
collection fault that reports zero rather than nothing, or a genuine absence of use would
all look like this in the readings. Nothing in the dataset distinguishes them and no
metadata has been linked. `MAC000197`'s near-total absence of consumption and
`MAC000134`'s month-long interruptions are described, not explained. **UNKNOWN.**

**It does not change any stored figure.** The tariff scenario is unaffected (no zero day is
charged). The FORE-001 backtest already treats a zero day as a recorded value and never
substitutes for it; `MAC000197` and `MAC000134` were not in its 40-household cohort, and
this analysis does not revisit that selection.

## 6. What it means for a charge built on this data

A charge is `consumption × price`, so a zero day contributes zero consumption-based charge
and raises no error. Zero recorded consumption is not the same as an established correct
bill: a month of exact zeros on a household whose other days record tens of kWh is an
unusual pattern that a billing process would need to surface and investigate before
relying on the figure — the same discipline as a missing value, without pretending to know
the cause. The profiler already keeps zero and missing apart; this analysis adds the
observation that **exact zeros arrive in runs**, and that most of those runs begin and end
against recorded usage.

## 7. Reproducing this

```bash
uv run zero-day-runs --database data/warehouse/energy.duckdb \
    --output data/quality/zero-days-energy.json
```

Prints the counts above and writes the full per-household report. The synthetic tests in
`tests/test_zero_days.py` fix the run, edge, bucket and reconciliation logic against a
hand-counted fixture, including an unusable day splitting a run.
