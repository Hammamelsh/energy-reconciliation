# ANL-003 — Port the tariff models to dbt

| Field | Value |
|---|---|
| Ticket | ANL-003 (roadmap M3; idea I-06) |
| Status | **Steps 0–4 implemented; step 5(a) publication core, 5(b) candidate workflow, 5(b′) attempt lifecycle + canonical digest + candidate identity, 5(c-i) the supported read contract 5(c-ii) the dashboard integration and 5(d) baseline format 2 with genuine replay implemented 2026-09-08/09; step 6 partly done (ANL-002 outputs reproduced by dbt at row level, format-2 replay reproduces exactly); 5(e) and step 7 not started.** `uv run build-candidate` snapshots a warehouse, builds it with dbt and seals it on success; `publication` resolves, finalises, promotes, rolls back, recovers and inventories. **Not yet wired in**: the dashboard still reads `data/warehouse/*.duckdb` directly, the published scenario is still built by `build-tariff-scenario`, and **published-run identity integration is not done** (step 5(d)). |
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
| 3 | **DONE.** Both dimensions are dbt Python models over `tariff/dimensions.py`, which returns typed `pyarrow` tables; `--schedule demo\|workbook` selects the source and an unknown variant raises rather than falling back to the invented one. New supported entry point `uv run run-dbt` validates the database path **before** anything can create it. | **Persisted** (`information_schema`, not the Arrow schema): `DECIMAL(9,4)` / `DECIMAL(9,6)`, `DATE` bounds NULL for the flat rate. All four prices equal hand-written publisher figures and `gbp * 100 = pence` exactly in the database. Workbook build: 17,520 rows, `schedule_source = 'Tariffs.xlsx'`; demo build: 48 rows, `'synthetic-demo'` on every row. Both dimensions **row-for-row identical to the Python path** (0 differing rows). Duplicate-label workbook: `ScheduleError` reaches the build; on a fresh target the schedule dimension is **absent**, and where one existed its rows and schema are byte-identical with no `__dbt_tmp` left. 18 tests in `tests/test_dbt_dimensions.py`. | Not triggered — the DECIMAL types were produced as designed, so the fallback was not used. |
| 4 | **DONE.** `models.py` parameterised the same way `policy.py` was, so `classified_readings`, `scenario_fact`, `exclusion_fact`, `exclusion_reason_case` and `exclusion_reasons` are **generated** from it — no rule is written twice. `int_classified_readings` (ephemeral) plus both facts as tables; 49 dbt tests, 11 singular, including the dimension keys CTAS drops. | Every published SQL constant **byte-identical to HEAD** (`CLASSIFIED_READINGS`, `FACT_SELECT`, `EXCLUSION_SELECT`, `SCHEMA`), so no figure could move; the Python rebuild reproduced ANL-002 and the charged-row digest `5d8fa82b…` exactly. `dbt build` → `PASS=55` on the three-member copy and on the demo. Against the Python path: **0 differing charged rows** of 456,096 over every column, exact total `11675.4339216532500000`, **0 differing exclusion rows** of 2,541,866, identical per-band and per-household aggregates. Hand-derived fixture covers all seven reasons plus duplicates, equivalents, two conflict kinds and a charged zero. **Mutations:** inverting one exclusion flag failed reconciliation + disjointness; swapping two reasons failed **only** the precedence test while `4 + 10 = 14` still closed. | — |
| 5 | **(a) CORE, (b) CANDIDATE WORKFLOW, (b′) ATTEMPT LIFECYCLE, (c-i) READ CONTRACT and (c-ii) DASHBOARD INTEGRATION IMPLEMENTED 2026-09-08/09; (d) BASELINE FORMAT 2 IMPLEMENTED 2026-09-09; (e) not started.** (d): `capture-published-baseline` records a **published dbt build** through the validated read contract — never the copied `main.scenario_run` — as format 2 (`data/baselines/pub2-*.json`): input members with content digests, schedule/catalogue/group scope, the candidate calculation and runtime identity, and the exact outputs (schemas, row counts, a `compare-rows-1` digest over every row occurrence, the accounting ladder, exact decimals, per band/household/reason). `replay-published-baseline` verifies every artifact **before** creating anything, re-ingests the recorded members from the archive and runs the supported `build-candidate` path — a real dbt build, complete required coverage — into a destination that must not exist, then compares. Exit 0 reproduced, 1 differed, 2 cannot reproduce. Only `run_id` (both facts) and `loaded_at_utc` (schedule dim) are excluded from row comparison, each justified. Format 1 untouched; the two formats refuse each other by version and by file name. (c-ii): the sidebar offers **Warehouse file** (unchanged) or **Published version**; the publication is resolved **once per rerun** through `reads.published()` and the immutable context is threaded through every tab, so tariff figures and identity come from the sealed dbt build and never from the Python `scenario_run` copied into the same file. An unresolvable publication is an explicit **unavailable** state that renders no tab and never falls back. `explorer/selection.py` owns the mode and adapts the identity per route. `ENERGY_RECONCILIATION_PUBLICATION_ROOT` points the app at a disposable root. Validated contexts are cached per process, keyed by the version file **and the digest the manifest records for it** — measured: a published rerun fell from 5.37 s to 1.01 s; a warehouse file is never cached. Evidence: `tests/test_explorer_publication.py` (13, Streamlit `AppTest`, headless), fixture doctored so any read of `main` is visible. (c-i): `tariff/reads.py` — `published(root)` / `candidate(path)` / `warehouse(database)` return an immutable `ReadContext` binding the file, fully qualified relations and a `BuildIdentity` from the build record and seal; `analytics` routes every query through `Relations` (design D9) and has **no** `scenario_run` on the dbt route, so a function needing one raises instead of reading `main`. Producer eligibility closed first: measured that `build --exclude test_type:singular` exits 0, skips all 11 singular tests and **was sealed**; attempts now record dbt's own node coverage and `finalise` refuses `required_build != complete`. Evidence: `tests/test_reads.py` (17), including a fixture whose copied Python scenario is deliberately doctored so any fallback to `main` is visible in every routed function. Real data: through the read route, 456,096 charged, 2,541,866 excluded, exact total `11675.4339216532500000`, per-band/per-household/per-reason identical to the reference; context validation 2.2 s once, full report 0.17 s.** (b′): `run-dbt` records a `started` attempt **before** dbt runs and completes it as `succeeded`/`failed`; `finalise` requires the **latest** attempt to be a succeeded `build`, recorded in this file, the only attempt, with the tables digesting as recorded under `canonical-rows-1` (sorted per-row SHA-256 over a typed, self-delimiting encoding — replaces the `bit_xor` summary that was measured to collide). Every attempt records the candidate identity: dbt/DuckDB/PyArrow/pandas versions, digests over the calculation files **plus** `dimensions.py` and the dbt project, resolved vars, and the schedule/catalogue identity read from the built dimensions. Published identity (`identity.py`) untouched on purpose. Evidence: `tests/test_candidate.py` (22, incl. a **real child-process interruption**: the orchestrator is SIGKILLed while dbt runs, dbt finishes cleanly, the attempt stays `started`, sealing refused), `tests/test_output_digest.py` (16), candidate-identity coverage guards in `tests/test_tariff_identity.py`. Real data: 0 differing rows in 456,096 charged and 2,541,866 excluded (`EXCEPT ALL` both ways), exact total `11675.4339216532500000`, per-band/per-household/per-reason identical; sealing validation 2.2 s. Format-1 replay of `4b3ee235d7ac`: same 16/17 as before (fingerprint differs since step 1; every figure and the charged-row digest reproduce). `uv run build-candidate --source <warehouse> [--schedule workbook\|demo]` validates source and destination, snapshots (source `READ_ONLY`, an ingestion lock reported as such), **clears the inherited build schema**, runs the guarded dbt build once into a **fresh file**, requires passing models **and** tests from dbt's own run results, then seals. A failed stage exits 1 naming the stage and the candidate, leaves it unsealed, and never retries in place; it never promotes. `src/energy_reconciliation/publication.py` provides the rest: Publication = **immutable versioned whole-warehouse files** under `data/published/versions/` and a `published.json` manifest replaced by atomic rename under an `O_EXCL` lock with compare-and-swap. `finalise` seals a built candidate (exactly one `run-dbt` record, no `.wal`, SHA-256 in a `.validated.json` sidecar, file mode 0444); `publish` re-hashes the file against the seal and refuses if the bytes moved; `rollback` is `publish` at a retained file; `recover` removes only an orphan tmp manifest and a lock whose pid **and start time** are dead; `inventory` is a read-only dry run and **nothing deletes**. CLI: `uv run publication status\|inventory\|finalise\|promote\|rollback\|recover`. | `tests/test_publication.py`: 19 scenarios, real child processes — reader during build, builder dying mid-write (published intact, candidate refused), gate on exact bytes (a post-seal edit is refused), file outside `versions/` refused, real `run-dbt` on a snapshot sealed and promoted, reader spanning a promotion sees one version, promoter dying between fsync and rename then recovered without editing the manifest, recovery **refusing** a live lock, competing promoters (exactly one wins), stale request refused, rollback < 5 s keeping all files, inventory deletes nothing, CLI. **Not established:** power-loss durability, non-ext4 filesystems, the dashboard switch. | Next: (b) `build-candidate` (snapshot + `run-dbt` + `finalise`, fail fast if ingestion holds the lock); (c) the dashboard resolves the manifest **once per rerun** with an explicit *unavailable* state; (d) `dimensions.py` + dbt files into `calculation_files()`, dbt into `RUNTIME_PACKAGES`, baseline format 2 with format-1 read-only; (e) step 6. Deleting old versions waits for I-17. |
| 6 | **PARTLY DONE 2026-09-09.** ANL-002's figures are reproduced by the dbt build at **row level**: `baseline.fact_row_digest` gained a `relation` argument so the *same* measure can be taken over either implementation, and the digest over the dbt fact equals the format-1 baseline's recorded `5d8fa82b201969c5…`, with distinct/included/excluded, raw rows, collapsed rows, the exact total and per-band/household/reason all equal. **Implementation identity is NOT equal and is not claimed to be**: a dbt build records no `scenario_fingerprint`, and its `calculation_code_sha256` covers `dimensions.py` and the dbt project. A format-2 baseline captured from the real publication replayed **44/44 fields, 0 differ**. Still to do: replaying format-1 `4b3ee235d7ac` itself under the Python path (its fingerprint difference stands and is not weakened). | Every figure in design §2 matches to the digit; the old baseline's replay report shows `scenario_fingerprint` as the **only** differing field; the new baseline replays 17/17 including `fact_row_sha256` | Any changed digit is a defect in the port, not a new result — stop and diagnose |
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

# working today (steps 0-4)
uv run render-dbt-macros            # regenerate dbt/macros/generated_policy.sql from policy.py
uv run render-dbt-macros --check    # verify it, never rewrite it

# Never point a build at data/warehouse/energy.duckdb: dbt takes a write lock on the file
# and creates its own schema in it. Work on an isolated copy, made the supported way
# (source opened READ_ONLY, so the original cannot be written):
#   ATTACH 'data/warehouse/energy.duckdb' AS src (READ_ONLY);
#   ATTACH '/tmp/dev-energy.duckdb' AS dev;
#   COPY FROM DATABASE src TO dev;

# THE SUPPORTED ENTRY POINT. Validates the database path before anything can create it,
# and records the build's dbt versions in scenario_build.dbt_build_run.
uv run run-dbt --database /tmp/dev-energy.duckdb                      # publisher workbook
uv run run-dbt --database /tmp/dev-energy.duckdb --schedule demo      # INVENTED schedule
uv run run-dbt --database /tmp/dev-energy.duckdb --tariff-group ToU   # scope (default ToU)
# Builds 5 models and runs 49 dbt tests. A failed build returns non-zero and records
# nothing; it can still leave independently successful models rebuilt, so a success row
# in scenario_build.dbt_build_run does not certify the tables after a later partial run.

# Calling dbt directly still works and is NOT guarded: a wrong path is created as an empty
# database before the on-run-start hook rejects it. Use it for read-only inspection.
export ENERGY_RECONCILIATION_DB=/tmp/dev-energy.duckdb
uv run dbt show --project-dir dbt --profiles-dir dbt --output json \
  --inline "select count(*) from {{ ref('int_distinct_readings') }}"   # -> 2997962

# proposed, NOT yet available (steps 3-5 add the vars and the models they configure):
# uv run dbt build --project-dir dbt --profiles-dir dbt --vars '{run_id: dev, tariff_group: ToU, schedule: demo}'
```

### Stale build records: what was measured, and what closes it

Both risks in the handover were real, and were reproduced before anything was changed.

| Risk | Measured behaviour before | What closes it |
|---|---|---|
| A snapshot **inherits** the source's build history | `COPY FROM DATABASE` copies `scenario_build` whole, record included. `finalise` **accepted** a bare snapshot that had never been built as a candidate. | `build-candidate` drops `scenario_build` from every new candidate, so it starts with no build history. A file that somehow carries two records is refused by the one-record rule. |
| A **stale record outlives the tables it described** | Build, then a failed rebuild in the same file: the failed attempt records nothing, the old record stands. `finalise` **accepted** it. | Two guards. The build record now carries `built_output_sha256`, a digest of the built base tables, and `finalise` recomputes it — a record that no longer describes the file is refused. And the supported command never reuses a file, so a rebuild is refused **before** any mutation; a sealed candidate is read-only, so even a direct `run-dbt` at it cannot open it for writing. |

| A **failed rebuild leaves the tables identical** (fails on the first model; dbt rebuilds the independent models to the same contents and skips the rest) | Nothing moved, so the digest could not object, and `finalise` **sealed** the file on the strength of the earlier success — measured, regression-tested as the honest limit of a content check. | The **attempt lifecycle** (2026-09-08). Every `run-dbt` invocation is recorded as `started` before dbt runs and completed as `succeeded` or `failed`; `finalise` requires the **latest** attempt to have succeeded. Output equality and attempt success are now two separate checks; neither is inferred from the other. |
| The **XOR summary cancels** | `COUNT + bit_xor(hash(row))` gave the same result for `{1,1,2}` and `{2,3,3}`. | `canonical-rows-1`: relation name, ordered column names and types, row count, and the sorted stream of per-row SHA-256 over a self-delimiting typed encoding (`N` / `V<len>:<text>`; decimals keep their scale). Duplicate multiplicity, values, schema and the relation set all move it; physical order does not. |
| An **interrupted attempt** | Nothing recorded, so indistinguishable from "never built". | The `started` row stays; `finalise` refuses it as unfinished. Proved with a real SIGKILL of the orchestrator while dbt ran: dbt finished, closed cleanly, and the file was still refused. |

| An **incomplete invocation succeeds and is sealed** | `run-dbt … build --exclude test_type:singular` builds every model, skips all 11 singular tests — reconciliation, exact arithmetic, reason precedence — exits 0, was recorded `succeeded` and **`finalise` sealed it**. Exit code 0 and the word `build` are not evidence that the project was built. | Every attempt records its node coverage from **dbt's own artefacts for that invocation**: the required set from `manifest.json` (enabled, non-ephemeral models + every test), each node's status from `run_results.json`, their digest, `invocation_id`, and any required node that did not pass. `required_build` is `complete` only when none is missing; `finalise` and `reads` refuse anything else. Stale artefacts are refused: both files must share an invocation id that post-dates the attempt's start. |

**Enforcement boundary, stated.** `run-dbt` and `build-candidate` record attempts. A direct
`dbt` invocation or a hand edit of the database is **not** an attempt and leaves no row;
what catches it is content — the output digest at sealing, the seal's whole-file SHA-256
after it. A record whose shape predates the lifecycle, or a seal that predates the current
fields, is **refused with a rebuild message**; nothing upgrades an older claim.

## OPEN RELEASE BLOCKER — `dbt build` segfaults intermittently (third investigation 2026-09-09, unresolved)

**Status: unresolved, not mitigated, blocker open.** GDB is now installed and a validated
debugger harness exists, but **no crash has occurred under it**. Nothing was changed for
the fault: no code, no dependency, no execution setting, no lockfile edit, no retry.

### Corrections to earlier wording in this record

| Earlier statement | Correction |
|---|---|
| "no completion line ⇒ SIGSEGV" | Each of the three is now corroborated individually (table below). A future incomplete invocation without corroboration is **incomplete/unknown**, not a crash. |
| "faulting inside the eval loop ⇒ the GIL was held, so not extension misuse" | The resolution only says **where the fault surfaced**. An extension can corrupt memory earlier, with or without the GIL, and the damage surfaces later in the interpreter loop. It excludes nothing. |
| "empty faulthandler output is explained by shared stderr" | That is a hypothesis. It is consistent with the transcript but not demonstrated. The GDB harness writes faulthandler to a private file so the question does not arise again. |
| "forty attempts had a one-in-three chance" | Withdrawn. That assumes a stable, independent per-attempt probability; the three observations are **clustered in 23 minutes** with 206 clean harness attempts since, which is not that. |
| "a native backtrace is the only next diagnostic" | Withdrawn as an absolute. Two other diagnostics were run this session (semaphore origin; fork probe) and resolved a question a backtrace would not have. |
| "294 invocations = 261 + 32 + 2" | Superseded by the uuid-based count below. |

### Accounting, corroborated per crash

Chronological parse of dbt's rotated logs, split on the `===== <time> | <uuid> =====` banner:
**303 invocations = 276 `succeeded at` + 24 `failed at` (deliberate test failures) + 3
without a completion line.** Exact. By origin: pytest 229 (1 crash), harness 67 (1),
ordinary use 7 (1). Seven ordinary-use invocations is far too few to quote a rate from.

| Crash (local time) | Origin | Corroboration | Phase reached |
|---|---|---|---|
| 11:14:40 | pytest | kernel: `dbt[218376]: segfault at 8 ip 0x1816c2b … error 4` | *Began compiling node* test 53/54 |
| 11:17:14 | build-candidate | kernel: `dbt[240559]: segfault at 100000007 ip 0x1815bfb … error 4` **and** retained attempt record `('failed', -11, 'incomplete')` | *Began compiling node* test 7/54 |
| 11:37:11 | harness (att-7) | harness rc 245 **and** attempt record `('failed', -11, 'incomplete')`; **no kernel entry**, which is expected: it ran with `PYTHONFAULTHANDLER=1`, and the kernel logs a page-fault SIGSEGV only when the handler is `SIG_DFL` | *Starting full parse*, before any node |

### Where the two recorded faults surfaced

Interpreter: `…/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12`, sha256 `f7c6210eb40fadcd…`,
Build ID `1b4adbcfef173a5a342e67de1b23f751d763439a`, `Type: EXEC` (not PIE, so the kernel's
`ip` values are absolute). `addr2line -f` resolves **both** `0x1816c2b` and `0x1815bfb` to
`_PyEval_EvalFrameDefault` (symbol at `0x1811500`, size 65,765; offsets +22,315 and
+18,171). Faulted addresses `0x8` (offset of `ob_type` from a NULL `PyObject*`) and
`0x100000007` (`0xFFFFFFFF + 8`). **Established:** the fault surfaced in the bytecode loop
dereferencing a NULL or garbage object pointer. **Not established:** what wrote it.

### Debugger harness — `tools/dbt-segv-gdb.sh` — and its validation

Runs the actual child under `gdb -batch`: `.venv/bin/python3 -c <wrapper>` calling
`dbt.cli.main:cli` with the same argv, cwd and env as `run-dbt`; stops at `SIGSEGV`/`SIGBUS`/
`SIGABRT` before the process's own handler; dumps `info program`, inferior identity,
registers, `x/12i $pc-24`, `bt full 20`, `thread apply all bt 30`, `info sharedlibrary`;
then `continue`s once so faulthandler writes Python frames to its private file; kills the
inferior on the second stop. ASLR is re-enabled (`set disable-randomization off`) to match
ordinary runs. No `python-gdb.py` helpers ship with this interpreter, so `py-bt` is
unavailable; Python frames come from faulthandler's file.

**Classification is from GDB's transcript, never its exit code** — the self-test shows why:

| Tiny process | gdb's own rc | classified |
|---|---|---|
| `sys.exit(0)` | **1** | completed |
| `sys.exit(3)` | 1 | failed:3 |
| `os.kill(getpid(), SIGSEGV)` | **0** | signalled:SIGSEGV |
| `ctypes.string_at(0)` (real null deref) | 0 | signalled:SIGSEGV |

GDB's rc is the *opposite* of the child's result. A missing or ambiguous transcript is
`unknown`. The harness records nothing in any `dbt_build_run` table and sits outside the
`run-dbt` / `build-candidate` attestation path.

**Stated fidelity differences from `uv run run-dbt`:** the harness calls the venv
interpreter directly; `uv run` would additionally prepend `.venv/bin` to `PATH` and set
`VIRTUAL_ENV`, `UV`, `UV_RUN_RECURSION_DEPTH` (same interpreter). GDB intercepts signals
and alters timing. `PYTHONMALLOC=debug` was **not** enabled in the baseline arms.

### Experiments this session (all on the demo warehouse, fresh target per attempt)

| Arm | Attempts | completed | failed | signalled | timeout | unknown |
|---|---|---|---|---|---|---|
| GDB, baseline settings, sequential | 20 | 20 | 0 | 0 | 0 | 0 |
| GDB, **two loops concurrently** (one factor changed) | 20 + 20 | 40 | 0 | 0 | 0 | 0 |

Cumulative harness attempts since the cluster: 59 plain + 40 traced + 60 GDB = **159, no
crash**; 206 including the run that produced att-7. **This is not evidence of a fix**, and
because the observations are clustered no per-attempt probability is claimed.

### Two questions resolved this session

- **The "2 leaked semaphore objects" warning is fully explained and is not a lead.** A
  probe patching `multiprocessing.synchronize.SemLock.__init__` and `os.fork` shows both
  locks are created in the **main thread by dbt itself on every run**: a
  `multiprocessing.RLock` at `dbt/adapters/base/connections.py:78` (via
  `dbt/adapters/duckdb/connections.py:33`) and a `multiprocessing.Lock` at
  `dbt/parser/manifest.py:286`. **`os.fork()` is never called.** They leak only because a
  signal death skips cleanup.
- **protobuf#22067 is not a match:** Python 3.13 only ("not reproducible on 3.12"), at
  exit-time GC, in `PyUpb_ModuleState_MaybeGet`. Ours is 3.12.14, mid-run, in the eval loop.

### Extension inventory (candidates only — none implicated by evidence)

Loaded by `import dbt.cli.main` alone: `dbt-extractor 0.6.0` (abi3), `protobuf 6.33.6`
(abi3, `_upb`), `msgpack 1.2.2`, `MarkupSafe 3.0.3`, `pydantic-core 2.46.5`,
`rpds-py 2026.6.3`, `PyYAML 6.0.3`, `charset-normalizer 3.5.1`; later `duckdb 1.5.5`,
`pyarrow 25.0.1`. All are cp312 or abi3 wheels for this interpreter. Two crashes were in
Jinja node compilation and one in the static parse; that is where they *surfaced*.

### Precise next step

The validated harness is ready but the fault is not reproducing on demand. The
evidence-driven next action is to **capture the next natural occurrence** rather than
run further unchanged loops: run every real candidate build under
`tools/dbt-segv-gdb.sh`-style tracing until one crashes, then read `bt full` for the
frame that owns the NULL/garbage object. Concretely, when the next `build-candidate` is
needed, run instead:

```bash
LABEL=real ATTEMPTS=1 SOURCE=data/warehouse/energy.duckdb bash tools/dbt-segv-gdb.sh
```

(the harness accepts `SOURCE`; it still seals nothing and records no attempt). If a crash
is captured, the first discriminating experiment is decided by the frame **above**
`_PyEval_EvalFrameDefault` in the native backtrace — not before.

**Not done, deliberately:** no retry, no dependency or threading change, no lockfile edit,
no weakening of the complete-build check.

## Staging runbook — partly runnable

Rows marked **real** exist and are tested; rows marked *proposed* are names fixed here so
the design and the implementation agree, and do not exist yet.

| Stage | Proposed command | What it does | What you should see |
|---|---|---|---|
| build **(real)** | `uv run build-candidate --source data/warehouse/energy.duckdb [--schedule workbook\|demo] [--root <dir>]` | validates source and destination, snapshots into `data/published/versions/cand-<timestamp>.duckdb` (read-only attach; an ingestion lock is reported as such), clears any inherited build schema, runs the guarded dbt build once, then seals | `sealed <file> · N models, M tests passed` and **READY FOR PROMOTION — not published**, or a non-zero exit naming the failed stage and the candidate path |
| validate **(real)** | `uv run publication finalise <file>` (run automatically by `build-candidate`; re-run it to retry a sealing that failed after a successful build) | refuses a `.wal`; requires the **latest** attempt to be a succeeded `build` recorded in this file, the only attempt, with the tables digesting as recorded (`canonical-rows-1`); writes `<file>.validated.json` with the SHA-256, run_id, both digests and the identity; makes the file read-only | `sealed <file> · run <run_id> · sha256 …` or a named refusal: *latest attempt … failed*, *… never finished*, *not this file*, *N attempts*, *changed them after that build*, *shape this version does not write* |
| record **(real)** | `uv run capture-published-baseline --root <root> [--directory data/baselines]` | resolves and validates the publication, then writes `pub2-<id>.json`: inputs, identity and the exact outputs a rebuild must reproduce | the baseline path, the dbt run, `complete, 54 required nodes`, the member digests, and the replay command to run |
| replay **(real)** | `uv run replay-published-baseline --baseline pub2-<id>.json --into <fresh dir>` | verifies the archive, member digests and workbook **before** anything is created, re-ingests the members, runs `build-candidate`, compares every input, identity and output | `REBUILD REPRODUCED THE PUBLISHED RESULT EXACTLY` (exit 0), a named list of differing fields (exit 1), or a refusal naming the missing artifact (exit 2) |
| read *(real, library only)* | `reads.published(root)` / `reads.candidate(<file>)` / `reads.warehouse(<db>)` in Python | validates once (manifest ↔ seal ↔ build record ↔ file bytes ↔ built-table digest) and returns a `ReadContext`; every analytics call takes `relations=context.relations` | a context whose `label` names the version or says **CANDIDATE — NOT published**; a refusal naming the two pieces of evidence that disagreed. **Not wired into the dashboard yet** |
| view **(real)** | `ENERGY_RECONCILIATION_PUBLICATION_ROOT=<root> PYTHONPATH=src uv run streamlit run src/energy_reconciliation/explorer/app.py`, then **Source → Published version** | resolves the manifest once per rerun, validates, and reads tariff figures and identity from the sealed dbt build | the sidebar shows *Published v000N*; the tariff tab says *dbt build (`scenario_build`), sealed and promoted*; with nothing published, an explicit **No published version is available** and no tab at all |
| inspect a candidate *(proposed)* | a *Candidate* picker in the dashboard, read-only | renders against a sealed but unpromoted candidate | deliberately **not** in this slice: `reads.candidate()` exists and is tested, but no UI selects one |
| promote **(real)** | `uv run publication promote <file> --expect-published <version or none>` | lock, compare-and-swap against `--expect-published`, re-hash against the seal, tmp → fsync → rename → fsync dir; writes `published.json`, appends `history.jsonl` | `published v000N <file> (previous v000N-1)`; a stale request prints the version it expected and the one it found, and changes nothing |
| rollback **(real)** | `uv run publication rollback <retained file name> --expect-published <version>` | the same promotion path pointed at a retained version — seconds, no rebuild | `published v000N+1 <old file>`; the dashboard's next rerun shows the old figures with their own run record |
| recover **(real)** | `uv run publication recover` | removes an orphan `published.json.tmp` and a lock whose pid **and start time** are dead; **never edits the manifest**, never touches a candidate; refuses when it cannot tell | what was removed, *nothing to recover*, or `RecoveryRefused` |
| status **(real)** | `uv run publication status` | one manifest read | `published v000N -> <file> · run … · dbt-core … · previous …`, or `UNAVAILABLE` with exit 1 |
| inventory **(real)** | `uv run publication inventory` | every version file and its role: published, previous, retained, sealed-unpublished, unsealed, broken | a table; **deletes nothing** |

Retention is a **documented policy, not a command** in this slice: keep the newest N
versions; never delete the published or the previous one; never delete anything younger
than a grace window, because a render opens a fresh connection per query to the path it
resolved at its start. `inventory` is the dry run. A deleting command (I-17) needs its own
confirmation step and is deliberately not written yet.

## A guided local exercise for Hammam — steps 1, 2, 4, 5 and 6 are runnable now; step 3 waits for the dashboard switch

Work on a copy, never on `data/warehouse/energy.duckdb`. Predict the outcome of each step
before running it; write the prediction down.

1. **Look at what is published.** `cat data/published/published.json`. *Expected:* one
   version, its file name, its sha256, its run_id, and `previous`. Open the dashboard;
   the sidebar should name the same version. Note the tariff tab's total.
2. **Build a candidate.** `uv run build-candidate --source data/warehouse/energy.duckdb`.
   *Expected:* `PASS=55` and a new file under `versions/`; `published.json` unchanged
   (check its modification time); the dashboard, refreshed, still shows the same version
   and total. Nothing you did has reached a reader.
3. **Inspect it.** Open the candidate in the dashboard's candidate picker. *Expected:*
   the same total as step 1 — the same inputs and the same rules produce the same
   figures — and a banner saying it is a candidate. Compare the run_id: different from
   the published one, because a candidate is a new build even when its figures match.
4. **Deliberately fail one.** Copy `data/raw/Tariffs.xlsx` to a scratch path, duplicate
   one schedule row with a different band, and build with `--workbook <that copy>`.
   *Expected:* the build fails with `ScheduleError: duplicated schedule label …`; the
   exit code is non-zero; no `validated` record is written; the failed file remains under
   `versions/` for you to inspect and has a `.wal` beside it if the writer died
   mid-transaction. **Refresh the dashboard: identical version, identical total.** Try
   `promote` on the failed file. *Expected:* refused, naming the reason; `published.json`
   unchanged.
5. **Promote the good candidate.** `uv run promote --candidate <file from step 2>
   --expect-published <version from step 1>`. *Expected:* `published v0002`; refresh the
   dashboard; the sidebar shows v0002 and the total is unchanged, because the inputs were.
   Now run the same promote command again. *Expected:* refused as **stale** — it expected
   v0001 and found v0002. That refusal is the protection against two people promoting at
   once.
6. **Roll back.** `uv run promote --candidate data/published/versions/<step-1 file>
   --expect-published v0002`. *Expected:* `published v0003` naming the old file; the
   dashboard shows the step-1 run_id again within one refresh. Nothing was rebuilt.
7. **Say, in your own words,** why step 4's failure could not have changed what step 1's
   dashboard showed, and which single file the answer depends on.

## Learning checkpoints (Hammam's, never marked automatically)

- Explain why a generated macro with a drift test is one definition and two hand-written
  copies with a comparison test are not.
- Explain why a pandas column of `Decimal` objects is a risk here and what a typed pyarrow
  table changes.
- Explain what a reader sees during a failed build under D5, and why a **separate file per
  attempt** — not `run_id` scoping inside one file — is what makes that safe.
- Explain the difference between the rename (atomic visibility) and the fsyncs (power-loss
  durability), and why the proof establishes the first and only *calls* the second.
- Explain why "the tables are unchanged" and "the latest attempt succeeded" are two
  different facts, and give the measured case where the first was true and the second
  false.
- Explain why summing or XOR-ing row hashes can make two different tables look the same,
  and what sorting the row hashes changes.
- Explain what a bare `FROM fact_interval_charge_scenario` resolves to inside a sealed
  candidate, and why that would have been wrong without anything failing.
- Explain why `dbt build` exiting 0 is not evidence that the project was built, and which
  file the answer is read from.
- Explain what "resolved once per rerun" protects against, and what would go wrong if the
  dashboard re-read the manifest for each tab instead.
- Explain why a *published version* may be cached between reruns and a *warehouse file*
  may not, in terms of what each one's identity is.
- Explain why a format-2 replay compares `run_id` for neither fact, and what would be
  wrong with a contract that did require it to match.
- Explain the difference between "the dbt build reproduces ANL-002's figures" and "the dbt
  build has ANL-002's identity", and which one the evidence supports.
