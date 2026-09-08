# Portfolio Evidence — Energy Billing and Reconciliation Simulator

**Purpose.** A working record of what this project has actually demonstrated, with the evidence
attached, so that CV bullets and interview answers can later be written from measured facts rather
than from memory or optimism.

**This file is deliberately not a CV.** No bullet here is phrased for a recruiter. Several entries
are marked NOT-YET-CV-READY, and those must not be used until the gap named in them is closed.

**Last updated:** 2026-09-07, after REP-001 Phase H. **Status of REP-001: OPEN** (criterion 11.6
outstanding).

## How to read this file

| Label | Meaning |
|---|---|
| **VERIFIED** | We measured it ourselves. A command and its output exist. |
| **PUBLISHER-DOCUMENTED** | The data publisher states it in authoritative documentation, quoted with a citation. Accepted as a source contract, not independently measured. |
| **INFERRED** | Derived by reasoning from verified items. Reasoning is written down. Not a fact. |
| **NOT-YET-CV-READY** | Real work, but not yet defensible as a portfolio claim. The specific gap is named. |

Nothing in this file may be upgraded to a stronger label without new evidence recorded in
`docs/source-data-profile.md`.

---

## 1. What has actually been built so far

**Honest summary: a verified source investigation plus one working, tested tool.** Eight phases are
complete. Phase H produced the project's **first production code** — a reproducible one-member
profiler with 48 passing tests. There is still **no pipeline**: no dbt model, no Airflow DAG, no
orchestration, no transformation beyond profiling.

| Artefact | Status |
|---|---|
| `docs/source-data-profile.md` | 1,745 lines, 14 sections, every claim labelled — **VERIFIED** exists |
| `docs/tickets/REP-001-source-data-investigation.md` | Full investigation spec written before work began — **VERIFIED** exists |
| `data/manifests/raw-file-manifest.csv` | Machine-readable integrity manifest, 6 files — **VERIFIED** exists |
| `src/energy_reconciliation/profiling/` | Reader, validation, aggregation, report, CLI — **VERIFIED** works; `uv run profile-member` |
| `tests/` — 83 tests, synthetic fixtures | **VERIFIED** all pass; never touch `data/raw/` |
| `docs/roadmap.md` — 7 delivery milestones with completion conditions | **VERIFIED** exists |
| `docs/rep-001-verified-facts.md` (47) and `…-assumptions-and-open-questions.md` (32) | **VERIFIED** exist; non-overlap machine-enforced |
| `data/profiles/lcl-june2015v2-0-profile.json` | Machine-readable full-member profile — **VERIFIED** exists |
| `docs/profiling.md` | Exact reproduction command — **VERIFIED** exists |
| Ingestion pipeline / dbt / Airflow / Spark | **DOES NOT EXIST** |

> **NOT-YET-CV-READY:** the project cannot yet be described as an end-to-end pipeline, a data
> platform, or an ELT project. It is a rigorous source investigation plus one profiling tool.
> Claiming otherwise would fail the first technical question asked about it.

---

## 2. Technical findings with evidence

Each item names what was measured and how, so it can be defended under questioning.

| # | Finding | Evidence | Label |
|---|---|---|---|
| 2.1 | Archive integrity: 168/168 members CRC-32 verified, 8,542,826,421 bytes checked in memory, nothing extracted | Phase B §9.4 | **VERIFIED** |
| 2.2 | `LCL-FullData.zip` uses **deflate64**, which Python's `zipfile` cannot decompress; its integrity is unverified | Phase B §9.4 | **VERIFIED** |
| 2.3 | Header is byte-identical across **all 168 members** (single SHA-256, census not sample) | Phase F §13.2 | **VERIFIED** |
| 2.4 | 4 columns: `LCLid`, `stdorToU`, `DateTime`, `KWH/hh (per half hour) ` — the fourth **ends in a space** | Phase C §10.3, Phase F census | **VERIFIED** |
| 2.5 | Values are **per-interval, not a cumulative register**: 142 decreases in 299 consecutive pairs, max value 1.164 | Phase D §11.3 | **VERIFIED** |
| 2.6 | Consumption unit is kWh per half hour | Dataset page + column name, Phase G §14.4 | **PUBLISHER-DOCUMENTED** |
| 2.7 | Missing-value token is `Null` — capital N, **unpadded**, while numeric values *are* space-padded (`' 0.2 '`) | Phase E §12.5 | **VERIFIED** |
| 2.8 | All observed `Null` rows sit **off the half-hour grid**; all off-grid rows are `Null` rows | Phase E §12.6 | **VERIFIED** |
| 2.9 | Archive is two blocks by tariff group: members 0–134 `Std`, 135–167 `ToU`, holding disjoint households | Phase F §13.3 | **VERIFIED** |
| 2.10 | **Households span member boundaries** — `MAC000166` appears in both member 4 and member 5 | Phase F §13.4 | **VERIFIED** |
| 2.11 | Split rule is exactly 1,000,000 rows per file; final member has 932,474 | Phase F §13.5 (5 members measured) | **VERIFIED** |
| 2.12 | Archive total ≈ 167,932,474 rows | Phase F §13.5 | **INFERRED** (163 members not counted; corroborated by byte arithmetic to 0.02 bytes/row) |
| 2.13 | `household + timestamp` is **not** a unique key: 105 collisions, all exact duplicates, 0 conflicting | Phase E §12.8 | **VERIFIED** (within scope) |
| 2.14 | Stream is ordered by *(group, household, timestamp)* — **not** globally time-ordered | Phase F §13.8 | **VERIFIED** |
| 2.15 | Zero rates vary 0.0%–76.7% between neighbouring households | Phase E §12.10 | **VERIFIED** (5 households) |
| 2.16 | Licence is **CC BY 4.0**, and the link is in this dataset's own licence field (not site chrome) | Phase G §14.5, link followed and its page position checked | **VERIFIED** |
| 2.17 | Timezone, interval start-vs-end, DST handling and the meaning of nulls/gaps were **not found in the two named LCL reports or the dataset page**, using recorded word-boundary searches (205 pages, 610,932 characters) | Phase G §14.4 | **VERIFIED search result** — a scoped negative, **not** proof the semantics are undocumented; other LCL documentation is unexplored |
| 2.18 | Member 0 holds **exactly 1,000,000 data records**, counted directly | Phase H §15.1, `data/profiles/…json` | **VERIFIED** |
| 2.19 | **Six reconciliation equations hold** over 1,000,000 records, including `raw lines = header + parsed + rejected` | Phase H §15.2 | **VERIFIED** |
| 2.20 | Full member: 0 malformed, 0 invalid timestamps, **0 negatives**, 0 empty, 0 unexpected tokens, 0 non-finite; 45,538 zeros; 29 `Null` | Phase H §15.3 | **VERIFIED** |
| 2.21 | **29 off-grid rows == 29 `Null` rows**, same record numbers, across 1,000,000 records / 30 households — the Phase E correlation at full scale | Phase H §15.4 | **VERIFIED** |
| 2.22 | 688 exact duplicate extra rows == 688 key collisions, **0 conflicting** | Phase H §15.6 | **VERIFIED** (this member) |
| 2.23 | Member 0 is **ASCII-compatible**: 0 bytes >= 0x80 in 50,755,532 bytes | Phase H §15.7 | **VERIFIED** — does not distinguish UTF-8 from Latin-1 |
| 2.24 | Profiling 1,000,000 rows uses **~38 MB peak memory** because duplicate detection is disk-backed (SQLite), not in-RAM | Phase H, `/usr/bin/time -v` | **VERIFIED** |
| 2.25 | All eight REP-001 acceptance criteria met; ticket still open on one engineering item (§6 distribution summary) and the §13 checkpoints | profile §16 | **VERIFIED assessment** |
| 2.26 | Go/no-go recorded: **no-go for billing, go for ingestion**, with three named blockers | profile §16.3 | **VERIFIED assessment** |
| 2.27 | Consumption distribution over 999,971 values: min `0`, max `6.5279999`, sum `239572.7849879`, mean `0.239579733`, median `0.129`, IQR `0.195` | profile §15.3 | **VERIFIED** — count/min/max/sum exact; mean derived |
| 2.28 | Percentiles use nearest rank, so every reported figure is an **observed value**, not an interpolation | profile §15.3 | **VERIFIED** |
| 2.29 | Percentiles and the zero count agree by independent routes: 45,538 zeros = 4.554%, p1 (rank 10,000) `0`, p5 (rank 49,999) `0.005` | profile §15.3 | **VERIFIED** |
| 2.30 | The **source** contains binary-float artefacts (`6.5279999` for `6.528`); our arithmetic is Decimal throughout | profile §15.3 | **VERIFIED observation**, cause UNKNOWN |
| 2.31 | Ingestion into DuckDB with a decided rerun policy: unchanged source **and** pipeline skips, either changing rebuilds; publication atomic per member; superseded loads kept in the registry | ING-001, `tests/test_ingest.py` (10 tests) | **VERIFIED** |
| 2.32 | Explorer computes every tab for one household and one date range; three kinds of repetition kept apart (exact duplicate, equivalent representation, conflict); conflict days publish no total and the rendered chart spec draws no bar for them | ING-001, `tests/test_explorer_policy.py` | **VERIFIED** (spec asserted, layout not visually inspected) |
| 2.33 | Off-grid observations excluded from half-hour totals, counted and plotted with provenance; `Null` beside a number withholds the total as an analytical policy | ING-001 closing policies | **VERIFIED**, policy labelled as ours |
| 2.34 | Tariff workbook read-only: one sheet, 17,520 unique on-grid half-hour labels for 2013, three band labels, no prices, no formulas, no DST representation; schedule-side join uniqueness measured (factor 1.0000) | `docs/anl-001-tariff-workbook-findings.md` | **VERIFIED**; time alignment remains an **assumption** |
| 2.35 | Tariff band schedule and publisher-documented prices modelled **separately** in DuckDB; flat-rate effective dates stored as UNKNOWN, never defaulted to the data span | ANL-002 §1, `dim_tariff_price` | **VERIFIED** |
| 2.36 | Interval charge scenario over 456,096 real `ToU` readings; `charged + excluded = distinct readings` holds exactly on 2,997,962 readings; every excluded reading carries one explicit reason and never a zero charge | ANL-002 §6, `tests/test_tariff.py` (31 tests) | **VERIFIED** |
| 2.37 | Independent recomputation in pure Python `Decimal`, outside the model, agrees with the SQL fact to every digit (`11675.433921653250`), per band as well as in total | ANL-002 §7.3 | **VERIFIED** |
| 2.38 | DuckDB evaluates `DECIMAL / 100` as `DOUBLE` (`1.125 × 67.2000 / 100` → `0.7559999999999999`); the division is done once in Python `Decimal` instead, so no binary float reaches a money-adjacent figure | ANL-002 §2 | **VERIFIED** |
| 2.39 | Duplicate, conflict, missing-value and off-grid rules have **one** definition (`src/energy_reconciliation/policy.py`) imported by both the explorer and the tariff models | ANL-002 §4 | **VERIFIED** |
| 2.40 | Member 135 measured: 1,000,000 rows, `ToU` only, 27 households, 456,408 rows in 2013, 27 `Null` tokens all also off-grid; **0** loaded households recorded under more than one tariff group | ANL-002 §5 | **VERIFIED**; AQ-22/23 still open (3 of 168 members) |
| 2.41 | `High` band = 4.90% of charged kWh and 24.09% of the scenario charge; `Low` = 10.48% and 3.06%, against stated denominators | ANL-002 §7.2, §8 | **VERIFIED**; **no causal claim** |
| 2.42 | Calculation identity names 17 first-party files explicitly, including the shared `policy.py`, checked against the models' **real import closure taken in a fresh interpreter** | `tests/test_tariff_identity.py` | **VERIFIED** |
| 2.43 | Reporting and replay code deliberately excluded from the digest, so an edit that cannot change a stored figure does not invalidate one | ANL-002 §9.1 | **VERIFIED**, decided and justified |
| 2.44 | Runtime identity (Python, DuckDB, PyArrow, pandas, openpyxl) recorded with every run and folded into the fingerprint | `scenario_run.runtime_detail` | **VERIFIED** |
| 2.45 | A captured baseline **replayed into a fresh database** and reproduced all 16 compared fields, including the exact total, every per-band charge, all 27 per-household charges and the fingerprint | ANL-002 §9.2, executed 2026-09-08 | **VERIFIED by execution** |
| 2.46 | Explorer scenario views separated into selected household / loaded sample / published schedule, each with its own period bounded by schedule coverage | `tests/test_tariff_views.py` | **VERIFIED** (spec and frames asserted; browser interaction not performed) |
| 2.47 | Both shares of every scenario view come from the same filtered rows; an empty selection returns no rows and the chart encodes no quantity | `tests/test_tariff_views.py` | **VERIFIED** |

---

## 3. Engineering decisions worth defending

These are the decisions that show judgement rather than tool familiarity.

### 3.1 Labelling every claim by evidence strength — VERIFIED

A four-label scheme (VERIFIED / PUBLISHER-DOCUMENTED / INFERRED / UNKNOWN, plus CONTRADICTED) applied
to every statement in the profile.

**Why it mattered, concretely:** Phase B inferred 994,048 rows per file from an even-split
assumption and labelled it INFERRED with an explicit warning not to use it as an expected count.
Phase F measured the real figure: **1,000,000**. The label is why that error was *caught* rather
than *inherited* into a reconciliation check.

### 3.2 Pre-registering scan bounds before looking at data — VERIFIED

Every bounded scan declared its stopping rule in writing first — sample size, thresholds, what
counts as a qualifying window.

**Why:** in Phase D the question was whether consumption values rise and fall. Had "enough non-zero
values" been left undefined, it would have been possible to keep searching until a window agreed
with the expected answer. Fixing the threshold first removes that freedom. In the event the first
window qualified, so no selection occurred at all.

### 3.3 Read-only handling of source data — VERIFIED

Raw archives were never extracted, renamed or modified. Every archive operation streamed in memory.
`stat` captured size, mtime, inode and mode before and after every phase; the comparison is
byte-identical throughout, and manifest SHA-256 values still reproduce.

**Why inode matters:** an inode change would reveal a file had been *rewritten* rather than modified
in place — a check that size and mtime alone would miss.

### 3.4 Designing reversibly around an unresolved unknown — INFERRED (not yet built)

Timezone and interval-anchor semantics are undocumented. The design records timestamps exactly as
supplied, keeps semantics in configuration rather than code, makes every dependent figure a
recomputable view, and stamps outputs with the assumptions that produced them.

**Why:** converting to UTC at ingestion under a guess destroys the original and makes a wrong guess
undetectable and irreversible.

> **NOT-YET-CV-READY** — this is a written design, not an implementation.

### 3.5 Measuring physical lines and logical records separately — VERIFIED

The profiler counts line terminators in the decompressed bytes **and** records returned by the CSV
parser, independently, then reports whether they agree.

**Why:** a quoted CSV field may legally contain a newline, so one line does not universally equal one
record. Every earlier phase assumed it did. For this member they do agree — so the ticket's
`raw lines = header + parsed + rejected` equation is valid *here*, as a measured property rather than
an assumption. A regression test builds a fixture with a quoted newline and asserts the profiler
reports the equation as **failing**, so the check cannot quietly become an assumption again.

### 3.6 Keeping memory flat with a disk-backed join — VERIFIED

Exact duplicate detection over 1,000,000 rows would cost hundreds of megabytes as Python objects.
Streaming records into a temporary SQLite database instead held peak memory to **~38 MB** while
keeping the answer exact.

**Why it matters beyond this file:** the same code will run against members of any size, and against
167 more of them, without the memory profile changing.

### 3.7 Distinguishing a census from a sample — VERIFIED

Phase F read all 168 headers (**census** — conclusions hold archive-wide) but sampled records from
5 members (**sample** — can refute uniformity, never prove it). The two were reported separately
with different strength of conclusion.

**Why it mattered:** the sample found `stdorToU = ToU`, a value that five earlier phases never saw,
because member 0 is entirely `Std`. The selection risk flagged in Phase E was real and was caught.

---

## 4. Interview stories

Short, specific, and true. Each names a mistake or a surprise, because those are what interviewers
probe.

### 4.1 "A prediction from arithmetic alone, tested and confirmed"

Two archives held the same dataset in different shapes. Their uncompressed totals differed by
**8,183 bytes**, and 8,183 = **167 × 49** exactly — 167 being the number of *extra* files in the
split version. That predicted a 49-byte repeated header **before any CSV byte was read**. Measured
later: 47 bytes of text + 2-byte CRLF = **49**.

**The point of the story is the discipline, not the trick:** it was recorded as INFERRED, with the
falsifying test named in advance, and it was explicitly *not* treated as proof that the two archives
were interchangeable — equal header sizes are necessary, not sufficient.

### 4.2 "The test that returned True and told me nothing"

To distinguish per-interval values from a cumulative meter register, the natural test is *a
cumulative register never decreases*. In the first 20-record sample it returned `True`.

It was worthless. **All 20 values were exactly 0.** A constant series has zero decreases — and zero
increases. It passes the test while carrying no information at all. The finding was recorded as
UNKNOWN, and the question was settled later on a proper window: **142 decreases in 299 pairs**.

**Lesson:** a passing test on degenerate input is not evidence.

### 4.3 "My own grep produced a confident false positive"

Searching two official PDFs for timezone definitions, the first pass reported **55 hits for "UTC"**
and **95 for "BST"**. Both were artefacts of case-insensitive substring matching: `utc` inside
"o**utc**omes", `bst` inside "s**ubst**ation". With word boundaries, both dropped to **zero**.

**Lesson:** the failure mode would have been claiming the reports *do* define a timezone — a false
positive in the direction I wanted. Verify the search, not just the result.

### 4.4 "The label the publisher never used"

The profile described ~4,500 households as a "control group", marked VERIFIED. Re-checking the full
official page found the term appears **nowhere**; the publisher says only that those customers'
readings "were not subject to the dToU tariff", and describes all 5,567 as one balanced sample —
not as treatment and control arms.

"Control group" implies randomised assignment. It was reclassified: the wording became **"remaining
non-dToU sample"**, with the control-group reading recorded as INFERRED.

**Lesson:** an experimental-design claim was about to be inherited from a paraphrase.

### 4.5 "Where the file boundaries are is a correctness problem"

The archive looks like 168 independent CSVs. It is one row-ordered stream cut every million rows —
so **`MAC000166` appears in both member 4 and member 5**.

A per-household job processing one file at a time would compute that household's totals and
first/last reading dates **twice, each time from a fragment** — and would not fail. It would return
confident, wrong numbers.

### 4.6 "Applying a rule too strictly is also an error"

The unit was recorded as UNKNOWN for four phases, on the reasoning that observed values cannot prove
their own physical unit. That misread the ticket, which required a **citation**, not an experiment —
and the citation had existed since Phase A.

**Lesson:** over-caution is not free. It parked a resolved question as an open blocker. Rigour means
applying the standard that was actually written down.

### 4.7 "A negative result, scoped honestly"

Timezone and interval semantics could not be found. Rather than record a vague "we didn't find it",
the search was made specific and repeatable: **205 pages, 610,932 characters** of two named official
reports, word-boundary searched for 19 recorded terms. All zero. The CSV's own column names appear
in neither report.

**The discipline is in what was *not* claimed.** The finding is "not found in these sources using
these searches" — not "not documented anywhere". A substantial LCL learning-report series remains
unopened, and a document could define the convention in wording no search term would match.
Overstating a scoped negative as a universal one is a claim that collapses the moment someone
produces the document.

**Lesson:** a searched negative is useful precisely because its scope is stated. It let us stop
waiting on the answer and design around it, without pretending the question is closed.

---

### 4.8 "Statistics that never touch a float"

Summarising 999,971 consumption values needed a minimum, maximum, mean and spread. The obvious
implementation loads them into a list and calls a stats library — hundreds of megabytes, and binary
float error compounding across a million money-adjacent values.

Instead: count, min, max and sum accumulate exactly with `Decimal` in **constant memory** while the
file streams, and percentiles come from the SQLite store already on disk, selected by **nearest
rank** so every reported figure is an actually observed value rather than an interpolation between
two. The mean is the only rounded number, and the report says so explicitly per statistic.

**The payoff was immediate:** the largest observed values are `6.5279999` and `6.5100002` — which is
what `6.528` and `6.51` look like after a round-trip through an IEEE-754 float. That artefact is in
the **source**. Had the profiler used floats, that finding would have been indistinguishable from
noise we introduced ourselves.

### 4.9 "A legal file reported as a failure"

The profiler folded the `physical_lines == header + parsed` check in with its logical partitions and
reported a single `all_hold`. On a CSV containing a quoted field with a newline — **legal CSV** —
physical lines exceed logical records, so `all_hold` became false even though every logical partition
reconciled perfectly. A valid, complete profile was being reported as a reconciliation failure.

The fix separates `core_partitions` (the correctness signal, driving the exit code) from
`source_shape_checks` (a property of this file's physical layout). A test asserts a multiline member
exits 0 with core partitions holding and the shape check not holding.

**Lesson:** a check that conflates "this file has an unusual shape" with "the arithmetic is wrong"
trains people to ignore failures.

### 4.10 "A commit hash that identified nothing"

The report recorded `git_commit` plus `git_tree_dirty: true`. Those two fields together do **not**
identify what ran: every dirty run at that commit shares the same commit id while the code differs.

The report now names `package_source_sha256` as the authoritative fingerprint, lists the exact files
it covers, states what it excludes (tests, `pyproject.toml`, dependency versions) and carries an
explicit `git_identity_sufficient` flag. Tests assert the digest changes when a source file is edited
**or renamed**.

**Lesson:** "we record the git commit" sounds like reproducibility and isn't, the moment the tree is
dirty — which for a working session is most of the time.

### 4.11 "The withheld total that had a bar"

The demo conflict day read "total withheld" beside a 3.5 kWh bar. Tracing the SQL showed the
daily sum included **both** disputed values at 03:30. The fix was not to hide the bar but to
make the day carry no number at all, and to assert on the chart specification the UI renders
that a withheld day appears only in a baseline marker layer that encodes no quantity.

**Lesson:** "withheld" is a property of the number, not of the label next to it. Test the
artefact the user sees.

### 4.12 "The report that disagreed with its own JSON"

A test compared the in-memory report with its serialised form and failed: the malformed-field-count
distribution used **integer** dict keys, which JSON silently converts to **strings**. A caller
reading the file would have seen different data from a caller using the object.

The fix was to make the report use string keys, plus a permanent round-trip test asserting
`json.loads(written) == report`.

**Lesson:** "machine-readable" is a promise about what a *consumer* sees. Serialisation is part of
the contract, not a detail after it.

---

### 4.13 "A total that was right because two implementations agreed"

The scenario charge came out of one SQL model. Passing tests would only have shown the model
agreed with itself, so before publishing the figure I recomputed the whole 2013 charge a second
way: pure Python `Decimal`, reading the workbook and the readings directly, applying
`kwh × pence ÷ 100` literally, row by row, outside the model. It matched to every digit —
`11675.433921653250` — and matched per band as well.

Writing that check is also what found the real defect. In SQL, `DECIMAL * DECIMAL / 100` is not a
decimal at all: DuckDB returns a `DOUBLE`, and `1.125 × 67.2000 / 100` comes back as
`0.7559999999999999`. Had I written the formula the way the specification states it, a binary
float would have been sitting under a money-adjacent figure in a project whose whole argument is
that floats do not belong there. The division now happens once, in Python, when the price
catalogue is built.

The second implementation was used once, as a check, and deliberately **not** kept — two
permanent implementations of one rule is the problem, not the solution.

### 4.14 "£16.64 that meant nothing about electricity"

One household in the loaded `ToU` sample had a scenario charge of £16.64 against a sample where
the others ran from £185 to £1,301. It would have been easy to present as the frugal household.

It was charged for 864 half hours out of 17,520 — exactly 48 × 18, the complete days from
1 to 18 January 2013. What is measured: its rows occupy records 1–7,441 of member 135, the next
household starts at 7,442, and no reading for it appears after 18 January in the loaded members.
Whether more of its history sits in member 134 is not established, because 134 is not loaded.
Why readings are absent is not established either, and I did not put a reason on it.

The lesson I keep from it: a per-household total without its contributing-reading count beside it
is not a measurement, it is a trap. The explorer now shows both, and the finding is written up as
a coverage artefact rather than as a fact about consumption.

### 4.15 "The replay that failed twice, and was right to"

The scenario had a fingerprint covering code, prices, schedule and data, and every test passed.
Then I captured a baseline and actually replayed it into a fresh database. Every figure matched
— the exact total, all three bands, all 27 households — and the fingerprint did not.

The first cause was over-sensitivity: the digest globbed `tariff/*.py`, so the replay tooling I
had just written changed the fingerprint of a result whose every number was identical. I fixed
the covered set to files that can change a *stored* figure, and added a test that takes the real
import closure of the models in a fresh interpreter so under-inclusion still fails loudly.

It failed again. The second cause was worse: the fingerprint included the published `load_id`s,
and a load id embeds the moment of loading. Byte-identical data in a fresh database could never
have fingerprinted the same. The reproducibility guarantee had never been reproducible, and
nothing in the test suite could have told me, because every test built exactly one warehouse.

It now keys on member content digests, and the replay matches all 16 fields. What I keep from
it: a reproducibility claim that has not been executed is a hypothesis.

## 5. Explicitly NOT claimable yet

| Claim that must NOT be made | Why not |
|---|---|
| "Built an end-to-end data pipeline" | Only a profiler exists. No ingestion, no models, no orchestration. |
| "Processed 167 million rows" | 1,000,000 rows have been read in full, plus roughly 350,000 in samples. The archive total is INFERRED. |
| "Used dbt / Airflow / Spark / AWS" | Airflow, Spark and AWS: **untouched**. dbt: an **early slice only** (ANL-003 steps 0–2, 2026-09-08) — `dbt-core 1.12.4` / `dbt-duckdb 1.11.0`, a staging view and two policy models whose SQL is generated from `policy.py`, proven to return the same rows as the Python path. **The tariff models that produce the charge are NOT in dbt**, and no dbt model writes a stored figure: no fact, no dimension, no publisher, no dbt test. The claim available is "began a dbt port, with the shared policy kept to one definition", never "built the pipeline in dbt". |
| "Calculated electricity bills" / "reproduced historical costs" | The tariff figures are a **scenario** under assumption A1, which is not established. No standing charge or levy is modelled, and **no separate tax adjustment is applied** — the tax treatment of the published rates is itself unresolved. The flat rate's effective period is UNKNOWN, so no `Std` household is costed at all. |
| "Showed households responding to price signals" | Nothing measured supports a causal claim. There is no comparison group and no before-and-after in this measurement. |
| "Analysed London energy use by area" | No geographic breakdown exists. One would require metadata legitimately linked to these households; none has been linked. |
| "Analysed the dToU cohort" | 27 households from one member of 168: a **bounded, non-representative subset**, not a sample drawn from the trial by any procedure. No figure over them should be scaled up. |
| "Verified the UI works" | The rendered chart specifications and the frames behind them are tested, and the app was driven headless through every view, period, household and dataset switch. **No browser interaction was performed** — no browser is available in this environment. |
| "Explained why a household's readings stop" | Short coverage is observed. The cause is not established and is not guessed at. |
| "Handled timezone and DST correctly" | Both conventions are UNKNOWN. Phase G did not find them in the sources it searched, and they are not recoverable from the data. |
| "Validated the full dataset" | One of two archives is CRC-unverified (deflate64); one of 168 members has been examined in depth. |
| "Built data-quality tests" | 187 tests cover this project's own logic, including the tariff policies. No test asserts a data-quality rule over the source archive itself. |
| "Built a schema-validating reader" | The profiler validates and reports; it does not yet emit validated records for downstream use. |
| "Profiled the whole archive" | One member of 168. |

---

## 6. The gap between this and a portfolio project

Closing REP-001 needs four things, and only two of them are write-ups:

| Deliverable | Kind of work |
|---|---|
| Verified-facts list and assumptions/open-questions list | **Consolidation** — reorganises evidence already recorded |
| Machine-readable profiling result | **Consolidation plus output from the profiler below** |
| End-to-end count reconciliation for one complete file | **Requires reading one full member (~1,000,000 rows).** `raw lines = header + parsed rows + rejected rows` cannot be shown from samples. This is real execution, not documentation. |
| Written go/no-go recommendation | **Consolidation** |

The next implementation is therefore a **reproducible one-file profiler** producing a
machine-readable result with reconciled counts. It reads one member end to end, so it also satisfies
the reconciliation criterion.

Note the scheduling consequence of the timezone unknown: it blocks **authoritative billing**, not
**lossless ingestion or profiling**. Ingestion-side work can proceed now.

After that, a streaming schema-validating reader turns findings 2.3–2.14 into enforced, tested rules.
**At that point** most of section 5 begins to become claimable — and the interview stories in
section 4 are already the strongest material here, because they are specific, self-critical and
true.
