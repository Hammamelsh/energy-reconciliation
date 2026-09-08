# FORE-001 — An evaluated consumption forecasting experiment

| Field | Value |
|---|---|
| Ticket | FORE-001 |
| Status | **Measured 2026-09-08.** Findings: [`../fore-001-forecasting-experiment.md`](../fore-001-forecasting-experiment.md) |
| Milestone | New strand; does not displace dbt (ANL-003), reconciliation (M4), Airflow (M5), cloud (M6) or Spark (M7) |
| Depends on | ING-001 (loaded readings), REP-001 (what the data is) |
| Out of scope | Geography, AI assistants, appliance disaggregation, tariff-response claims, live forecasting |

## Why this is worth doing

The project can now say what was recorded and what a tariff scenario would have charged.
Forecasting asks a different question — how much of a household's next week is predictable
from its own past — and it is the first question here whose answer is a *measured accuracy*
rather than a reconciliation.

## Decided: eligibility before performance

Every rule that decides what is forecast, and what is scored, was fixed and written down
before any result was looked at: 48 observed labels, no missing-value token, no
disagreement, one contiguous usable run of at least 168 days, households ordered by id and
bounded to 40. Choosing households by how well they forecast would make any accuracy figure
meaningless, so the selection rule is documented and mechanical.

## Decided: a model may decline

If a day a model needs is unusable, it returns no prediction and a reason. Substituting a
zero would score data quality as if it were forecast accuracy — and in a project whose
central policy is that missing is not zero, it would also be incoherent.

## Decided: MAE, not MAPE

The loaded data holds 975 daily totals of exactly zero. A percentage error is undefined or
explosive there, and would rank models by the smallest days.

## Decided: no complex model

The baselines and a development-only sweep over how much same-weekday history to average
show, among {1, 2, 4, 8} weeks on a common frame, that 4 is best. That the remaining error
is information these models lack is a hypothesis, not a finding. A larger model class
would add a dependency without a measured signal to justify it, so none was added; the
alternatives and the experiment that would separate them are in `docs/ideas.md`.

## Recorded honestly: the sweep came after the holdout was read

The main comparison's holdout results were read before the sweep was designed. The sweep
selected on development only, but its chosen candidate is the main comparison's own model,
so its holdout line restates a known figure rather than testing a fresh one.

## Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Feasibility established from the loaded data before modelling | **met** |
| 2 | Prediction target defined without claiming calendar-day or interval completeness | **met** |
| 3 | Input-quality and evaluation eligibility fixed before results | **met** |
| 4 | No zero filling, no bridged dates, no partial total called complete | **met** |
| 5 | Bounded household selection by documented data criteria | **met** — 40 of 71 eligible, by id; a retrospective clean-run benchmark, 35 `Std` / 5 `ToU` |
| 6 | Both required baselines implemented and compared | **met** |
| 7 | Rolling origins with explicit forecast origins and an untouched holdout | **met** |
| 8 | Only information available at the origin is used | **met** — proved by mutating the future |
| 9 | MAE by household and horizon, with counts and exclusions | **met** |
| 10 | Poor results retained; no tuning on the holdout | **met** — holdout scored once; the later sweep's holdout line is a restatement, not a second test |
| 11 | Observed-versus-predicted view distinguishing backtest from live forecast | **met** |
| 12 | Known-answer tests for lag alignment, missing dates and leakage | **met** — 38 tests |
| 13 | Dataset, code, configuration and split identity recorded | **met** |

## Not done, deliberately

No forecasting of future dates, no weather or occupancy data, no geography, no AI
assistant, no appliance inference, and no claim connecting a forecast to a bill, a saving
or a response to price.
