# ANL-003 — Design: porting the tariff models to dbt

**Date:** 2026-09-08. **Status: steps 0–4 BUILT; steps 5–7 not built.** The staging view,
the two policy models, both tariff dimensions, the classification and **both facts** exist,
run, and reproduce §2's figures exactly. **No publisher does.** The published scenario is
still built entirely by `build-tariff-scenario`, from its own dimensions, and consumes
nothing dbt produces. dbt is installed (versions in D1). The ticket that would build
it is [`tickets/ANL-003-dbt-port.md`](tickets/ANL-003-dbt-port.md). The roadmap entry it
answers is `roadmap.md` § M3 → ANL-003.

The working SQL it starts from is `src/energy_reconciliation/tariff/models.py`; the rules
it must not duplicate are `src/energy_reconciliation/policy.py`. Read those first — this
document decides *where each piece goes*, not what the arithmetic is.

## 0. What the port has to keep true

These are the properties the current implementation has and the roadmap's completion
conditions require. Every decision below is checked against them.

| # | Property today | Where it is enforced today |
|---|---|---|
| P1 | The four analytical policies have **one** definition, used by the explorer and the tariff models | `policy.py` constants, imported by both |
| P2 | A duplicated schedule label is **refused before any row reaches the warehouse** | `schedule._validate` |
| P3 | `price_gbp_per_kwh` is the pence price ÷ 100 done **once, exactly, in Python `Decimal`**; the division is never written in SQL | `prices.Price.gbp_per_kwh`; `models.py` docstring |
| P4 | Every fact row carries `assumption_id = 'A1'` and `run_id` | `FACT_SELECT` |
| P5 | `distinct readings = charged + excluded`, every exclusion with **one** reason and every condition as its own flag | `EXCLUSION_ORDER`, `ScenarioResult.reconciles` |
| P6 | Rerunning identical inputs is a **provable no-op**; a changed input **supersedes** rather than accumulates | `scenario_fingerprint`, `build_scenario` skip path, `status` column |
| P7 | The whole build is **atomic**: a failure leaves the previous published scenario as it was | one DuckDB transaction in `build_scenario` |
| P8 | The run record names every input and every piece of code that can change a figure | `identity.calculation_files`, `scenario_run` columns |
| P9 | A captured baseline **replays** into a fresh database and matches field by field | `baseline.replay` → `build_scenario` |
| P10 | pytest keeps its hand-computable cases (44 test builds today) | `tests/test_tariff*.py`, `test_rec001_comparison.py` |

## 1. Decisions

Each decision names the alternatives that were on the table and why they lost.

### D1 — Layout: one dbt project in `dbt/`, `dbt-duckdb` over the existing warehouse

```
dbt/
  dbt_project.yml          name: energy_reconciliation; profile: energy_reconciliation
  profiles.yml             duckdb; path from env ENERGY_RECONCILIATION_DB
                           (default data/warehouse/energy.duckdb); target schema scenario_build
  models/
    sources.yml            source warehouse: readings, load_registry (schema main)
    staging/
      stg_readings.sql               view   — the source, column-contracted, nothing else
    policy/
      int_distinct_readings.sql      ephemeral — {{ distinct_readings(ref('stg_readings')) }}
      int_conflicting_labels.sql     ephemeral — {{ conflicting_labels(ref('stg_readings')) }}
    tariff/
      dim_tariff_band_schedule.py    table  — Python model (D3)
      dim_tariff_price.py            table  — Python model (D3)
      int_classified_readings.sql    ephemeral — today's CLASSIFIED_READINGS, with ref()
      fact_interval_charge_scenario.sql   table
      fact_interval_charge_exclusion.sql  table
      schema.yml                     column tests (D7)
  macros/
    generated_policy.sql   GENERATED from policy.py + models.EXCLUSION_ORDER (D2). Do not edit.
  tests/                   singular tests (D7)
```

`dbt/target/`, `dbt/logs/` and `dbt/dbt_packages/` are git-ignored. `profiles.yml` is
committed inside the project directory (`--profiles-dir dbt`), so a clone runs without
touching the user's home directory.

**Versions — INSTALLED 2026-09-08 and verified by `dbt --version`:** `dbt-core 1.12.4`,
`dbt-duckdb 1.11.0`, both pinned exactly in `pyproject.toml` main dependencies. 40
packages were added. **The four packages that evaluate the arithmetic are unchanged**
(`duckdb 1.5.5`, `pyarrow 25.0.1`, `pandas 3.0.5`, `openpyxl 3.1.5`), so the recorded
runtime identity did not move. One existing package was **downgraded**: `protobuf`
7.36.1 → 6.33.6, required by `dbt-common`. It takes no part in the scenario arithmetic
and is not in `RUNTIME_PACKAGES`; it is recorded here because a downgrade should never be
discovered later from a lockfile.

**`identity.RUNTIME_PACKAGES` was NOT extended in step 0** — a deliberate departure from
this document's first draft. Adding dbt there would assert that dbt evaluated the stored
figures, and in steps 0–2 dbt produces no stored figure at all. Recording it now would be
the over-inclusion that `identity.py` already warns about: an invalidation signal that
fires for things that cannot change a result stops being believed. dbt joins
`RUNTIME_PACKAGES` and `calculation_files()` in **step 5**, when it first writes a fact.

**The supported entry point is `uv run run-dbt`, and the guarantee is its, not dbt's.**
`env_var()` without a default stops an *unset* variable, but a variable set to a *wrong*
path is worse: DuckDB creates a database at any path it is given, so dbt would open — and
thereby create — an empty warehouse, and the in-project `on-run-start` hook only rejects it
afterwards. `run-dbt` validates first: non-empty string, then `exists`, then a
**read-only** connection (which DuckDB never creates a file for), then `main.readings`.
A refused path leaves nothing on disk. **Running `dbt` directly is unguarded** — it still
creates the empty file before the hook fires — and the hook stays as the backstop for that
route. Neither replaces the other, and the ticket says so where the commands are listed.

*Rejected:* a separate repository or a `dbt/` package that vendors its own copy of the
warehouse path. The models must read the warehouse that ingestion writes; one path, one
environment variable.

### D2 — One policy definition: Python is the source, a **generated macro file** is the dbt copy, a test refuses drift

The four policy rules stay where they are, in `policy.py`. Two changes make them usable
from dbt without a second definition:

1. **Parameterise the relation name.** Today `DISTINCT_READINGS` and `CONFLICTING_LABELS`
   hard-code `FROM readings`. They become functions of the relation they read:

   ```python
   def distinct_readings_sql(readings: str = "readings") -> str: ...
   def conflicting_labels_sql(readings: str = "readings") -> str: ...
   DISTINCT_READINGS = distinct_readings_sql()        # existing callers unchanged
   CONFLICTING_LABELS = conflicting_labels_sql()
   ```

   The Python callers (`compare.py`, `explorer/queries.py`, `models.py` until D5 removes
   it) keep importing the constants and produce byte-identical SQL. The existing 333 tests
   are the check that nothing moved.

2. **Render the macros from Python.** A small command, `uv run render-dbt-macros`, writes
   `dbt/macros/generated_policy.sql`:

   ```jinja
   {# GENERATED from src/energy_reconciliation/policy.py and tariff/models.py.
      Edit those and run `uv run render-dbt-macros`. A test fails if this file drifts. #}
   {% macro distinct_readings(readings) %}
   <distinct_readings_sql("{{ readings }}")>
   {% endmacro %}
   {% macro conflicting_labels(readings) %} ... {% endmacro %}
   {% macro finite_category() %}'finite_numeric'{% endmacro %}
   {% macro flat_band() %}'flat'{% endmacro %}
   {% macro exclusion_reason_case() %}
   CASE WHEN is_ineligible_group THEN 'ineligible_tariff_group' ... END
   {% endmacro %}
   {% macro exclusion_flags_any() %}is_ineligible_group OR ... {% endmacro %}
   {% macro exclusion_reasons() %}('ineligible_tariff_group', ...){% endmacro %}
   ```

   **Extended at step 4.** The generator now also renders `classified_readings`,
   `scenario_fact`, `exclusion_fact`, `exclusion_reason_case` and `exclusion_reasons`,
   from `models.classified_readings_sql`, `models.fact_projection_sql`,
   `models.exclusion_projection_sql` and `EXCLUSION_ORDER` — the same functions the Python
   path calls. That was not optional: eligibility, schedule coverage, conflict, off-grid,
   missing value, unmatched label, unpriced band and the reason precedence are *rules*, and
   hand-writing them in a dbt model would have been the second implementation this
   decision exists to prevent. `models.py`'s published SQL constants are now the default
   renderings of those functions and are **byte-identical to their previous values**, so no
   figure could move.

   The generated file **is committed** — dbt needs it present — and
   `tests/test_dbt_generated.py` asserts that a fresh render equals the committed bytes.
   Editing the macro by hand, or editing `policy.py` without re-rendering, fails the suite.
   The exclusion order and reason names come from `models.EXCLUSION_ORDER` through the
   same generator, so the CASE ordering (P5) has one definition too.

The warehouse's inspection views (`v_distinct_readings`, `v_conflicting_keys`, written by
ingestion) are **not** read by any dbt model; they remain diagnostics, and the ticket's
step 2 uses them only as an independent count to check the macro against.

*Rejected — write the rules in Jinja and have Python read the macro file:* Python would
need a Jinja renderer just to obtain a SELECT, the module docstring that explains each
rule would move into a template comment, and the explorer would take a dbt dependency it
does not otherwise need.
*Rejected — dbt Python models for the policy layer:* they would import `policy.py`
directly, but the lineage from `readings` to the facts would then be invisible to
`ref`/`source`, which is most of what the port is for.
*Rejected — two hand-maintained copies with a comparison test:* that is the "same rule
written twice in two languages" the roadmap forbids, with a test as an apology.

### D3 — The non-SQL steps become **dbt Python models** that call the existing Python

Two things in today's build are not SQL: reading and validating the workbook
(`schedule.read_workbook`) and the price catalogue with its exact ÷100 (`prices.CATALOGUE`).
They become Python models, which `dbt-duckdb` runs **in-process** with the same interpreter
and the same installed package:

```python
# dbt/models/tariff/dim_tariff_band_schedule.py
def model(dbt, session):
    dbt.config(materialized="table")
    from energy_reconciliation.tariff.schedule import demo_schedule, read_workbook, loaded_at
    which = dbt.config.get("schedule", "workbook")       # var: schedule=workbook|demo
    schedule = demo_schedule() if which == "demo" else read_workbook()
    return schedule_arrow_table(schedule, loaded_at())   # pyarrow, typed (below)
```

- **P2 holds unchanged** because `_validate` runs inside `read_workbook`; a duplicated
  label raises `ScheduleError`, the model fails, dbt stops, nothing is written.
- **P3 holds unchanged** because `Price.gbp_per_kwh` is the only place the division exists.
- **Types are declared, not inferred.** The models return **pyarrow tables** with explicit
  `decimal128(9,4)` / `decimal128(9,6)` columns, not pandas frames. A pandas column of
  Python `Decimal` objects is dtype `object`, and letting DuckDB infer it risks `DOUBLE` —
  the exact artefact P3 exists to prevent. A pytest checks `information_schema.columns`
  after a build: both price columns must be `DECIMAL`, with the scales above.
- The synthetic schedule is selected with `--vars '{schedule: demo}'`, which is how the
  committed demo archive keeps working without the workbook.

**BUILT 2026-09-08, and it works as designed.** `dim_tariff_band_schedule` and
`dim_tariff_price` are dbt Python models calling `dimensions.schedule_table` /
`dimensions.price_table`, which return `pyarrow` tables whose schema names the scales.
Measured on the persisted tables, not on the Arrow schema:
`price_pence_per_kwh DECIMAL(9,4)`, `price_gbp_per_kwh DECIMAL(9,6)`, both `effective_*`
columns `DATE` and NULL for the flat rate. All four prices equal the published figures,
and `price_gbp_per_kwh * 100 = price_pence_per_kwh` exactly in the database. From the
publisher's workbook the schedule dimension is 17,520 rows, and both dimensions are
**row-for-row identical to the ones the Python path builds** (0 rows differ, comparing
every column except the build timestamp). The design's fallback was not needed.

**Discovery — `CREATE TABLE AS SELECT` drops constraints.** dbt materialises a table with
CTAS, which carries column names and types and **not** `PRIMARY KEY` or `NOT NULL`. So a
dbt-built dimension has `models.SCHEMA`'s types but not its key. The duplicate-label
refusal is unaffected, because it happens in `schedule._validate` before a row exists, but
the *declared* uniqueness is gone and has to be re-asserted by a dbt test (step 4).
Restoring the constraints themselves would need dbt model contracts — recorded as I-15,
not done here.

**Discovery — the failure boundary is per model, not per build.** When the schedule model
raises `ScheduleError`, dbt fails that model and **still builds the models that do not
depend on it**. Measured: on a fresh target the schedule dimension is not created at all
(not empty, not partial — absent), and where a valid one already exists its rows and
column layout are byte-identical afterwards, with no `__dbt_tmp` relation left behind. But
`dim_tariff_price` and `stg_readings` are built in the same failing run. That is a real
guarantee and a real limit, and step 5's publisher cannot infer whole-build atomicity
from it.

*Rejected — keep `_load_dimensions` in Python and declare the dims as dbt sources:* it
works, and is the fallback if the Python-model path proves awkward, but then
`dbt build` alone does not reproduce ANL-002 from warehouse + workbook, which is the
roadmap's completion condition. *Rejected — re-express the workbook read as SQL over
`read_xlsx`:* the duplicate-label refusal and the ÷100 would then need SQL re-expressions,
which is two definitions again.

### D4 — Model boundaries and materialisations

| Model | Materialisation | Why |
|---|---|---|
| `stg_readings` | view | A column contract on the source and nothing else; free to query, never stores a copy of 3 million rows. |
| `int_distinct_readings`, `int_conflicting_labels` | ephemeral | Exactly today's CTEs; inlined into the consumer, so no intermediate table can go stale. |
| `dim_tariff_band_schedule`, `dim_tariff_price` | table (Python) | Small, must be materialised for the PK/uniqueness tests to run against real rows. |
| `int_classified_readings` | ephemeral | Today's `CLASSIFIED_READINGS`; both facts read it, and inlining keeps the two facts from ever seeing different classifications. |
| `fact_interval_charge_scenario`, `fact_interval_charge_exclusion` | table | The published result; stamped with `var('run_id')` and `'A1'`. |
| `scenario_run` | **not a dbt model** | Written by Python after a successful build (D5). |

**Grains and keys, stated once** (the same words `compare.py` uses):

| Model | One row per | Key | Enforced by |
|---|---|---|---|
| `stg_readings` | raw source row as loaded | (`load_id`, `source_record_no`) | none — duplicates are evidence, not errors |
| `int_distinct_readings` | **distinct reading**: (household, source label, value signature) | those three | `SELECT DISTINCT` in the policy macro |
| `int_conflicting_labels` | label where the source disagrees with itself | (household, source label) | `GROUP BY ... HAVING` |
| `dim_tariff_band_schedule` | schedule half-hour label | `schedule_label_naive` | `_validate` (P2) **and** a dbt `unique` test |
| `dim_tariff_price` | price for a group and band | (`tariff_group`, `band_label`) | dbt `unique_combination_of_columns` |
| `fact_interval_charge_scenario` | **charged output**: one per (household, source label) | (`run_id`, `household_id`, `source_timestamp_text`) | dbt `unique_combination_of_columns` — a conflicted label has two signatures and is excluded entirely, so the charged output is unique by construction and the test proves it |
| `fact_interval_charge_exclusion` | excluded **distinct reading** | (`run_id`, household, label, `value_signature`) | not unique on (household, label) by design: a conflicted label yields one exclusion row per signature |

The exclusion table today does not carry `value_signature`; the port adds it, so the
grain is visible in the row rather than only in the docstring. It is a new column, not a
changed figure.

The classification SQL moves out of `models.py` into `int_classified_readings.sql` with
three substitutions: `FROM readings` → `{{ ref('stg_readings') }}` via the macro
argument, `dim_*` → `{{ ref(...) }}`, and the two `?` placeholders →
`'{{ var("tariff_group") }}'` and `'{{ var("run_id") }}'` (quoted as string literals; both
vars are required, with no default, so a build without them fails at parse time rather
than charging the wrong group). The product stays
`CAST(consumption_kwh * price_gbp_per_kwh AS DECIMAL(38,16))` — DECIMAL × DECIMAL in
DuckDB is exact, and the singular test in D7 recomputes it row by row. After D5 the SQL constants in `models.py` are **deleted**, so the
dbt models are the definition and Python holds no copy.

### D5 — Rerun, supersede and atomicity in dbt terms: **Python orchestrates, dbt builds into a staging schema, Python publishes in one transaction**

dbt's `table` materialisation replaces each table independently; there is no
transaction across models. Left as is, a failure on the second fact would leave the
first replaced and the previous run's rows gone — P7 broken. The design keeps P6 and P7 as
follows:

1. `build_scenario` keeps its signature and its skip rule. It computes the fingerprint
   exactly as today (with the dbt files added to the digest, D6). If the published run
   carries the same fingerprint and `force` is off, it returns `skipped=True` **without
   invoking dbt at all** — the no-op stays provable and cheap.
2. Otherwise it invokes dbt **in-process** through `dbt.cli.main.dbtRunner` with
   `build --vars {run_id, tariff_group, schedule}` and target schema **`scenario_build`**.
   dbt tests run as part of `build`; a failing test aborts before anything is published.
3. On success Python opens **one transaction** on the warehouse:
   `CREATE OR REPLACE TABLE main.<fact> AS SELECT * FROM scenario_build.<fact>` for the
   two facts and the two dims, `UPDATE scenario_run SET status='superseded'` for the
   previous run, `INSERT` the new run record, commit. DuckDB's DDL is transactional, so a
   reader sees the old scenario or the new one, never a mixture.
4. On any failure nothing in `main` has changed; `scenario_build` holds the partial build
   for diagnosis and is dropped at the start of the next attempt.

Readers already scope every query by the published `run_id`
(`analytics._fact_scope`), so this changes nothing for them.

**Atomic publication is not the same problem as reader availability, and a staging
schema does not solve the second.** DuckDB locks the **file**, not the schema. Measured
on duckdb 1.5.5, two processes, this machine:

| While one process holds the file | another process opening read-write | another opening read-only |
|---|---|---|
| read-write | **refused** (`IOException: Could not set lock`) | **refused** |
| read-only | **refused** | opened |

So a dbt build that holds the warehouse read-write makes the dashboard unable to open it
**at all** — not stale, unopenable — and a dashboard holding it read-only blocks the
build. Building into `scenario_build` inside the same file changes nothing about this,
because the lock is taken on the file the schema lives in. D5's transaction therefore
buys atomicity (a reader never sees half a scenario) and buys **nothing** about
availability. The publisher in step 5 must additionally decide one of: a short declared
write window with readers retrying; readers pointed at a published copy rather than the
live warehouse; or the build running in a separate file and only the publish touching the
warehouse. **Not decided here, and not implemented in this slice** — recorded as I-14.

**What must remain true whatever is chosen:** a failed build leaves the last successful
published result **and its identity** intact — the `scenario_run` row, its fingerprint and
its digests included, not merely the fact rows.

**A build record is not a certificate of the tables (measured at step 4).** dbt fails per
model, so a failed run can still leave independently successful models rebuilt. `run-dbt`
returns dbt's non-zero exit and records **nothing** for a failed attempt, which keeps the
log truthful about builds. It does not, and cannot, make the earlier success row describe
the schema afterwards: after a partial rebuild some candidate tables are new and others
are as they were, while the last row still reads "succeeded". Reading a candidate table
therefore requires the last build to have succeeded, not merely for a success to be on
record. Step 5's publisher is where that becomes a guarantee rather than a caveat.

**Rollback.** There is no in-place undo today and the port does not add one: when a run
supersedes another, the previous rows are gone (as they are now). The recovery path is
the one REC-001 already uses — replay the previous baseline into a **fresh** database
from the recorded input identity — plus `force=True` to rebuild in place from a checked-out
earlier commit. The ticket exercises the replay once as acceptance criterion 8.

**Baseline equivalence.** `baseline.compare` checks six figure fields, the fingerprint,
and the SHA-256 over every charged row. After the port the figure fields and the row
digest must be equal; the fingerprint differs because `calculation_digest` now covers the
dbt files. The replay report therefore names the fingerprint as the single expected
difference, and a format-2 baseline captured afterwards is the new reference.

*Rejected — dbt `on-run-end` hook writing `scenario_run`:* a hook cannot decide to skip
the whole build, and the fingerprint needs the Python identity functions.
*Rejected — build directly into `main`:* loses P7. *Rejected — dbt's own `--state`
comparison as the skip rule:* it compares model source, not schedule contents, price
version, runtime or input identity, all of which the fingerprint must cover.

### D6 — Run identity extends to the dbt files; nothing is dropped

**Already done at step 3, because dbt now persists analytical tables.** The dimensions are
real outputs, so which dbt produced them is part of what they are. `run-dbt` writes one row
to `scenario_build.dbt_build_run` after a successful build: `dbt-core` and `dbt-duckdb`
versions, Python version, the schedule variant, a digest over the dbt project files, and
the policy and calculation digests. It is **separate from `scenario_run`** and creates
nothing in `main`, because these are *candidate* outputs: the published scenario is still
built by `build-tariff-scenario` from its own dimensions and consumes none of them. A
failed build records nothing. `identity.RUNTIME_PACKAGES` and `calculation_files()` are
still unchanged for the same reason, and `tariff/dimensions.py` joins
`CALCULATION_TARIFF_FILES` at **step 5**, the moment a dbt dimension feeds a published
figure.

The rest of this decision applies from step 5:

- `identity.calculation_files()` gains every file under `dbt/models/`, `dbt/macros/` and
  `dbt/dbt_project.yml`. A new test globs those directories and fails if a file is present
  but not covered — the SQL equivalent of the import-closure guard, which cannot see
  `.sql` files.
- `identity.RUNTIME_PACKAGES` gains `dbt-core` and `dbt-duckdb`. A different dbt is a
  different renderer of the same SQL and is recorded as such.
- `scenario_run` gains two columns: `dbt_manifest_sha256` (digest of `target/manifest.json`
  after the build — the exact rendered graph) and `dbt_versions`. The schema-migration
  rule in `ensure_schema` already drops and rebuilds derived tables when `scenario_run`'s
  shape changes, so this is a known, handled path (the 2026-09-08 incident notes apply:
  restart any Streamlit server started before the change).
- Baselines bump `FORMAT_VERSION` to `"2"` carrying the two new fields. Replay of a
  format-1 baseline is still accepted: figure fields are compared, and identity fields
  the old format lacks are reported as *absent*, not as mismatches.

### D7 — Tests: dbt tests for structure and identities, pytest for arithmetic

**BUILT at step 4: 49 dbt tests, 11 of them singular.** Schema tests cover
`schedule_label_naive` (unique, not_null), the band vocabularies, the price not-nulls, the
assumption id, both facts' key columns and every exclusion flag, plus a `relationships`
test tying every charged reading's label back to the schedule dimension. Singular tests
cover the fact key, the price key, `charged + excluded = distinct`, disjointness,
**membership** (every distinct reading in exactly one fact, and neither fact holding a key
the grain does not), row-by-row charge arithmetic, the reason vocabulary **and its
precedence**, at-least-one-flag, price validity being both-or-neither, unknown validity
pricing nothing, and the four required price values.

**`effective_from` / `effective_until` are deliberately given no not_null test.** The flat
rate's period is UNKNOWN; a NULL bound there means "not established", never "open-ended",
and a blanket rule would force an invented period into the data. What *is* asserted is the
consequence: a price with unknown validity charges nothing.

**Mutation-tested, because a passing suite proves nothing about the tests themselves.**
Two deliberate defects, each built against a **copy** of the project and a disposable
warehouse:

| Mutation | Tests that failed | Tests that still passed |
|---|---|---|
| One exclusion flag inverted in the exclusion projection only | reconciliation, disjointness, at-least-one-flag, reason not-null | the reason-precedence test |
| Two reasons swapped inside the exclusion fact only | **the reason-precedence test alone** | reconciliation and disjointness — `4 + 10 = 14` still closed exactly |

The second is the one that matters. Every count, every total and the accounting identity
were untouched; only recomputing the precedence from the stored flags found it. A
reconciliation test on its own would have reported success on wrong data.

**The original schema-test list, for reference:**

**dbt singular tests (`dbt/tests/`):**

| Test | Asserts |
|---|---|
| `assert_charged_plus_excluded_equals_distinct` | `count(int_distinct_readings) = count(fact) + count(exclusion)` for `var('run_id')` |
| `assert_charged_and_excluded_are_disjoint` | no (household, label) in both facts |
| `assert_exact_charge_arithmetic` | `energy_charge_gbp = CAST(consumption_kwh * price_gbp_per_kwh AS DECIMAL(38,16))` on every row — the DECIMAL product, never a double |
| `assert_one_reason_per_exclusion` | `exclusion_reason IN {{ exclusion_reasons() }}` and the reason's own flag is true |
| `assert_price_validity_both_or_neither` | `effective_from` and `effective_until` are both null or both set |

**pytest keeps (P10):** every hand-computable case in `tests/test_tariff.py`, the
identity closure guard, the schema-repair tests, REC-001. They call `build_scenario`
as today, which now runs dbt. Two new pytest guards: no `/ 100` (or any division) in
`dbt/models/**/*.sql`, and the DECIMAL column-type check from D3.

**Cost, stated:** 44 test builds today take seconds each in DuckDB. A dbt invocation
adds parse time per call. The ticket measures the suite before and after; if it exceeds
five minutes, the mitigation is dbt partial parsing with a shared `target/` per session,
**not** a Python-only fast path (which would be a second implementation).

### D8 — What Python keeps, and what it loses

| Stays in Python | Leaves Python |
|---|---|
| `policy.py` (the rules, now parameterised) | the SQL constants in `models.py` |
| `schedule.py`, `prices.py`, `identity.py` | `_load_dimensions` |
| `build_scenario` (skip rule, dbt invocation, publish transaction, run record) | the two `INSERT ... SELECT` statements |
| `analytics.py`, `baseline.py`, `compare.py`, `cli.py` unchanged in interface | — |
| `EXCLUSION_ORDER` (rendered into the macro; `analytics` still imports the reasons) | — |

## 2. Acceptance — the figures `dbt build` must reproduce

From `anl-002-tariff-scenario.md`, over `data/warehouse/energy.duckdb` (members 4, 5,
135), scope `ToU`, assumption A1. **None of these may change by any digit.**

| Figure | Value |
|---|---:|
| Distinct readings | 2,997,962 |
| Charged | 456,096 |
| Excluded | 2,541,866 (`ineligible_tariff_group` 1,998,647 · `outside_schedule_period` 543,219) |
| Charged kWh | 85,467.1329968 |
| Exact scenario charge | `11675.4339216532500000` |
| Charged rows at exactly zero | 133 |
| Rows collapsed by policy | 2,038 |
| `High` share of charged kWh / charge | 4.90% / 24.09% |
| `Low` share of charged kWh / charge | 10.48% / 3.06% |

**Baseline `4b3ee235d7ac`:** its six **figure** fields and the per-band, per-household
and per-reason detail must match on replay. Its `scenario_fingerprint` **will not**
match — the calculation digest changes by design when code moves — and the replay report
must show that as the *only* differing field, named. Then a new baseline is captured under
the ported identity and replayed 17/17 into a fresh database. A replay that has not been
executed is not evidence (the project learned this once already).

## 3. Risks, each with the check that retires it

| Risk | Check |
|---|---|
| dbt-duckdb Python models cannot return typed DECIMAL columns | Step 3 of the ticket builds the dims alone and reads `information_schema`; if the types are wrong, fall back to D3's rejected alternative (dims as sources) and record why |
| In-process `dbtRunner` and the warehouse connection contend for the DuckDB file | Python closes its connection before invoking dbt and reopens for the publish step; a test builds twice in one process |
| The generated macro renders SQL that dbt's Jinja alters (e.g. `{{` inside a string) | The policy SQL contains no braces today; the drift test also compiles the project (`dbt parse`) |
| Suite time | Measured before/after in the ticket, threshold five minutes |
| Streamlit server holding an old `models.py` | Same as the 2026-09-08 incident; the tab already diagnoses a schema mismatch |

## 4. Out of scope, on purpose

Staging models for households or a household dimension (roadmap M3, separate item);
Airflow (M5); any change to what is charged, excluded, rounded or assumed; snapshots or
incremental models (the facts are rebuilt whole by design, so a rerun is provable).
