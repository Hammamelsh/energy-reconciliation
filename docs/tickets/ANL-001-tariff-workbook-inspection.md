# ANL-001 — Tariff workbook inspection

| Field | Value |
|---|---|
| Ticket | ANL-001 |
| Status | **Inspection complete (2026-09-08); model proposed; no costs published.** Findings: [`../anl-001-tariff-workbook-findings.md`](../anl-001-tariff-workbook-findings.md) |
| Milestone | M3 prerequisite |
| Depends on | ING-001 |

## Why this is next

`Tariffs.xlsx` has been verified as a structurally sound three-worksheet workbook
(`docs/source-data-profile.md` §9.8), but **not one cell has been read**. Every tariff
question in M3 — effective-date joins, missing or overlapping rate periods, which price
band applied when — depends on what that workbook actually contains.

## Scope

- Read the workbook's structure: sheet names, headers, column types, row counts.
- Record the exact date and time representation used, and whether it shares the
  consumption data's unresolved timezone problem.
- Establish how price bands map to periods, and find missing or overlapping ranges.
- Label every finding VERIFIED, PUBLISHER-DOCUMENTED, INFERRED or UNKNOWN.

## Out of scope

Joining tariffs to consumption, and calculating any cost. Both wait until the timezone
convention and interval anchor are resolved, or until an explicit reversible assumption
is recorded.
