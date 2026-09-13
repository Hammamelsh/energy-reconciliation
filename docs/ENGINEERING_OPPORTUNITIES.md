# Engineering friction and automation opportunities

A running log of material friction met while building this project that automation or a
reusable developer tool might remove. It is evidence for a later decision (choosing a third
portfolio project, compared with a separate log kept in Lost Minutes), **not** a backlog.
Recording an entry does not authorise building anything. The standing practice is
`.claude/rules/engineering-opportunities.md`, which Claude Code loads at the start of every
session; this file holds the rules for entries and the entries themselves, and is deliberately
not loaded automatically.

## Rules

- **Material only.** Recurring manual work, confusing debugging, brittle integrations, quality or
  recovery problems. A one-off typo is not an entry.
- **Evidence, labelled.** Cite files, commands, commits, run ids or failures. Write UNKNOWN for
  anything unmeasured (effort is usually unmeasured: say so rather than estimate).
- **Kind.** Say whether it is an *own defect* (our implementation bug), *own recurring work*, an
  *upstream or environment defect*, or a *broader need* that other teams plausibly share. An own
  defect can seed a broader need; keep the two statements separate.
- **Existing solutions.** Cite sources, with the date accessed, when researched. Until then write
  NOT RESEARCHED; names listed "to check" are unverified pointers, not findings. Never claim that
  nothing comparable exists without evidence.
- **Deduplicate.** A recurrence updates the existing entry's *Repeat occurrences* line.
- **Correctness blockers are reported immediately** and tracked in their ticket; an entry here
  may point at a blocker but never replaces reporting it.
- **Here versus elsewhere.** Keep what was observed in this repository, with its evidence,
  separate from any claim that other teams share the need. That claim is a hypothesis, labelled
  unvalidated until its demand test has run.

## Entry template

```
### EO-NN · <short name>
**Kind:** … · **Status:** open / fixed here / watching / closed
- **Problem and evidence.**
- **Affected user and current workaround.**
- **Recurrence and effort.** (UNKNOWN when unmeasured)
- **Best response.** small fix / script / existing tool / integration / new product, and why.
- **Existing solutions.** (sources and date if researched; otherwise NOT RESEARCHED)
- **Smallest useful reusable capability.** Visual interface helps? Cheap demand test.
- **Repeat occurrences.**
```

## Entries

Seeded 2026-09-13 from existing repository evidence. Each problem below is recorded as it was
found; its current state is stated separately, and none is assumed to remain unfixed.

### EO-01 · A build record that no longer describes the tables it certifies
**Kind:** broader need, seeded by own defects (fixed) · **Status:** fixed here; broader need unvalidated
- **Problem and evidence.** Three ways a candidate could be sealed on a success record that did
  not describe its file, each reproduced before it was fixed (2026-09-08): `COPY FROM DATABASE`
  copied `scenario_build` whole, so a snapshot inherited its source's success record and
  `finalise` accepted a file never built as a candidate; a failed rebuild left the previous
  success record standing; and `dbt build --exclude test_type:singular` exited 0 with all eleven
  reconciliation tests skipped, and was sealed. Commit `b831af0`; `docs/ideas.md` I-16 and I-18;
  design D5 in `docs/anl-003-dbt-design.md`.
- **Affected user and current workaround.** Whoever promotes a build. Before the fix the gap was
  invisible. Now: a digest of the built tables (`built_output_sha256`) recomputed at `finalise`,
  a fresh file for every attempt, and the required node set taken from dbt's `manifest.json` and
  checked against that invocation's `run_results.json` (`tests/test_candidate.py`,
  `tests/test_reads.py`, `tests/test_dbt_facts.py`).
- **Recurrence and effort.** Three failure modes found in one day of development; none in use
  since. Effort to find and fix: UNKNOWN.
- **Best response.** Here, done. More broadly, possibly a small reusable check, if existing dbt
  packages do not already provide it.
- **Existing solutions.** NOT RESEARCHED. To check: dbt's own artifacts (used here), the
  `dbt_artifacts` and Elementary packages, and whether dbt selectors or `--fail-fast` already
  cover partial builds.
- **Smallest useful reusable capability.** A command that reads a dbt target's `manifest.json`
  and `run_results.json`, derives the required nodes, refuses unless every one passed in that
  invocation, and prints a digest of the built relations. No visual interface; this belongs in CI
  output. Demand test: search dbt-core issues and the dbt community forum for promoted builds
  with skipped tests, and ask three dbt users whether they check a run's test coverage before
  promoting it.
- **Repeat occurrences.** None since 2026-09-08.

### EO-02 · An application reading an output other than the one it believes it is reading
**Kind:** broader need, seeded by own defects (contained or fixed) · **Status:** fixed here; broader need unvalidated
- **Problem and evidence.** Four related cases, 2026-09-08 to 09-09. (1) A runtime incident: the
  dashboard raised `BinderException: Referenced column "tariff_code_sha256" not found` because a
  Streamlit server started before `analytics.py` was edited kept the old module while another
  terminal migrated `scenario_run` (contained with a column check before the query and a distinct
  schema error; `tests/test_tariff_schema.py`). (2) Forecast reports were matched to a database
  by file name (I-19): byte-identical data at a new path was refused, and different data reusing
  a name would have been accepted. Found by review; no wrong figure was shown. (3) Until ANL-003
  step 5 the dashboard read the Python scenario while the dbt tables were outputs nothing read.
  (4) While a build holds a DuckDB file read-write, a reader cannot open it even read-only
  (measured, duckdb 1.5.5, I-14), so atomic publication and reader availability are separate
  problems.
- **Affected user and current workaround.** Dashboard readers and the operator. Now: immutable
  sealed versions behind an atomically replaced manifest (`src/energy_reconciliation/publication.py`),
  a read contract that returns the build's own identity, content-based report applicability
  (`src/energy_reconciliation/forecast/applicability.py`), and a restart after a code change.
- **Recurrence and effort.** One runtime incident, one review finding, one design gap and one
  measured lock behaviour in two days. Effort: UNKNOWN.
- **Best response.** Here, done. More broadly, an integration pattern (a read contract that
  checks identity at read time) more likely than a product, unless existing tools lack it.
- **Existing solutions.** NOT RESEARCHED. To check: dbt exposures, OpenLineage and Marquez, data
  contract tools, and snapshot identifiers in table formats such as Iceberg and Delta.
- **Smallest useful reusable capability.** A read-time guard: given an output and an expected
  identity (manifest digest, run id, schema version), refuse or label the read, and expose "what
  am I reading" to the app. A visual interface helps here: a small "version X, built by run Y"
  badge is the value a reader sees (the dashboard already shows its run identity). Demand test:
  ask five analysts or engineers whether a dashboard of theirs showed figures from a stale or
  wrong table in the last year, and how they found out.
- **Repeat occurrences.** None since 2026-09-09.

### EO-03 · Proving two builds agree, or explaining exactly how they differ
**Kind:** broader need; own recurring work (automated here) · **Status:** automated here; broader need unvalidated
- **Problem and evidence.** Moving the tariff logic from Python to dbt needed proof that both
  produce the same rows: 0 differing charged rows of 456,096 over every column, 0 differing
  exclusion rows of 2,541,866, the same exact total (ANL-003 step 4; `docs/roadmap.md`). Adding
  a source file needed the change explained, not just shown: REC-001 attributed +30 households,
  +507,567 charged readings and +£12,145.07 with a residual of exactly zero
  (`docs/rec-001-source-expansion.md`, `uv run compare-scenarios`). An independent recomputation
  in Python `Decimal` is what found that DuckDB's `DECIMAL * DECIMAL / 100` returns a `DOUBLE`
  (`docs/portfolio-evidence.md` story 4.13).
- **Affected user and current workaround.** Whoever migrates logic or adds data, and the reviewer.
  Now: project-specific comparison code and equivalence tests; `compare-scenarios` refuses two
  warehouses that differ in more than their source.
- **Recurrence and effort.** Equivalence runs on every test run; the explained-delta comparison
  was used once; the independent recomputation once. Effort: UNKNOWN.
- **Best response.** An existing tool probably covers row-level diffs. Attributing a change in a
  total to row classes with a stated zero residual is less clearly covered: a small reusable
  capability if research confirms the gap.
- **Existing solutions.** NOT RESEARCHED. To check: dbt-audit-helper's relation comparisons,
  data-diff tools (including datafold's open-source data-diff; its maintenance status is
  unverified), and Great Expectations or Soda for the assertions.
- **Smallest useful reusable capability.** Given two relations and a key: identical, changed,
  added and removed rows, and the change in a chosen total attributed to those classes with the
  residual stated. A visual interface helps: a delta bridge (waterfall) is what a finance or
  operations reader would use. Demand test: look for reconciliation with a residual in dbt
  migration guides and issues, and show a mock bridge to two people who have run a migration.
- **Repeat occurrences.** Not applicable yet (automated).

### EO-04 · Reproducibility claims that had never been executed
**Kind:** own defects (fixed); no broader need claimed · **Status:** fixed here; replay runs in hosted CI
- **Problem and evidence.** A replayed baseline matched every figure but not its fingerprint,
  twice (2026-09-08): the digest globbed `tariff/*.py`, so new replay tooling changed it; then it
  included load ids that embed the load time, so identical data in a fresh database could never
  match. It now keys on member content digests and 16 of 16 fields match (story 4.15 in
  `docs/portfolio-evidence.md`). The profiler's git commit plus a dirty-tree flag did not
  identify uncommitted code, now covered by `package_source_sha256` (`docs/profiling.md`), and a
  history rewrite left recorded commit hashes unresolvable (commit `d24969a`).
- **Affected user and current workaround.** Anyone relying on a recorded result later. Now:
  content digests, and format-2 baselines replayed by `tools/synthetic-quickstart.sh` in CI.
- **Recurrence and effort.** Two fingerprint failures in one session, one identity defect, one
  rewrite. Effort: UNKNOWN.
- **Best response.** A practice (execute the replay; CI now does) plus the small fixes made. Not a
  product.
- **Existing solutions.** NOT RESEARCHED.
- **Smallest useful reusable capability.** None beyond replay in CI; recorded so the pattern is
  recognised if it recurs.
- **Repeat occurrences.** None since 2026-09-08.

### EO-05 · An intermittent native crash inside `dbt build`
**Kind:** upstream or environment defect as far as established; debugging friction · **Status:** **unresolved release blocker**, open in `docs/tickets/ANL-003-dbt-port.md`; broader need unvalidated
- **Problem and evidence.** 303 invocations, 3 without a completion line, each corroborated by a
  kernel log entry or an attempt record, all within 23 minutes on 2026-09-09; 206 clean harness
  attempts since. The faults surface in CPython's `_PyEval_EvalFrameDefault` on a null or garbage
  object pointer; what wrote it is not established. The debugging itself was confusing, in
  measured ways: GDB's exit code is the opposite of the child's result; the kernel logs a
  page-fault SIGSEGV only when the handler is the default one; and subprocess reported the signal
  as `-11`, which read as a build fault until commit `826e997` named it.
- **Affected user and current workaround.** The operator and CI. Nothing is sealed on a crash; the
  message names the known crash; rerun. Three scripts exist: `tools/dbt-segv-gdb.sh`,
  `tools/dbt-segv-repro.sh`, `tools/dbt-segv-trace.sh`.
- **Recurrence and effort.** Three crashes in one window, none observed since (hosted CI green,
  most recently run 34721253334 on 2026-09-12). Clean runs are not evidence of a fix; the
  blocker stays open until a cause is established. Three investigations; hours UNKNOWN.
- **Best response.** Existing tools (core dumps, faulthandler, GDB) and an upstream report once a
  native backtrace exists. A new product is not indicated.
- **Existing solutions.** In use: Python faulthandler, GDB batch mode. NOT RESEARCHED:
  systemd-coredump, crash reporters.
- **Smallest useful reusable capability.** A wrapper that runs any child process and classifies
  how it ended (completed, failed with a code, killed by a named signal, unknown) from evidence
  rather than exit codes, with faulthandler output kept private: the harness's classifier,
  generalised. No visual interface. Demand test: search dbt and Python subprocess issues for
  "exit code -11" confusion.
- **Repeat occurrences.** None since 2026-09-09.

### EO-06 · Verifying each public release by hand
**Kind:** own recurring work · **Status:** open; the verification scripts were not kept
- **Problem and evidence.** Three releases of the public page, each verified by hand: `46ed791`
  (2026-09-10, `docs/deployment.md`: assets byte-identical to a local build), `e5263a7` and
  `a3ef044` (2026-09-12; the "Gate" in commit `a3ef044`, "Phones" in `web/README.md`, evidence
  2.48). Each time: compare live assets and data files with a local build byte for byte, load
  the page at 320, 390 and 1440 px, run axe-core, check console errors, CSP violations and failed
  requests, and exercise interactions. For `a3ef044` the scripts were written ad hoc in a session
  scratchpad and not kept; the Playwright Chromium binary needed `libnss3`, `libnspr4` and
  `libasound2` extracted from Ubuntu packages because there is no root access; and a DevTools
  full-page capture produced a false blank-canvas screenshot. LinkedIn's post inspector needs a
  sign-in, so link-preview caching remains unverified.
- **Affected user and current workaround.** Hammam at every release; repeated by hand.
- **Recurrence and effort.** Three times in three days. Effort per release: UNKNOWN.
- **Best response.** A repository script built on existing tools, written when the next release
  needs it. Not a product.
- **Existing solutions.** In the repository: `npm run check`, axe-core as a dev dependency. NOT
  RESEARCHED: Playwright Test with `@axe-core/playwright`, Lighthouse CI, pa11y-ci.
- **Smallest useful reusable capability.** One command taking the live URL and the local build:
  byte-compare every built asset and pinned data file, then overflow, tap-target, axe, console
  and CSP checks at three widths, printed as a pass/fail table. No visual interface. Demand is
  our own; no external test needed unless it is generalised.
- **Repeat occurrences.** 3 (2026-09-10, 2026-09-12, 2026-09-12).

## Own defects reviewed, no tool warranted

Fixed with a small change and a test. Listed so they are not re-proposed as opportunities.

| Defect | Fix |
|---|---|
| A display share rounded twice (4 dp, then 1 dp) showed 72.9% instead of 72.8% | Round once from the exact value; bundle re-exported (`b99fe5c`, `docs/prototypes/energy-terrain.md` §9) |
| Integer keys became strings on JSON round-trip, so the file disagreed with the object | String keys and a permanent round-trip test (story 4.12) |
| A test asserted `/tmp` is tmpfs, true on one machine only | The filesystem property that matters is asserted instead (`e7a2eaf`) |
| The demo explorer check skipped on every hosted CI run | It now builds its own fixture and runs everywhere (`826e997`) |
| A test asserted no charged row is zero; 133 real readings are measured zeros | The false invariant was removed; a zero reading is charged at exactly zero (acceptance review, 2026-09-08) |
