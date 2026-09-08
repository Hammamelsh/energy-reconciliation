# Delivery roadmap

**What this is.** Seven delivery milestones for the Energy Billing and Reconciliation Simulator, each
with what it delivers and the condition under which it is complete.

**What this is not.** These are **delivery milestones, not promises of seniority or employment**.
Completing a milestone means an artefact exists and its completion condition is satisfied — nothing
more. No milestone carries a date; completion conditions are the only measure used here.

**Status:** M1 is in progress. A first slice of **M2** is built — see
[`tickets/ING-001-standardised-ingestion-and-explorer.md`](tickets/ING-001-standardised-ingestion-and-explorer.md):
standardised ingestion into DuckDB with a decided rerun policy, plus a household data-quality
explorer. M2's remaining items (Parquet output, rejected-record reasons across the whole archive,
cross-file processing beyond three members) are not done.

A first slice of **M3** is also built — see
[`tickets/ANL-002-tariff-scenario.md`](tickets/ANL-002-tariff-scenario.md): the tariff band
schedule, the publisher-documented price catalogue and an assumption-labelled interval charge
scenario, materialised in DuckDB and measured over one real `ToU` member. **M3's dbt deliverable
is not met** — the models are written as standalone SELECTs, which gives the port working, tested
SQL to start from but does not make it mechanical. Tracked as ANL-003 below. Orchestration and
cloud deployment remain planned.

See [`../README.md`](../README.md) for what runs today, and
[`source-data-profile.md`](source-data-profile.md) section 16 for the REP-001 assessment.
Candidate work that is recorded but not authorised lives in [`ideas.md`](ideas.md).

---

## M1 — Reproducible source investigation

**Deliver**

- Runnable one-member profiler and documented command.
- Machine-readable profile with reconciled logical-record counts.
- Consumption distribution, duplicate and missing-value findings.
- Separate facts, assumptions and open questions.
- Meaningful synthetic tests.

**Complete when**

- Remaining REP-001 requirements are assessed honestly.
- The maintainer can explain one record, missing vs zero, duplicate risk, source tracing and the
  profiler's counting equation.
- Unresolved time semantics have explicit downstream restrictions.

## M2 — Reliable ingestion and standardisation

**Deliver**

- Stable typed schema, Decimal consumption, explicit missing-value handling.
- Source archive/member/record references and rejected-record reasons.
- Durable typed output such as Parquet.
- Safe reruns, recovery from interrupted runs and cross-file processing.

**Complete when**

- Rerunning identical inputs does not duplicate published output.
- Failed runs cannot expose partial output as complete.
- Every input record is accounted for.
- Household boundaries and candidate-key conflicts have tested handling.

## M3 — dbt modelling and scoped cost calculations

**Deliver**

- Staging models, household/tariff dimensions and interval consumption facts.
- Inspection and modelling of the actual tariff workbook.
- Effective-date tariff joins with missing/overlapping-rate checks.
- Decimal precision, currency units and explicit rounding rules.
- Coverage indicators and consumption charges.

**Complete when**

- Small independently calculated fixtures match.
- Missing values do not become zero.
- Duplicate observations cannot inflate published totals.
- Costs have clear time assumptions and scope.
- Historical bills are not claimed as authoritative while required source semantics remain
  unresolved.
- Synthetic examples exercise DST where historical evidence is insufficient.

**Progress (ANL-001, ANL-002)**

| Item | Status |
|---|---|
| Inspection and modelling of the actual tariff workbook | done |
| Tariff dimension, price dimension, interval charge fact | done, in DuckDB |
| Decimal precision, currency units, explicit rounding rules | done |
| Coverage indicators and consumption charges | done — charged/excluded reconcile exactly |
| Effective-date joins with missing/overlapping-rate checks | partial — the dToU period is modelled; the flat rate's period is UNKNOWN and is not invented |
| Staging models and household dimension | not started |
| **Expressed as dbt models** | **not done — ANL-003** |

### ANL-003 — Port the tariff models into dbt (follow-up inside M3)

**Not a copy-and-paste job.** The SQL is written and tested, which is the starting point,
not the whole task. The port has to decide model boundaries and materialisations, wire
`ref`/`source`, handle the parts that are not SQL at all (reading the workbook, the price
catalogue, the schedule validation that refuses a duplicated key), re-express the
rerun-and-supersede policy in dbt's terms, and carry the run identity that makes a result
reproducible. Estimating it as "move the SELECTs" would be wrong.

**Deliver**

- The tariff models as dbt-duckdb models over the existing warehouse.
- A decided answer for the shared policy: **one** definition serving both dbt and Python,
  not the same rule written twice in two languages.
- A decided answer for the Python-side steps that have no SQL equivalent.
- dbt tests for the schedule primary key, band domain, price uniqueness and the
  charged-plus-excluded reconciliation identity.
- Run identity and the baseline/replay path preserved, not dropped in the move.

**Complete when**

- `dbt build` reproduces the figures in `anl-002-tariff-scenario.md` exactly.
- The policy rules still have **one** definition, not one per tool.
- The pytest suite keeps its hand-computable cases; dbt does not replace them.
- A captured baseline still replays into a fresh database and matches.

## M4 — Reconciliation, corrections and historical reproduction

**Progress (REC-001).** A first slice is built — see
[`tickets/REC-001-source-expansion.md`](tickets/REC-001-source-expansion.md): an accepted
baseline reproduced into a fresh database (17/17 fields), and the effect of adding one
member explained to a residual of exactly zero, with every charged-output difference
categorised and traceable to its source rows. Versioned inputs, code, configuration and
published results are in place. Late/revised readings, retrospective tariff changes and
synthetic register scenarios are **not** started.

**Deliver**

- Explicitly synthetic register scenarios based on real consumption shapes.
- Explained interval-versus-register differences.
- Late readings, revised readings and retrospective tariff changes.
- Versioned inputs, code/configuration and published results.

**Complete when**

- A previous published result can be reproduced.
- A correction produces an explained delta.
- Scenarios include meter exchange and estimate-to-actual replacement.
- Derived synthetic registers are never described as independent real evidence.

## M5 — Airflow orchestration and operational recovery

**Deliver**

- Authored DAGs for ingestion, modelling, checks and publication.
- Dependencies, retries, backfill parameters and useful run logs.
- Failure-injection demonstrations and a short recovery runbook.

**Complete when**

- The maintainer can explain retry versus backfill.
- A failed run is recovered without double-counting.
- A date-range rerun produces the expected versioned output.

## M6 — Bounded AWS deployment

**Deliver**

- S3 storage, suitable catalog/query services and workload execution.
- Terraform, least-privilege access and protected credentials.
- Monitoring, recorded costs and cleanup instructions.
- Select services for demonstrated needs; do not deploy every listed tool.

**Complete when**

- A small cloud run reproduces validated local analytical results.
- Infrastructure setup and cleanup are documented and exercised.
- Budget alerts exist, with explicit understanding that alerts are not hard caps.

## M7 — Spark evaluation and portfolio release

**Deliver**

- A focused Spark implementation of one substantial transformation.
- Equivalent-result checks against the established implementation.
- Runtime, memory and query-plan evidence under stated hardware/data conditions.
- GitHub setup instructions, CI, architecture and a short demonstration.
- README limitations, attribution and evidence-backed CV bullets.

**Complete when**

- Another person can run a small example without the full archive or paid cloud.
- Performance claims match measurements; no invented distributed-scale story.
- The maintainer can explain design choices and demonstrate a failure/recovery case.
- A small usable GitHub demonstration is delivered before all optional work ends.

---

## FORE — Forecasting

A strand alongside the milestones above, not a replacement for any of them. **dbt
(ANL-003), reconciliation (M4), Airflow (M5), cloud (M6) and Spark (M7) all stand
unchanged.**

**FORE-001 — evaluated consumption forecasting.** Built; see
[`tickets/FORE-001-forecasting-experiment.md`](tickets/FORE-001-forecasting-experiment.md).
Seven-day daily-total backtest over 40 eligible households with rolling origins and an
holdout: a four-week same-weekday mean reaches **1.901 kWh MAE** on holdout target days
averaging 10.1 kWh, beating a one-week seasonal naive (2.121) and a persistence reference
(2.322). A retrospective clean-run benchmark, not operational accuracy.

Candidate follow-ups are recorded, with evidence and prerequisites, in
[`ideas.md`](ideas.md). Recording an idea does not authorise it.

**Complete when** (for the strand, not FORE-001)

- A forecast is evaluated against a baseline it does not trivially beat.
- Eligibility and exclusions are decided before results and never adjusted to flatter one.
- No forecast is presented as a bill, a saving, or a claim about cause.

---

## Optional extension — AI incident assistant

**Optional. Not required for any milestone above.**

An AI incident assistant that explains quality failures using report evidence.

**Evaluate on:** factual accuracy, evidence references, appropriate uncertainty, latency and cost.

**Hard constraints:** it must **not** silently alter readings and must **not** calculate bills.

**On additional datasets:** any further dataset must answer a named product or engineering need.
