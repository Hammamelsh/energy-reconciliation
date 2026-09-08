# ANL-002 — Reproducible, assumption-labelled tariff scenario

| Field | Value |
|---|---|
| Ticket | ANL-002 |
| Status | **Built and measured (2026-09-08).** Findings: [`../anl-002-tariff-scenario.md`](../anl-002-tariff-scenario.md) |
| Milestone | M3 (partial) — modelling and scoped cost calculations |
| Depends on | ANL-001 (workbook inspection), ING-001 (ingestion and policies) |
| Out of scope | Bills, savings claims, forecasting, AI features, geography, cloud |

## Why this is next

ANL-001 established what the workbook contains — a schedule of price bands, not prices —
and proposed a three-table model. Nothing was built and no cost was calculated. This
ticket builds the model, loads a bounded real `ToU` sample, computes the scenario and
measures it.

## Decided: where the models live

**Not in dbt, yet — and this is a sequencing adjustment worth stating.**
`docs/roadmap.md` places tariff modelling in **M3 alongside dbt**, and M3 had not
started; M2 is only partly delivered. Two things decided it:

1. The duplicate, conflict, missing-value and off-grid rules lived as SQL fragments
   inside `explorer/queries.py`. Re-expressing them in dbt SQL would have created a
   **second, independently maintained implementation of the same policy** — the specific
   failure this ticket was told to avoid.
2. The validation this ticket needs is hand-computable synthetic cases over temporary
   warehouses. Those are pytest-shaped, not dbt-run-shaped.

So the rules were lifted into one shared module (`src/energy_reconciliation/policy.py`)
imported by both the explorer and the new models, and each model was written as **one
named SELECT** materialising a real table in DuckDB. Business logic is out of Streamlit
entirely: the new tab reads tables and computes nothing.

**The cost, stated plainly: M3's dbt deliverable is not met by this ticket.** Tracked as
**ANL-003** — and that ticket is not a copy-and-paste of these SELECTs. It has to choose
model boundaries and materialisations, wire `ref`/`source`, handle the steps that are not
SQL (the workbook read, the price catalogue, the schedule validation), re-express the
rerun-and-supersede policy, and keep the run identity and replay path intact.

## Rerun policy — decided

**Content-addressed replace, one scenario per warehouse**, mirroring ING-001 rather than
inventing a second policy. The fingerprint covers the schedule source and its digest, a
digest of the schedule contents, the price catalogue version, the modelling code and
`policy.py`, the ingestion pipeline fingerprint, the tariff-group scope and the set of
published load ids. Unchanged inputs skip; any change supersedes the previous run.

The schedule-contents digest was added after a test revealed the gap: a fixture that
declared a fixed digest for two different schedules produced the same fingerprint. In
production the digest is always content-derived, so the defect was in the fixture — but
including the contents makes the whole class of mistake impossible.

## Decided: rounding

No row-level rounding anywhere. Rounding once at the output stage: money 2 dp, energy
3 dp, shares 4 dp, `ROUND_HALF_UP`, with the exact unrounded figure carried beside every
rounded one.

The `÷ 100` in the charge formula is done in Python `Decimal` when the price catalogue is
built, **not** in SQL, because DuckDB evaluates `DECIMAL / 100` as `DOUBLE` and would
reintroduce binary floats into a money-adjacent figure.

## Decided: what withholds and what scopes

A conflicting label withholds **that label**; the subtotal that remains is a **scoped**
subtotal published beside the excluded count and its reasons. Nothing becomes zero.
The reconciliation identity `distinct readings = charged + excluded` is asserted by the
build, by the tests and by the explorer.

## Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Schedule and prices modelled separately, with units, evidence labels and citations | **met** |
| 2 | Flat-rate effective dates recorded as UNKNOWN, never defaulted | **met** |
| 3 | Every charged row carries `assumption_id` A1; the run records it too | **met** |
| 4 | Decimal arithmetic; stated precision; rounding only at output | **met** |
| 5 | Every distinct reading is charged or excluded with one explicit reason | **met** — reconciles on real and synthetic data |
| 6 | Joins cannot multiply consumption rows | **met** — schedule PK, duplicates refused at load, asserted in tests |
| 7 | Member 135 loaded; `Std` sample and demo kept as separate contexts | **met** |
| 8 | Schedule-wide results distinguished from loaded-household results | **met** |
| 9 | Run identity sufficient to reproduce | **met** |
| 10 | Compact explorer view with the assumption visible | **met** |
| 11 | Hand-computable synthetic cases for units, boundaries, duplicate keys, unmatched, outside-period, conflicts and repeated autumn labels | **met** — 31 tests |
| 12 | Real-data outputs verified separately from synthetic expectations | **met** — independent Python `Decimal` recomputation |
| 13 | Ported to dbt | **not met** — deferred to ANL-003, which is a design task, not a move |
| 14 | Three scenario scopes separated, each with an explicit period bounded by schedule coverage | **met** |
| 15 | Share chart readable: horizontal grouped bars, one 0–100% axis, direct labels, accessible table | **met** |
| 16 | Excluded households given their **measured** reason, with an explicit switch to a charged household | **met** |
| 17 | Calculation identity covers the shared `policy.py` and the runtime, verified against the real import closure | **met** |
| 18 | A baseline replays into a fresh database and reproduces every figure | **met** — executed |
| 19 | An unreadable tariff schema produces a recovery instruction, not a raw database error, and the other three tabs keep working | **met** — after a real incident; `tests/test_tariff_schema.py` |
| 20 | Price validity is an explicit half-open interval, enforced in the join independently of schedule coverage; all six boundary timestamps verified through the whole build | **met** — acceptance review |
| 21 | A period-scoped exclusion count never silently becomes a whole-history count | **met** — whole history only under an explicit label |
| 22 | Replay compares every charged row, not only aggregates | **met** — executed |

## Found by executing the replay, not by testing

Both defects were invisible to tests that only ever built one warehouse.

1. **Fingerprint over-sensitivity.** Hashing `tariff/*.py` by glob meant adding the replay
   tooling invalidated a scenario whose every figure was identical. A signal that fires on
   unrelated edits stops being read. The covered set is now an explicit list of files that
   can change a *stored* figure, guarded by a test against the models' real import closure.
2. **Fingerprint irreproducibility.** It included published `load_id`s, which embed the
   moment of loading — so byte-identical data in a fresh database could never fingerprint
   the same, and no replay could ever have matched. It now keys on member name, content
   digest and pipeline fingerprint.

## Not done, deliberately

- No bill, cost-of-living figure, saving or tariff comparison.
- No causal claim about price signals. The measurement cannot support one.
- No geographic breakdown; that stays conditional on legitimately linked metadata.
- No `Std` costing, because the flat rate's effective period is UNKNOWN.
