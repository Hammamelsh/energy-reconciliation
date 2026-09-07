# REP-001 — Assumptions and open questions

Everything we believe but have **not** proven, everything marked UNKNOWN, and every question a later
ticket must answer.

**Companion document:** [`rep-001-verified-facts.md`](rep-001-verified-facts.md). The two lists are
**non-overlapping**: nothing here is also claimed as a verified fact, and
`tests/test_rep001_lists.py` enforces that mechanically.

**Labels used here**

| Label | Meaning |
|---|---|
| **INFERRED** | Derived by reasoning from verified items. Reasoning shown. Not a fact. |
| **UNKNOWN** | Cannot currently be answered. |
| **ASSUMPTION** | Something we are proceeding on without proof, recorded so it can be withdrawn. |

---

## A. Blocking unknowns — these prevent authoritative billing

| ID | Question | Status | Why it blocks, and what would settle it |
|---|---|---|---|
| AQ-01 | Is `DateTime` UTC, GMT, UK local civil time, or something else? | **UNKNOWN** | Determines which billing period a reading falls in. Not present in the data — the strings carry no offset — and not found in the sources searched (VF-47). Only authoritative documentation can settle it. |
| AQ-02 | Does a timestamp mark the **start** or the **end** of its half-hour? | **UNKNOWN** | Shifts every reading by 30 minutes across period boundaries. Not derivable from data; documentation only. |
| AQ-03 | How are daylight-saving transitions represented? | **UNKNOWN** | If timestamps are local time, spring transitions create legitimate gaps and autumn creates legitimate duplicate timestamps. REP-001 §7 forbids investigating this until AQ-01 is resolved. |

**These three do not block lossless ingestion, profiling, data-quality measurement or count
reconciliation.** They block only the assignment of energy to a defensible billing period.

## B. Provenance gaps

| ID | Question | Status |
|---|---|---|
| AQ-04 | What is the real **download date** of the three raw files? | **UNKNOWN** — filesystem timestamps record when files appeared on this machine, not retrieval. REP-001 §3 requires it; recorded as explicit UNKNOWN under §11.7. |
| AQ-05 | Which page resource became which on-disk filename? | **INFERRED** from an exact three-way byte-size match, not observed at download time (profile §9.9). |
| AQ-06 | What does the `CC_` prefix in `CC_LCL-FullData.csv` mean? | **UNKNOWN** — never mentioned by the publisher. |
| AQ-07 | Is the maintainer's email address recoverable? | **UNKNOWN** — obscured by the page's email-protection mechanism. |

## C. Integrity and coverage gaps

| ID | Question | Status |
|---|---|---|
| AQ-08 | Is `LCL-FullData.zip`'s payload intact? | **UNKNOWN** — its member uses **deflate64**, which Python's `zipfile` cannot decompress, and no `unzip`/`7z`/`bsdtar` is installed. Its container and central directory are readable. Needs `p7zip-full`. |
| AQ-09 | Do all 168 members hold exactly 1,000,000 rows? | **INFERRED** — measured in 5 members; corroborated by Phase B byte arithmetic to within 0.02 bytes/row. |
| AQ-10 | Is the archive total 167,932,474 rows? | **INFERRED** from AQ-09, not counted. |
| AQ-11 | Are the two archives the same underlying data? | **INFERRED** — the 49-byte header prediction held exactly, which is necessary but not sufficient. A content comparison is blocked by AQ-08. |
| AQ-12 | Is `household + timestamp` unique **archive-wide**? | **UNKNOWN** — and harder than it looks, because households straddle member boundaries (VF-16), so the check must union adjacent members. |
| AQ-13 | Are all 168 members uniform at **row level**? | **UNKNOWN** — the header census is archive-wide, but row-level sampling covered 5 members and roughly 0.03% of rows. |
| AQ-14 | What is the file **encoding**? | **UNKNOWN** — member 0 is VERIFIED ASCII-compatible (VF-38), but ASCII is a subset of UTF-8, Latin-1 and Windows-1252 alike. The other 167 members are unscanned. |
| AQ-15 | Do other missing-value tokens (`NULL`, `null`, `NA`, empty) exist elsewhere? | **UNKNOWN** — not observed within the scope examined, which is not evidence of absence. |

## D. Meaning — deliberately not interpreted

REP-001 §§6 and 9 forbid attributing a cause without evidence. Each of these is an observation whose
explanation is unknown.

| ID | Question | Status |
|---|---|---|
| AQ-16 | Why do 45,538 zero readings occur, and what does a zero mean? | **UNKNOWN** — not to be treated as "no usage" or as missing. |
| AQ-17 | Why do zero rates vary from 0.0% to 76.7% between neighbouring households? | **UNKNOWN** — pooled zero statistics would be meaningless until this is understood. |
| AQ-18 | Why do all `Null` rows sit off the half-hour grid, clustered on 2012-12-19? | **UNKNOWN** — the co-occurrence is verified (VF-30); the cause is not. A meter-commissioning explanation is plausible and unproven. |
| AQ-19 | Why do 688 exact duplicates occur, all at `00:00:00`, across 25 dates at roughly monthly spacing? | **UNKNOWN** — a DST explanation was considered and does not fit a monthly pattern, but the actual cause is unestablished. |
| AQ-20 | What causes absent intervals, and how many are genuine? | **UNKNOWN** — absence counts are **upper bounds** while AQ-01 is open, since local-time DST would inflate them. |
| AQ-21 | Is a leading run of zeros ending at a gap a meter-commissioning signature? | **INFERRED, untested** — observed in one household; the falsifying test is to check other households. |

## E. Tariff-group semantics

| ID | Question | Status |
|---|---|---|
| AQ-22 | Does `stdorToU` determine the tariff applicable to a given reading? | **UNKNOWN** — it is a per-household group label. The dToU tariff ran only in 2013 (VF-44) while data spans Nov 2011 – Feb 2014, so a `ToU` household's 2012 readings carry the label but predate the tariff. |
| AQ-23 | Is `stdorToU` fixed per household, or can it vary over time? | **UNKNOWN** — every observation so far is constant within a household, but this has not been tested at archive scale. |
| AQ-24 | Is the `ToU` block the ~1,100-customer dToU cohort? | **INFERRED** — 33/168 members = 19.6% against the page's ~1,100/5,567 = 19.8%. Households in the block have not been counted. |
| AQ-25 | Should the ~4,500 non-dToU households be treated as a control group? | **INFERRED at best** — the publisher never uses the term (VF-46), and all 5,567 were recruited as one balanced sample. Treating them as a comparison baseline is an analytical choice to argue, not a fact to inherit. |

## F. Standing assumptions we are proceeding on

| ID | Assumption | Why it is safe to proceed, and how it is withdrawn |
|---|---|---|
| AS-01 | The documented unit (kWh per half hour) is the source contract | If reality differs, that is a publisher defect. Withdrawn by evidence of a different unit; nothing downstream is stored in converted form. |
| AS-02 | Timestamps are stored and parsed **naively**, with no timezone attached | Never bakes a guess into stored data. Withdrawn by setting a configuration value and re-deriving. |
| AS-03 | One physical line equals one logical record **for member 0 only** | Measured (VF-40), not assumed. The profiler reports the check as failing when it does not hold. |
| AS-04 | Rows may be quarantined but never dropped, coerced or filled | Preserves the ability to correct. Withdrawn only by an explicit handling-policy ticket. |

## G. Questions for a later ticket

| ID | Question |
|---|---|
| AQ-26 | Do the LCL learning reports A1–A11 (Imperial College London, 2014) contain a data dictionary defining AQ-01 to AQ-03? Not retrieved within Phase G's time box; the most likely remaining source. |
| AQ-27 | What handling policy applies to zeros, `Null`, off-grid rows, duplicates and absent intervals? REP-001 §12 places this out of scope; it needs its own ticket. |
| AQ-28 | Should `data/raw/` be made filesystem read-only? Files are `0644` owned by root, but the directory is user-writable, so files can be renamed or deleted without `sudo`. |
