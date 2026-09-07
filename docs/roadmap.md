# Delivery roadmap

**What this is.** Seven delivery milestones for the Energy Billing and Reconciliation Simulator, each
with what it delivers and the condition under which it is complete.

**What this is not.** These are **delivery milestones, not promises of seniority or employment**.
Completing a milestone means an artefact exists and its completion condition is satisfied — nothing
more. No milestone carries a date; completion conditions are the only measure used here.

**Status:** M1 is in progress. See [`../README.md`](../README.md) for what runs today, and
[`source-data-profile.md`](source-data-profile.md) section 16 for the REP-001 assessment.

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

## M4 — Reconciliation, corrections and historical reproduction

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

## Optional extension — AI incident assistant

**Optional. Not required for any milestone above.**

An AI incident assistant that explains quality failures using report evidence.

**Evaluate on:** factual accuracy, evidence references, appropriate uncertainty, latency and cost.

**Hard constraints:** it must **not** silently alter readings and must **not** calculate bills.

**On additional datasets:** any further dataset must answer a named product or engineering need.
