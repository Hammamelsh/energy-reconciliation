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
| `PROJECT_CONTEXT.md` | Maintained so a future session can resume from the repo alone — **VERIFIED** exists |
| `src/energy_reconciliation/profiling/` | Reader, validation, aggregation, report, CLI — **VERIFIED** works; `uv run profile-member` |
| `tests/` — 69 tests, synthetic fixtures | **VERIFIED** all pass; never touch `data/raw/` |
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

### 4.11 "The report that disagreed with its own JSON"

A test compared the in-memory report with its serialised form and failed: the malformed-field-count
distribution used **integer** dict keys, which JSON silently converts to **strings**. A caller
reading the file would have seen different data from a caller using the object.

The fix was to make the report use string keys, plus a permanent round-trip test asserting
`json.loads(written) == report`.

**Lesson:** "machine-readable" is a promise about what a *consumer* sees. Serialisation is part of
the contract, not a detail after it.

---

## 5. Explicitly NOT claimable yet

| Claim that must NOT be made | Why not |
|---|---|
| "Built an end-to-end data pipeline" | Only a profiler exists. No ingestion, no models, no orchestration. |
| "Processed 167 million rows" | 1,000,000 rows have been read in full, plus roughly 350,000 in samples. The archive total is INFERRED. |
| "Used dbt / Airflow / Spark / AWS" | None have been touched. |
| "Handled timezone and DST correctly" | Both conventions are UNKNOWN. Phase G did not find them in the sources it searched, and they are not recoverable from the data. |
| "Validated the full dataset" | One of two archives is CRC-unverified (deflate64); one of 168 members has been examined in depth. |
| "Built data-quality tests" | 48 tests cover the profiler's own logic. No tests assert data-quality rules over the source itself. |
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
