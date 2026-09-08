# REC-001 — Reproduce a result and explain a source expansion

| Field | Value |
|---|---|
| Ticket | REC-001 |
| Status | **Measured 2026-09-08; residual exactly zero.** Findings: [`../rec-001-source-expansion.md`](../rec-001-source-expansion.md) |
| Milestone | M4 (first slice) — reconciliation and historical reproduction |
| Depends on | ANL-002 (accepted tariff milestone) |
| Out of scope | Forecasting, geography, AI, new datasets, dbt |

## Why this is next

The tariff scenario produced a defensible figure. The project's question is whether a
*later* figure can be explained against it. This ticket takes the accepted baseline,
rebuilds it, adds one member, and requires every difference in the charged output to
carry a category, a reason and its source rows — with the reconciliation closing exactly.

## Decided: the comparison must refuse an uninterpretable difference

Nine identity fields must be equal (calculation code, policy, model code, runtime, price
catalogue, assumption, tariff-group scope, schedule digest, ingestion pipeline), every
baseline member must be present with identical content, and at least one member must be
added. Otherwise the difference is not attributable to source, and the tool errors rather
than reporting a number nobody can interpret.

## Decided: removals are first-class

Adding a member can **lower** the charge: a new row can dispute an already charged
reading, and the conflict policy then withholds it. Removals are reported with the reason
recorded in the comparison warehouse and the source rows on **both** sides of the dispute,
each with member and record number.

## Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Accepted baseline identified by content, not filename | **met** |
| 2 | Reproduced into a database that did not exist; 17/17 fields matched | **met** |
| 3 | Comparison warehouse separate; baseline members byte-identical | **met** |
| 4 | Differences separated by grain and category | **met** |
| 5 | `baseline + signed adjustments = comparison`, residual reported | **met** — `0E-16`, exactly zero |
| 6 | Every charged-output difference has evidence and a reason | **met** |
| 7 | New readings that produced **no** charge also explained | **met** — `outside_schedule_period`, with dates |
| 8 | An affected household traceable to its source observations | **met** — member and record number |
| 9 | A decrease and a withholding demonstrated | **met** — synthetic, hand-derived |
| 10 | Existing baselines, archives and warehouses preserved | **met** |

## Not done, deliberately

No forecasting, geography or AI. No dbt (ANL-003). The comparison view is a CLI report
rather than a dashboard tab: the audience is a reviewer reading evidence, and the JSON
carries every source reference a follow-up would need.
