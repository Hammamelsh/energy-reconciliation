# ANL-003 — Port the tariff models to dbt

| Field | Value |
|---|---|
| Ticket | ANL-003 (roadmap M3; idea I-06) |
| Status | **Steps 0–2 implemented 2026-09-08. Steps 3–7 not started.** The staging view and the two policy models build and run; no tariff fact, dimension or publisher exists. |
| Design | [`../anl-003-dbt-design.md`](../anl-003-dbt-design.md) — read it first; this ticket only sequences it |
| Depends on | ANL-002 (`d3a97ce`), REC-001 (`4bbad6a`), accepted baseline `4b3ee235d7ac` |
| Out of scope | Any change to what is charged, excluded, rounded or assumed; household dimension; Airflow; incremental models |

## The business problem

The tariff scenario is correct and reproducible, but its SQL lives in Python strings.
The roadmap's M3 asks for the same models **as dbt models**, so their lineage, tests and
documentation are visible to the tooling most teams use, without the rules being written
twice. "Move the SELECTs" would break at least four things the current build guarantees
(one policy definition, atomic publish, run identity, replayable baselines). The design
decides where each piece goes so that none of them breaks.

## Before building — one understanding question for Hammam

> When dbt rebuilds the fact tables and fails halfway, what should someone reading the
> dashboard see a minute later — and which of the two options gives that: building the
> tables in place, or building into the `scenario_build` schema and publishing in one
> transaction?

Answer in your own words before step 5 starts. The reason this matters is design D5.

**A measurement that arrived after the question was written, and that the answer now has
to account for:** DuckDB locks the *file*, not the schema. While one process holds a
warehouse read-write, another process cannot open it **even read-only** (measured, design
D5). So neither option on its own gives a reader anything during the build — the choice
decides what a reader sees *afterwards*, and availability *during* is a third decision
(I-14) that is not yet made.

## Steps, each with the evidence that closes it

Every step ends with the full pytest suite passing. A step is not complete because its
code exists; it is complete when its evidence row is true.

| # | Step | Evidence that closes it | Stop rule |
|---|---|---|---|
| 0 | **DONE.** Pinned `dbt-core==1.12.4`, `dbt-duckdb==1.11.0` in main dependencies; `.gitignore` gained the three dbt artefact directories. **`identity.RUNTIME_PACKAGES` deliberately NOT extended — moved to step 5** (see design D1: in this slice dbt writes no stored figure, and claiming otherwise in the fingerprint is over-inclusion). | `uv run dbt --version` prints `dbt-core 1.12.4` / `duckdb 1.11.0`. 40 packages added; `duckdb`/`pyarrow`/`pandas`/`openpyxl` **unchanged**, so `runtime_fingerprint` is byte-identical (`13866bb5ca0d2093…`). `protobuf` downgraded 7.36.1 → 6.33.6 by `dbt-common`; recorded, takes no part in the arithmetic. Full suite passed **before** any code change with dbt installed. | — |
| 1 | **DONE.** `policy.distinct_readings_sql(relation)` / `conflicting_labels_sql(relation)` with the constants kept as their default renderings; a relation name is **validated** (`PolicyRelationError`), never interpolated blind, with the dbt placeholder permitted by name only. `compare.py`'s `FROM readings` string-replace is gone, replaced by the parameter. `uv run render-dbt-macros[ --check]` renders/verifies `dbt/macros/generated_policy.sql`. | Both rendered constants are **byte-identical to the pre-refactor committed text** (checked against `git show HEAD:…/policy.py`), so no figure could move. Render is deterministic (same SHA-256 twice). `tests/test_policy_sql.py` (14 cases incl. 9 refused injections) and `tests/test_dbt_macros.py` (7 cases) pass; the hand-edit test mutates a **temp copy**, never the repository file, and no check ever rewrites it. | — |
| 2 | **DONE.** `dbt/` project, committed credential-free `profiles.yml` whose path is `env_var('ENERGY_RECONCILIATION_DB')` **with no default**, an `on-run-start` guard that refuses a database with no `readings` table, `sources.yml`, `stg_readings` (view, columns listed not `SELECT *`), and the two ephemeral policy models whose bodies are **only** the generated macro. | `dbt build` succeeded (`PASS=2`). On an isolated copy of the three-member warehouse **dbt itself** returned distinct readings **2,997,962**, distinct labels 2,997,962, households 83, finite 2,997,881, on-grid 2,997,881, null 81, signatures 3,439, conflicting labels 0 — all equal to the Python path on the same database. `tests/test_dbt_equivalence.py` compares **every column of every row** on a fixture holding duplicates, equivalent representations, two conflicts, an off-grid row and a token. Both guards were exercised and fail loudly. | — |
| 3 | The two dims as Python models returning **typed pyarrow tables**; `schedule=demo` var | `information_schema.columns` shows `DECIMAL(9,4)` and `DECIMAL(9,6)` for the price columns; a workbook fixture with a duplicated label makes `dbt build` fail with `ScheduleError` and writes nothing | **If the DECIMAL types cannot be produced through the Python model, stop, switch to the design's fallback (dims as dbt sources loaded by Python) and record the reason in the design doc** |
| 4 | `int_classified_readings`, both facts, `schema.yml` tests, the six singular tests | `dbt build` on the demo warehouse passes every test; the reconciliation singular test fails when one exclusion flag is deliberately inverted (try it, then revert) | — |
| 5 | `build_scenario` orchestrates: skip rule unchanged → `dbtRunner` into `scenario_build` → one publish transaction → run record with `dbt_manifest_sha256`, `dbt_versions`; delete the SQL constants and `_load_dimensions` from `models.py`; extend `identity.calculation_files` to the dbt files with the glob-coverage test; baseline format 2 | A build that is killed after the first fact leaves `main` untouched (test with a failing singular test injected via var); rerun with identical inputs is `skipped=True` without a dbt invocation (assert the runner was not called); suite time measured and recorded | If the suite exceeds five minutes, apply dbt partial parsing with a shared `target/` — never a Python-only fast path |
| 6 | Reproduce ANL-002 on `energy.duckdb`; replay baseline `4b3ee235d7ac`; capture and replay a new baseline | Every figure in design §2 matches to the digit; the old baseline's replay report shows `scenario_fingerprint` as the **only** differing field; the new baseline replays 17/17 including `fact_row_sha256` | Any changed digit is a defect in the port, not a new result — stop and diagnose |
| 7 | Docs: `anl-002-tariff-scenario.md` gains a one-line "reproduced by dbt on <date>" note with the command; roadmap M3 row flips; `portfolio-evidence.md` "Used dbt" row moves from not-claimable to a narrowly worded claim; this ticket's status → done | The claims match the executed evidence, nothing broader | — |

## Acceptance criteria

| # | Criterion |
|---|---|
| 1 | `uv run dbt build --profiles-dir dbt --project-dir dbt --vars '{run_id: <id>, tariff_group: ToU}'` on `energy.duckdb` yields the design §2 figures exactly |
| 2 | The policy rules have one definition: `policy.py`; the macro file is generated and drift-tested; `models.py` holds no SQL |
| 3 | The `/ 100` division appears nowhere under `dbt/`; both price columns are `DECIMAL` |
| 4 | `charged + excluded = distinct readings` is a dbt singular test and still a `ScenarioResult` property |
| 5 | Identical inputs skip without invoking dbt; a failed build leaves the published scenario untouched |
| 6 | Baseline `4b3ee235d7ac` replays with every figure field equal and the fingerprint reported as the only difference; a new baseline replays 17/17 |
| 7 | pytest keeps every hand-computable case; suite time recorded |
| 8 | Rollback path documented and exercised once: replay the previous baseline into a fresh database (there is no in-place undo, by design) |

## Commands

```bash
uv run build-tariff-scenario --database data/warehouse/energy.duckdb   # existing entry point, keeps its name
uv run capture-baseline  --database data/warehouse/energy.duckdb
uv run replay-baseline   --baseline data/baselines/<file>.json --database data/warehouse/<fresh>.duckdb
uv run pytest -q

# working today (steps 0-2)
uv run render-dbt-macros            # regenerate dbt/macros/generated_policy.sql from policy.py
uv run render-dbt-macros --check    # verify it, never rewrite it

# Never point this at data/warehouse/energy.duckdb: dbt takes a write lock on the file
# and creates its own schema in it. Work on an isolated copy, made the supported way
# (source opened READ_ONLY, so the original cannot be written):
#   ATTACH 'data/warehouse/energy.duckdb' AS src (READ_ONLY);
#   ATTACH '/tmp/dev-energy.duckdb' AS dev;
#   COPY FROM DATABASE src TO dev;
export ENERGY_RECONCILIATION_DB=/tmp/dev-energy.duckdb
uv run dbt build --project-dir dbt --profiles-dir dbt
uv run dbt show  --project-dir dbt --profiles-dir dbt --output json \
  --inline "select count(*) from {{ ref('int_distinct_readings') }}"   # -> 2997962

# proposed, NOT yet available (steps 3-5 add the vars and the models they configure):
# uv run dbt build --project-dir dbt --profiles-dir dbt --vars '{run_id: dev, tariff_group: ToU, schedule: demo}'
```

## Learning checkpoints (Hammam's, never marked automatically)

- Explain why a generated macro with a drift test is one definition and two hand-written
  copies with a comparison test are not.
- Explain why a pandas column of `Decimal` objects is a risk here and what a typed pyarrow
  table changes.
- Explain what a reader sees during a failed build under D5, and why `run_id` scoping in
  `analytics` is what makes that safe.
