# ANL-003 — Port the tariff models to dbt

| Field | Value |
|---|---|
| Ticket | ANL-003 (roadmap M3; idea I-06) |
| Status | **Design complete 2026-09-08 — implementation pending. No dbt code exists yet.** |
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

## Steps, each with the evidence that closes it

Every step ends with the full pytest suite passing. A step is not complete because its
code exists; it is complete when its evidence row is true.

| # | Step | Evidence that closes it | Stop rule |
|---|---|---|---|
| 0 | Pin `dbt-core==1.12.4`, `dbt-duckdb==1.11.0` in main dependencies; add `dbt/target/`, `dbt/logs/`, `dbt/dbt_packages/` to `.gitignore`; add both packages to `identity.RUNTIME_PACKAGES` | `uv sync` succeeds; `uv run dbt --version` prints both versions; a fresh scenario run records them in `runtime_detail` | If `uv` cannot resolve these exact versions, record the resolvable ones and why — do not float the pins |
| 1 | Parameterise `policy.py` (`distinct_readings_sql(readings)`, `conflicting_labels_sql(readings)`); keep the constants; write `render-dbt-macros`; commit `dbt/macros/generated_policy.sql`; add the drift test | All existing tests pass unchanged; `git diff` of rendered SQL for the Python path is empty; the drift test fails when one byte of the macro file is edited by hand (try it, then revert) | — |
| 2 | dbt project skeleton, `sources.yml`, `stg_readings`, the two ephemeral policy models | `dbt build --select stg_readings` against the demo warehouse; `count(*)` of a temporary `select * from {{ distinct_readings(...) }}` equals `count(*) FROM v_distinct_readings` on `energy.duckdb` (2,997,962) | — |
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

## Commands (as established today; dbt commands are proposed, not yet runnable)

```bash
uv run build-tariff-scenario --database data/warehouse/energy.duckdb   # existing entry point, keeps its name
uv run capture-baseline  --database data/warehouse/energy.duckdb
uv run replay-baseline   --baseline data/baselines/<file>.json --database data/warehouse/<fresh>.duckdb
uv run pytest -q
# proposed after step 2:
uv run render-dbt-macros
uv run dbt build --profiles-dir dbt --project-dir dbt --vars '{run_id: dev, tariff_group: ToU, schedule: demo}'
```

## Learning checkpoints (Hammam's, never marked automatically)

- Explain why a generated macro with a drift test is one definition and two hand-written
  copies with a comparison test are not.
- Explain why a pandas column of `Decimal` objects is a risk here and what a typed pyarrow
  table changes.
- Explain what a reader sees during a failed build under D5, and why `run_id` scoping in
  `analytics` is what makes that safe.
