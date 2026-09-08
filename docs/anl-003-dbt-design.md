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

### D5 — Publication: **immutable versioned database files and an atomically replaced manifest** (DECIDED and PROVED 2026-09-08; the **core and the candidate workflow are implemented**; the dashboard switch is not)

**Why the first draft below was wrong.** It built into a `scenario_build` schema inside
the live warehouse and published with one transaction. Measured (table further down):
DuckDB locks the *file*, so a build in that file makes the dashboard unable to open it at
all, and a dashboard holding it read-only blocks the build. Atomicity was solved; reader
availability was not. The draft is kept for the record; the decision replaces it.

**Options weighed.**

| Option | Availability during a build | Verdict |
|---|---|---|
| 1. Staging schema in the live file, coordinated reader downtime | none — readers cannot even open the file while it is written; every build is an outage, and a *failed* build leaves the file having been write-locked for nothing | rejected: fails "a failed candidate build leaves the last published result readable" |
| **2. Separate immutable version files + a manifest replaced by atomic rename** | full — the builder writes a *new* file; readers hold the *published* file read-only; promotion touches neither, only the manifest | **chosen**: meets every requirement with the filesystem alone |
| 3. A server (DuckDB server, Postgres, a hosted warehouse) | full | rejected: one user, one machine, a Streamlit dashboard; nothing in the requirements needs a process to stay up, and it would add an operational dependency the project has none of |

**What a publication is: a coherent warehouse snapshot, not the tariff tables alone.** The
Overview, Data quality and Source records tabs read `readings` and `load_registry`; the
tariff tab reads the facts and `scenario_run`. If the facts lived in a separate file, the
tabs could disagree about which members exist — after loading member 136 the Overview
would show four members while the published scenario was computed on three. A version
file is therefore the **whole database**: readings, registry, dimensions, facts and the
run record together, copied once from the mutable ingestion warehouse and never written
again. Alignment across tabs is then structural: they all read one file, and the run
record's input identity matches that file's `load_registry` by construction.

**Snapshot acquisition and the ingestion lock.** The builder copies
`data/warehouse/energy.duckdb` into a new version file with `ATTACH … (READ_ONLY)` +
`COPY FROM DATABASE`. A read-only attach coexists with other read-only holders and is
refused while ingestion holds the file read-write; the builder then **fails fast with a
named cause** ("ingestion in progress") and does not retry silently. Once the dashboard
reads published versions, ingestion is the only writer that can compete.

**States.** *candidate* — a new file exists and is being written; *validated* — `run-dbt`
returned 0 and wrote its build record into that file, which has been closed (no `.wal`);
*failed* — `run-dbt` returned non-zero, nothing was recorded, the file is kept for
diagnosis and can never be promoted; *published* — the manifest names it. **Every attempt
is a new file**, so "a previous success row must not certify tables changed by a later
failed attempt" is solved structurally: a later attempt never touches an earlier file, and
I-16's stale-certificate problem does not arise.

**Version selection in a Streamlit rerun.** The app resolves the manifest **once** at the
top of the script and threads the resolved *path* through every query, exactly as it
threads `database` today. Every connection a render opens is to that one file; the
manifest is never consulted mid-render, so a promotion during a render is invisible to it
and the next rerun sees the new version whole, metadata included.

**Promotion.** Under an `O_EXCL` lock file: compare-and-swap on the manifest's current
version (a request formed against an older state is refused as *stale*), gate the
candidate (no `.wal`, a `validated` record, the run_id the caller validated, digest
recorded), write `published.json.tmp`, `fsync`, **`rename`** over `published.json`,
`fsync` the directory. The rename is the **atomic visibility** boundary; the fsyncs are
**power-loss durability** — different properties, both needed, neither implied by the other.

**Reader behaviour.** *Before:* reads the published file. *During a build:* unaffected —
a different file. *During promotion:* unaffected — a rename of a 300-byte JSON file. *After:*
the next rerun resolves the new version. With no manifest, `resolve` raises an explicit
*unavailable* error; it never returns an empty dataset.

**Interruption and recovery.** Killed mid-build: a partial candidate, possibly with a
`.wal`; the manifest is untouched and the gate refuses the file. Killed after the tmp is
written but before the rename: the old version is still published, the tmp and the lock
are left; `recover` removes both and **never edits the manifest** — either the rename
happened or it did not, there is no third state.

**Retention.** Keep the newest N versions; never delete the published or the immediately
previous one; never delete anything younger than a grace window. The grace exists because
a render opens a fresh connection per query to the path it resolved at its start: on
POSIX an open connection survives `unlink`, but the *next* query's open would not.

**Rollback.** Pointing the manifest at a retained version — seconds, no rebuild. For a
version no longer retained, reconstruction by baseline replay.

**Identity, at implementation.** `tariff/dimensions.py` and every file under `dbt/models`,
`dbt/macros` and `dbt/dbt_project.yml` join `calculation_files()`; `dbt-core` and
`dbt-duckdb` join `RUNTIME_PACKAGES`. Baselines move to **format 2**, adding the dbt
versions, the manifest version and the version file's digest. **Format-1 baselines are
never rewritten**: `replay` accepts them, compares every figure field, and reports the
fields format 1 lacks as *absent*, not as mismatches.

**Proof (`tests/test_publication_proof.py`, separate reader and builder processes, ext4).**

| Scenario | Established |
|---|---|
| Reader while a candidate builds | reader read v1 while the builder held a write lock on the v2 file; both succeeded; the closed candidate had no `.wal` |
| Failure midway | builder died mid-write; manifest byte-identical; v1 readable; candidate left with a `.wal`; promotion of it **refused** |
| Promotion gate | a `failed` record refused; a validated file with a different run_id refused; the accepted file's digest recorded |
| Real `run-dbt` on a snapshot | 48 charged rows from the demo schedule; the wrapper works against a version file; promoted |
| Reader spanning a promotion | first and second read identical (file, rows, run_id, manifest version) though v2 was promoted between them; the next resolve saw v2 |
| Interruption at the boundary | promoter died after fsync, before rename; manifest unchanged; tmp + lock left; a second promoter refused by the lock; `recover` removed both and did not touch the manifest; promotion then succeeded |
| Competing promoters | two processes released together: exactly one won, the other refused as stale |
| Stale request | formed against v1, submitted after v2: refused; v2 stayed |
| Rollback | manifest change under five seconds; reader saw v1's data |
| Retention | protected versions and the grace window respected; an open connection survived the unlink; a new open failed |

**Implemented (step 5(b)).** `uv run build-candidate` owns the candidate lifecycle:
validate, snapshot, clear inherited build history, build once into a fresh file, require
passing models *and* tests, seal. It never promotes and never reuses a file. Two measured
defects were closed by it — a snapshot inheriting the source's build record, and a stale
record outliving the tables it described — the second by adding `built_output_sha256` to
the build record and recomputing it at `finalise`. Real-data check: a candidate built from
the three-member warehouse matched the Python path exactly (456,096 charged rows with 0
differing over every column, 2,541,866 excluded with 0 differing, total
`£11675.4339216532500000`, per-band and per-household identical).

**Implemented (attempt lifecycle, canonical digest, candidate identity — 2026-09-08).** The
review after 5(b) found three gaps and this closed them; each was reproduced before it
was changed.

- *Attempt lifecycle.* `run-dbt` writes a **`started`** row to `scenario_build.dbt_build_run`
  **before** dbt is invoked (the recording connection is closed first, because DuckDB locks
  the file) and completes it as **`succeeded`** or **`failed`** afterwards. A row left
  `started` means the orchestrator died or is still running. **Contract:** `finalise` seals
  only when the **latest** attempt (by start time) is `succeeded`, ran `build`, was recorded
  **in this file** (`database_path`), is the **only** attempt (a retry is a new file), and
  the tables still digest as it recorded. A failed or unfinished attempt after a success
  is refused **even when the tables are unchanged** — attempt success and output equality
  are separate checks and neither is inferred from the other. A refusal before an attempt
  begins (unusable path, sealed read-only file, legacy record shape) records nothing.
  **Boundary:** attempts are recorded by `run-dbt` and `build-candidate` only; a direct
  `dbt` run or a hand edit is not an attempt and is caught by content (the output digest
  at sealing, the whole-file SHA-256 after it), not by history. Legacy record shapes and
  legacy seals are **refused with a rebuild message**, never migrated or reinterpreted.
- *Canonical digest* (`canonical-rows-1`, recorded as `output_digest_version`). The former
  `COUNT + bit_xor(hash(row))` summary was measured to collide: `{1,1,2}` and `{2,3,3}`
  summarised identically. The digest now covers, per base table in `scenario_build`
  (record excluded, views excluded): relation name, ordered column names **and types**, row
  count, and the **sorted stream of per-row SHA-256** over a self-delimiting text encoding
  — `N` for NULL, else `V<length>:<DuckDB VARCHAR cast>` so a `DECIMAL(9,4)` stays
  `0.6720`, never `0.672`. Independent of physical order; moves for any value, duplicate
  multiplicity, type, name or relation change. Rows are streamed in chunks (bounded on the
  Python side; the sort is DuckDB's). Measured on the three-member candidate: 2.4 s for
  ~3.0 M rows; full sealing validation 2.2 s; whole-file SHA-256 (210 MB) 0.13 s. **Two
  digests, two claims:** the attempt's `built_output_sha256` says the built tables are the
  ones dbt left; the seal's `sha256` says the whole file is the one validated. Neither is a
  proof of equality — migration evidence stays row-by-row (`EXCEPT ALL` both ways).
- *Candidate identity* (`tariff/candidate_identity.py`, a **sibling** of `identity.py`).
  Every attempt records `calculation_code_sha256` over the published calculation files
  **plus** `tariff/dimensions.py` and the dbt project (`dbt_project.yml`, `models/**`,
  `macros/*`; not `target/`, `logs/`, `.user.yml`, `profiles.yml`, `tests/`), the per-file
  digests (`covered_files`), `runtime_detail` naming Python, DuckDB, PyArrow, pandas,
  openpyxl, dbt-core and dbt-duckdb, the resolved dbt variables, and the schedule source,
  file digest, row count and price catalogue version **read from the dimension rows dbt
  wrote**. Coverage is guarded: the import closure of the dbt Python models in a fresh
  interpreter, and an independent walk of `dbt/` against the globs. **The published
  identity is deliberately untouched** — `identity.py` is itself a covered file, so editing
  it would have moved the published fingerprint for a change that cannot alter a published
  figure, and the dashboard reads no candidate yet. Verified: `calculation_digest()` is
  byte-identical before and after (`262491c4…`), and the format-1 replay of baseline
  `4b3ee235d7ac` gives the same 16/17 result as before this slice.

**Still not done**: the dashboard reads no candidate (the read contract is the next slice),
the published identity switch that comes with it, baseline format 2, retention (I-17).

**Implemented (step 5(a)).** `src/energy_reconciliation/publication.py` carries the proof's
primitives over with three additions: **`finalise`** seals a built candidate (exactly one
`run-dbt` record, no `.wal`, SHA-256 written to a `.validated.json` sidecar, file mode
dropped to read-only), so *writable during construction, immutable after* is enforced by
the filesystem and re-checked by digest at promotion; the lock records **pid and process
start time**, so recovery cannot mistake a reused pid for the live owner; and there is
**no sweep** — `inventory` is the dry run and deleting waits for a confirmed command
(I-17). The proof scenarios run against the module (`tests/test_publication.py`, 19
tests, real child processes). Measured in the walkthrough: a candidate whose dbt build
failed on a duplicated schedule label closed cleanly and left **no `.wal`**; the absent
build record and absent seal are what refuse it. The sidecar check is a second gate.

**What the proof does not establish.** Power-loss durability (fsyncs were called, not
tested by pulling power); behaviour on NTFS/drvfs or a network share (ext4 only); the
production publisher itself (the primitives are proof code); the dashboard reading a
manifest (not switched); retention against a real long-running render.

**The earlier draft, for the record:**

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
schema does not solve the second** (this measurement is what forced the decision above). DuckDB locks the **file**, not the schema. Measured
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

### D9 — The supported read contract: an explicit, validated context, never a bare relation name (DECIDED and IMPLEMENTED 2026-09-08)

**The defect this closes was found by review, not by a failure.** A sealed candidate is a
whole-warehouse snapshot, so it holds **two** tariff scenarios: the Python one copied from
the source in `main`, and dbt's in `scenario_build`. Every query in `analytics.py` named
its relations bare (`FROM fact_interval_charge_scenario`), and DuckDB resolves a bare name
in `main`. Pointing a reader at a candidate would therefore have shown the **copied Python
figures** under the candidate's name, with `main.scenario_run`'s identity beside them.
Nothing would have raised.

**Decision.** Relations are routed explicitly, per query, through an immutable context.

| Option | Verdict |
|---|---|
| Session `SET search_path = scenario_build, main` | **rejected**: process-wide state deciding, at some later statement, which of two schemas a bare name meant — and the two hold different runs by different builders. A reader that forgets to set it reads `main` silently. |
| Copy dbt's tables over `main.*` in the candidate | rejected: destroys the evidence of what each builder produced, and makes the seal's digest describe tables nobody can compare. |
| **Fully qualified names from a validated `Relations` value, threaded through every call** | **chosen**: the schema is in the SQL text, the value is built from two fixed vocabularies (`main`/`scenario_build`, seven known tables) so no caller-supplied identifier is ever interpolated, and the dbt route has **no** `scenario_run` at all, so a function needing one raises instead of falling back. |

**The surface** (`tariff/reads.py`): `published(root)` resolves the manifest **once** and
returns a `ReadContext`; `candidate(path)` does the same for a sealed file being inspected;
`warehouse(database)` is the unchanged legacy route. A context binds the database path, the
relations, the run id, and a `BuildIdentity` from the build record and the seal. Validation
happens once, at that boundary: manifest ↔ seal ↔ build record ↔ file bytes ↔ built-table
digest must all agree, and any disagreement names the two pieces of evidence that differ.
`tariff_report(context, …)` is one complete analytical operation over one context.

**Identity is mapped, never renamed.** A dbt build has no `scenario_fingerprint` and no
`ingestion_pipeline_fingerprint`, so `BuildIdentity` has neither, and `dbt_project_sha256`
is never presented as either. What genuinely agrees keeps its name: tariff group, schedule
source and digest, price catalogue version, policy digest, runtime versions. The
reconciliation ladder is **read** from `scenario_run` on the Python route and **counted**
on the dbt route (`Accounting.derived` is True), because dbt records no such row.

**Active versus inspected.** `role` is `published` only for the file the manifest named when
the context resolved; a sealed candidate is `candidate`, `is_active_publication` is False and
the label says *NOT published*. A context already held stays bound to its version across a
promotion — tested — which is what makes "resolve once per rerun" safe.

**Producer eligibility, and why the reader could not be exposed without it.** Before this
slice, `finalise` accepted any attempt whose recorded command began with `build`. Measured:
`run-dbt … build --exclude test_type:singular` builds every model, **skips all eleven
singular tests** (reconciliation, exact arithmetic, reason precedence), exits 0, was
recorded as `succeeded` and **was sealed**. Exit code 0 and the word `build` are not
evidence that the project was built. So every attempt now records its coverage from dbt's
own artefacts for that invocation — the required node set from `manifest.json` (enabled,
non-ephemeral models plus every test), each executed node's status from `run_results.json`,
their digest, dbt's `invocation_id`, and any required node that did not pass — and
`required_build` is `complete` only when none is missing. Stale artefacts cannot satisfy
it: the two files must share an invocation id, and it must post-date the attempt's start.
`finalise` and `reads` both refuse anything else. The required set is the project's own, so
adding a model or a test raises the bar without touching this code.

### D6 — Run identity extends to the dbt files; nothing is dropped

**Candidate identity complete (2026-09-08); published identity deliberately unchanged.**
The dimensions and facts are real outputs, so which dbt produced them, from which code and
runtime, is part of what they are. Every `run-dbt` attempt records it in
`scenario_build.dbt_build_run` (see D5): dbt-core and dbt-duckdb versions, Python, DuckDB,
PyArrow, pandas and openpyxl versions, a digest and per-file digests over the published
calculation files **plus** `tariff/dimensions.py` and the dbt project, the policy digest,
the resolved dbt variables, and the schedule/catalogue identity of what was built. This
lives in `tariff/candidate_identity.py`, a sibling of `identity.py` that reuses its helpers,
so that `identity.calculation_files()` and `RUNTIME_PACKAGES` — and with them every
`scenario_run` fingerprint and format-1 baseline — are untouched. It is **separate from
`scenario_run`** and creates nothing in `main`: the published scenario is still built by
`build-tariff-scenario` from its own dimensions and consumes none of it.

The rest of this decision applies when the dashboard reads published candidates (the read
contract slice), at which point the candidate identity becomes the published one:

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
