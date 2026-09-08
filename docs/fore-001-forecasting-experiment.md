# FORE-001 — How accurately can we forecast seven days of daily consumption?

**Date:** 2026-09-08. **Status:** measured. **A historical backtest, not a live
forecast.** Nothing here is a bill, a saving, an appliance claim, or a statement about
response to a tariff.

**Question.** For eligible loaded households, how accurately can the next seven source
dates' consumption totals be predicted from earlier data alone?

## 1. The prediction target

**One household's recorded half-hourly consumption, in kWh, grouped by source-date
label.**

A "source date" is the date part of the timestamp label as the source wrote it. Grouping
by it is a grouping and **not** a claim: its correspondence to a local calendar day is not
established, it is not a settlement day, and a date carrying 48 labels is not proof the
meter covered the whole day. The timestamp convention remains UNRESOLVED (AQ-01).

Totals use the same policy as everything else in this project: distinct on-grid finite
readings, each meaning counted once, off-grid observations excluded.

## 2. Feasibility, measured before any model was written

| | |
|---|---:|
| Households loaded | 83 |
| Household-days recorded | 62,689 |
| **Usable** household-days | 61,799 |
| Recorded missing-value rows | 81 |
| Off-grid rows | 81 |
| Household-days with disagreeing readings | **0** |
| Households with a contiguous usable run ≥ 168 days | **71** |
| Longest usable run: min / median / max | 61 / 220 / 436 days |

The nominal grid is **48 labels per source date** (00:00 to 23:30), measured, not assumed.

**Why days are unusable**, and it is almost entirely partial observation: 489 days carry
47 of 48 labels, 180 carry 1, 81 carry a recorded `Null`, and the rest are scattered
partials. Nothing is repaired: no zero fill, no bridging, no treating a partial date as a
whole one.

**A consequence of the unresolved timestamp convention, checked rather than assumed.**
If the labels were local wall-clock time, the spring-forward date would hold 46 labels and
the autumn date 50, and every household would fail the 48-label rule on those dates.
Measured across all four UK clock changes in the span:

| Date | Interval counts observed |
|---|---|
| 2012-03-25 (spring forward) | 48 for all 80 households present |
| 2012-10-28 (autumn back) | 48 for 80, 43 for 1 |
| 2013-03-31 (spring forward) | 48 for all 75 |
| 2013-10-27 (autumn back) | 48 for all 72 |

So **no date in the loaded data gains or loses half hours at a UK clock change**, and the
48-label rule never systematically excludes a transition date. That is consistent with a
fixed nominal grid — as the tariff schedule also is (ANL-001 §3) — and it does **not**
resolve the convention. It only establishes that this particular hazard does not bite here.
The partial days cluster on ordinary dates instead (33 households on 2012-10-18), which
looks like collection outage; the cause is not established.

## 3. Eligibility, fixed before any performance was seen

**A usable day** requires all of: 48 distinct on-grid labels with finite values; no
missing-value token; no label carrying disagreeing readings. Off-grid observations on the
date are permitted and counted — policy already excludes them from the total.

**An eligible household** has one **contiguous** run of usable days of at least
**168 days**, which accommodates a 28-day warm-up, weekly rolling origins and a 28-day
holdout.

**Contiguity is a benchmark choice, not a correctness requirement.** Lag lookup is keyed
by date: a model asks for `target − 7 days` and receives that date's value or nothing. A
hole never shifts what "seven days earlier" means — it makes the lookup return nothing and
the model declines. Contiguity is imposed so every household contributes a dense frame of
the same shape and the split boundaries are well defined in calendar days, which keeps the
model comparison from being confounded by differing decline rates. Relaxing it is a
separate experiment (I-08).

Households are selected by that rule and then by **household id**, bounded to the first
**40**. Nothing in the selection depends on how well anything forecasts.

**Two limits of that rule, measured rather than assumed.**

*It uses hindsight.* The longest run is found over each household's whole recorded
history, holdout window included, so a household is in the cohort partly *because* its
data stayed clean to the end. No model sees a value after its origin — the leakage test
proves that — but an operator on the origin date could not have made this selection. The
result is a **retrospective clean-run benchmark** of the models, not an estimate of
operational accuracy across all households. 30 of the 40 selected runs end before the
warehouse's last date, i.e. their boundaries are set by later data-quality events.

*"First 40 by id" is arbitrary, and not neutral.* Ids track source members, so the cohort
is **35 `Std` / 5 `ToU`** and **34 of 40 from members 4–5**, against 47 / 24 and 27 / 44
among all 71 eligible. Nothing here weights or reweights for that; a figure from this
cohort is a figure about these forty households.

## 4. Design

- **Rolling origins**, stepping weekly. At origin `O` a model may use usable totals dated
  `≤ O` and nothing else, and predicts `O+1 … O+7`.
- **Splits per household:** a 28-day warm-up carries no origin; then development; then the
  final **28 days as a holdout**, scored once at the end. Development targets never enter
  the holdout window (0 overlapping targets, checked), and each (household, target date)
  is predicted **exactly once per model per split**, because origins step by exactly the
  horizon.
- **The holdout is rolling, by specification.** Its four origins step weekly through the
  window, so a later holdout origin may use earlier *holdout* dates as inputs — as an
  operator on that day would. 2,520 of the 3,360 holdout predictions do. What is forbidden
  is any date after the origin, and any model or parameter choice informed by holdout
  scores.
- **A model may decline.** If a day it needs is not usable it returns no prediction and a
  reason. It never substitutes a zero, a mean, or the nearest available day — that would
  turn "we cannot say" into a number that then gets scored.
- **MAE in kWh**, by model, horizon and household, with counts and exclusions.
  **MAPE is deliberately absent**: the loaded data contains **975 daily totals of exactly
  zero**, where a percentage error is undefined or explodes, so MAPE would rank models by
  their behaviour on the smallest days.

## 5. Results

All three models are scored on **identical (household, origin, horizon) cases** —
checked, not assumed.

| | Development | Holdout |
|---|---:|---:|
| Households | 40 | 40 |
| Forecast origins | 1,205 (16–54 per household) | 160 (4 per household) |
| Scored predictions per model | 8,435 | 1,120 |
| Unique (household, target date) | 8,435 | 1,120 |
| Targets predicted more than once per model | 0 | 0 |
| Exclusions | 0 | 0 (see §7) |

**MAE pools predictions**: every scored prediction has equal weight. In the holdout every
household contributes exactly 28, so pooled and household-equal-weight MAE coincide. In
development, counts run from 112 to 378 per household, and the two differ slightly
(`weekday_mean_4`: 2.094 pooled, 2.055 household-equal). The pooled figure is reported.

Keep three numbers apart: **61,799** is warehouse-level usable household-days across all
83 households; **40** is the cohort; **8,435 / 1,120** are what was scored.

| Model | Development MAE | **Holdout MAE** | Holdout median AE |
|---|---:|---:|---:|
| `weekday_mean_4` — mean of the 4 preceding same weekdays | 2.094 | **1.901** | 1.069 |
| `seasonal_naive_7` — same weekday last week | 2.397 | **2.121** | 1.154 |
| `persistence_1` — the origin day repeated *(reference)* | 2.550 | **2.322** | 1.232 |

For scale, use the scored targets themselves, not the whole warehouse: the holdout's
1,120 target days have a mean of **10.122 kWh** and a median of **8.634 kWh** (27 of them
are exactly zero); the development targets average 9.166 kWh. So 1.901 kWh is about 19%
of the holdout's mean target and 22% of its median. That is a ratio of an error to a
typical day, **not** an "accuracy". The ordering of the three models is the same on both
splits, and the holdout was scored once.

**By horizon (holdout, kWh):**

| | h+1 | h+2 | h+3 | h+4 | h+5 | h+6 | h+7 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `weekday_mean_4` | 2.010 | 1.854 | 2.009 | 1.907 | 1.935 | 1.767 | 1.824 |
| `seasonal_naive_7` | 2.247 | 2.043 | 2.397 | 1.998 | 2.313 | 1.866 | 1.987 |
| `persistence_1` | 2.104 | 2.140 | 2.733 | 2.837 | 2.309 | 2.142 | 1.987 |

**Error does not rise monotonically with the horizon.** Two things are known about why,
and they are different kinds of knowledge.

*A property of the models:* for the two weekday models the newest input is always exactly
seven days before the target, whatever the horizon (measured: 7 days at every h). That is
consistent with a non-rising pattern; it is not proof of what causes the pattern actually
observed, which also moves up and down between horizons.

*A measured association for `persistence_1`:* its error is highest when the origin and
the target sit on opposite sides of the weekday/weekend boundary — holdout MAE **2.665**
on those 356 pairs against **2.208** on the 604 same-side, different-weekday pairs — and
lowest at h+7, where origin and target share a weekday (**1.987**). Development shows the
same crossing effect (2.897 vs 2.244), though there same-weekday h+7 (2.538) is *not* the
best. So "the weekday/weekend crossing raises persistence error" is supported; "weekday
mismatch dominates" as a blanket statement is not, and is not claimed. "Non-recursive
models have flat horizon error" would be the wrong generalisation in any case.

### The one further experiment the baselines justified

The two required baselines differ mainly in **how much** same-weekday history they average
— one week against four — and four won. That is a concrete question the data can answer
with no new model class and no new dependency: sweep the number of weeks, choose on
development, spend the holdout once.

**Ordering, stated plainly.** This sweep was designed *after* the main comparison's
holdout results had been read. Its selection used development only, and no other
candidate was scored on the holdout; but the candidate it selected is the main
comparison's own model, whose holdout figure (1.901) was already known. The holdout line
below is therefore a **restatement**, not a fresh independent test. There was no
preregistration of the sweep, and none is claimed.

**The frame, and why the 4-week number here differs from the one above.** Candidates
needing more history decline more often at early origins — the 8-week model cannot predict
from a household's first four development origins (4 × 7 × 40 = 1,120 cases, all
`insufficient_same_weekday_history`). Scoring each candidate on whatever it managed would
compare them over different days, so the comparison is restricted to the **7,315 cases
every candidate predicted**. On that frame `weekday_mean_4` scores **2.059**; on the
1,120 dropped early-origin cases it scores **2.321**; pooled over all 8,435 it is the
headline **2.094**. The early weeks of a run are harder for every model, and the sweep
frame omits them.

| Weeks averaged | Development MAE (kWh) |
|---:|---:|
| 1 (= `seasonal_naive_7`) | 2.330 |
| 2 | 2.144 |
| **4** | **2.059** |
| 8 | 2.119 |

**What was measured:** among {1, 2, 4, 8} weeks of equal-weight same-weekday averaging,
on this frame, 4 is best and 8 is worse than 4. **What is a hypothesis:** *why* 8 is
worse (older weeks being less representative is one explanation, more variance from a
longer window in a series with level shifts is another), and whether 3, 5, 6 weeks or a
recency-weighted average would do better than 4 — none of those was tested. "Four weeks
exhausts the benefit of history" is not supported by four points on one frame, and is
not claimed. The experiment that would distinguish the alternatives: a denser sweep
including exponentially weighted variants, on the same common frame, selected on
development, with a holdout that has not already been read.

**No more complex model was added.** The measured evidence justifies the two baselines and
one sweep, not a new model class. That the remaining error comes from information these
models lack is a **hypothesis** consistent with the failure pattern in §6 (one-off days
that the household's own past cannot anticipate); it is not established, and it would be
established only by adding such an input at forecast-origin information level and
measuring the change on a fresh holdout.

## 6. Where the predictions fail

**The reason differs by model, and one explanation for all three would be wrong.**
Measured on `MAC000131`'s ten largest errors:

- For the **weekday models**, a large error does coincide with a target unlike its weekday
  lag. 8 Jan 2014: observed 11.242 against a lag of 21.388, and `seasonal_naive_7` — which
  *is* that lag — is wrong by exactly 10.146.
- For **`weekday_mean_4`** the previous-week column alone explains nothing — its input is
  the four preceding same weekdays, and both of its top-ten misses are targets outside the
  range of all four. 9 Nov 2013: observed 17.965 against 9.544 · 6.706 · 7.253 · 11.546,
  whose mean is exactly the 8.762 predicted. 25 Dec 2013: observed 21.369 against
  14.205 · 11.965 · 12.638 · 14.445, mean 13.313. No averaging of those inputs reaches the
  target. (The explorer's worst-days table now shows the four values and the dates the
  model read for every row; classifying this cohort-wide is idea I-13.)
- For **`persistence_1`** the largest error of all occurs where the weekday lag was nearly
  exact. 1 Jan 2014: observed 21.388, the previous Wednesday 21.369, a difference of
  **0.019** — yet persistence predicted 11.061, because it repeats the origin day, and the
  origin was New Year's Eve.

So "large errors happen on days unlike the same weekday before them" describes the weekday
models and is contradicted by the worst persistence case. Cohort-wide, the top 1% of errors
(286 of 28,665) are 120 `seasonal_naive_7`, 98 `persistence_1` and 68 `weekday_mean_4`,
against an equal 9,555 scored predictions each — the four-week mean is under-represented
among the worst errors, consistent with averaging damping one-off days, though that is an
association rather than a demonstrated mechanism.

What remains true of all three: by construction they see **only** one household's earlier
daily totals — no weather, occupancy, holidays, tariff band, price, or any other
household.

## 7. What the real data did not exercise

**0 predictions were excluded on real data**, and that is by construction rather than luck:
eligibility requires a *contiguous* usable run, so within a run every lag a model needs is
present. The declining paths — missing lag day, insufficient same-weekday history, unusable
target — are therefore exercised **only by the synthetic tests**, which is exactly what
those tests are for. The one place declining does fire on real data is the weeks sweep,
where 8-week candidates correctly decline 1,120 early-origin triples.

## 8. Reproduction

```bash
uv run run-forecast-experiment --database data/warehouse/energy.duckdb
```

Recorded with every run: dataset digest, forecast code digest, configuration digest,
first-party calculation digest and the runtime versions. The report is written to
`data/forecasts/` (git-ignored, because it names real household ids).

## 9. What forecasting does not establish

Nothing here bears on tariff assumption **A1**. Forecasting daily totals grouped by source
date neither requires nor tests the alignment of consumption labels to schedule labels.
The DST observation in §2 constrains how the labels behave at clock changes; it does not
resolve the convention.

## 10. Limits

- **A backtest over recorded history.** Not a live forecast; no future date is predicted.
- **An as-of-source-date simulation, not historical production availability.** "Data
  dated on or before the origin" means readings whose source-date label is on or before
  it. Whether those readings would actually have been *available* on that date in the
  original system depends on ingestion and publication timing, which this archive does
  not record. No such claim is made.
- **40 households from 83 loaded, from 3 members of 168** — a bounded, non-representative
  subset: 35 `Std` / 5 `ToU`, 34 from members 4–5, chosen by id. No figure here
  describes the trial or London.
- **A retrospective clean-run benchmark.** Household runs were selected with hindsight
  over their whole history; this is not operational accuracy over all households.
- The timestamp convention is unresolved; source dates are a grouping, not calendar days.
- The models are univariate and given nothing but one household's own history.
- MAE is reported in kWh; comparing it across households of very different size is not
  meaningful, which is why per-household MAE is reported rather than pooled percentages.
