# REP-001 — Source Data Investigation

| Field | Value |
|---|---|
| Ticket | REP-001 |
| Title | Source data investigation: Low Carbon London smart-meter dataset |
| Type | Investigation / spike (no production code) |
| Status | Not started |
| Owner | Project maintainer |
| Reviewer | Senior data engineer |
| Blocks | All later consumption, billing, correction and reconciliation work |
| Related outputs | `docs/source-data-profile.md`, machine-readable profiling result, verified-facts list, assumptions/open-questions list |

> **Nature of this ticket.** This is *requirements and investigation planning only*. It defines
> what evidence we must gather before we trust the source. It does **not** authorise writing
> Python or SQL, downloading data, or building models. Implementation of the investigation is a
> separate, later step (see "Smallest safe first implementation step").

---

## 0. Statements we are treating as UNVERIFIED

The following come from the project brief and the dataset landing page description. They are
**claims to be checked by this investigation**, not established facts. Nothing below may be
repeated elsewhere as verified until this ticket confirms it with evidence.

- Publisher is UK Power Networks, distributed via the London Datastore.
- Dataset page:
  `https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d`
- The archive contains approximately 168 compressed files.
- Each file contains on the order of one million CSV rows.
- A separate tariff workbook is provided.
- The licence is a Creative Commons Attribution licence.
- Readings are half-hourly.
- The consumption unit is kWh per half-hour.
- A literal token such as `Null` is used for absent readings.
- Households are identified by a code such as `LCLid`.

Every one of these must end up in either the **verified facts** list or the
**assumptions / open questions** list by the time the investigation is done.

---

## 1. Business context

The whole project answers one question: *what did we calculate at the time, what would we
calculate now, and can we explain every difference?* Billing and reconciliation numbers are only
as trustworthy as the raw readings they are built from. If we misread the source, every
downstream figure is wrong in a way that is hard to detect later because the pipeline will still
"run".

Concrete ways a wrong assumption here causes wrong money later:

- **Timestamps.** If we assume the wrong interval length, the wrong timezone, or the wrong
  meaning of a timestamp (interval start vs interval end), we can shift or double-count energy
  around midnight, month boundaries and daylight-saving changes. A half-hour placed in the wrong
  billing period moves revenue between periods and between tariff rates.
- **Units.** If the values are not what we assume (for example Wh vs kWh, or cumulative register
  reads vs per-interval consumption), totals are off by a large factor or are nonsensical.
  Multiplying the wrong unit by a tariff rate produces a confidently wrong bill.
- **Missing readings.** If we treat a gap as zero consumption, we under-bill a customer who was
  actually using energy but whose meter did not report. If we treat it as an error and drop the
  household, we lose real usage. The correct handling depends on *why* the reading is missing,
  which we do not yet know.
- **Duplicate records.** If the same interval appears twice and we sum naively, we over-bill. If
  two rows share a key but disagree on the value, picking the wrong one changes the bill and we
  have no audit trail explaining the choice.

We inspect evidence now so that later modelling decisions are defensible and every difference
between "then" and "now" can be traced to a documented cause.

---

## 2. Scope

**Start with exactly one CSV file** taken from the official multi-file archive. Do not begin
profiling until provenance (section 3) is recorded for that file.

### 2a. Checks that are meaningful on the first file alone

- File format, encoding, delimiter.
- Header names exactly as supplied.
- Raw line count vs successfully parsed row count.
- Malformed / rejected rows within that file.
- Repeated header lines inside that file.
- Column-level profiling for that file's rows.
- Numeric parsing success/failure for the consumption column in that file.
- Min / max / distribution of consumption values in that file.
- Zero and negative values in that file.
- Observed timestamp format, earliest/latest timestamp, and interval frequency in that file.
- Exact duplicate rows within that file.
- Duplicate candidate keys within that file.
- Conflicting duplicates within that file.
- Missing intervals for households that appear in that file (internal gaps vs edges).

### 2b. Checks that require more than one file, or the whole archive

- Whether the household identifier is unique across files or repeats across files (a household's
  readings may be split across multiple files).
- Whether the candidate key `household_id + timestamp` is unique across the **whole** archive,
  not just one file.
- True earliest and latest timestamp for the dataset, and the full observation window per
  household.
- Whether headers, encoding, delimiter and column set are identical in every file.
- Whether value ranges, null-token usage and formats are consistent across files.
- Total row count reconciliation for the archive.
- Cross-file duplicates and cross-file conflicting duplicates.

### 2c. Explicitly out of this ticket

See section 12.

---

## 3. Source provenance

Before any profiling, record the following and store it with the profiling outputs. Values that
cannot be determined must be written as `UNKNOWN`, not guessed.

- **Publisher** — organisation named on the dataset page.
- **Official dataset page** — full URL, plus the date the page was viewed.
- **Licence** — exact licence name and version as stated on the page, link to the licence text,
  and the **exact attribution string** the licence requires us to display.
- **Downloaded filename** — the archive filename exactly as delivered.
- **Download date** — date (and time if available) the file was retrieved.
- **File sizes** — compressed archive size in bytes, and extracted size in bytes (total, and for
  the single CSV chosen).
- **SHA-256 checksum** — of the downloaded archive, and of the single extracted CSV used.
- **Modification status** — explicit statement of whether the file was altered after download
  (it must not be); record the command used to verify and where the untouched original is kept.

The raw download and these provenance records are kept read-only and are never edited in place.

---

## 4. File-level inspection

For the one chosen CSV, gather and record:

- **Format, encoding and delimiter** — confirmed by inspection, not assumed. Record the detected
  encoding (e.g. UTF-8, UTF-8 with BOM, Latin-1) and the field delimiter, with the evidence used
  to determine each.
- **Header** — the first line reproduced verbatim, including exact spelling, casing, spaces,
  punctuation and column order.
- **Raw line count** — total physical lines in the file.
- **Parsed row count** — number of data rows a parser accepts under a strict configuration.
- **Malformed / rejected rows** — count and a sample of raw examples, with the reason each was
  rejected (wrong field count, unescaped quote, encoding error, etc.).
- **Repeated headers** — whether the header line appears again anywhere inside the file, and if
  so where and how many times.
- **Representative raw values** — a small sample of raw lines copied exactly as they appear, with
  no trimming, type coercion or reformatting, so the reader can see the true shape of the data.

All counts must be explainable: `raw lines = header line(s) + parsed rows + rejected rows`.

---

## 5. Column-level profiling

For **every** column in the file, record:

- **Documented meaning** — what the column represents, citing the source documentation or dataset
  page. If no authoritative definition exists, mark the meaning `UNKNOWN` and add an open
  question — do not invent one.
- **Observed example values** — a handful of real values seen in the data.
- **Inferred type** — the type the values appear to be (string, integer, decimal, timestamp,
  categorical), clearly labelled as *inferred from observation*, not declared by the source.
- **Null values and non-standard null tokens** — count of truly empty fields, plus counts of any
  placeholder tokens such as `Null`, `NULL`, `null`, `NA`, `N/A`, `-`, whitespace-only. List each
  distinct token separately with its count.
- **Invalid values** — values that do not fit the inferred type or documented domain (e.g.
  non-numeric text in a numeric column, out-of-range categories), with counts and examples.
- **Distinct count** — where it is informative (identifiers, categorical flags, timestamp
  values); note whether the count is over the one file or a wider set.

---

## 6. Consumption checks

For the column believed to hold energy consumption:

- **Numeric parsing** — count of values that parse as a number and count that fail, with examples
  of the failures (including how null tokens like `Null` behave).
- **Distribution summary** — minimum, maximum, and a description of the spread (e.g. quantiles or
  a histogram description). Note the most extreme values individually.
- **Zero values** — how many readings are exactly zero, and where they occur.
- **Negative values** — how many readings are below zero, with examples. Do not decide yet what a
  negative value means; record it as an open question.
- **Unit confirmation** — the unit must be taken from authoritative source documentation and
  quoted with a citation. Until such a citation exists, the unit is `UNKNOWN`. Plausibility of
  the observed range may be *noted* but does not confirm the unit.
- **Missing ≠ zero** — this ticket explicitly forbids treating an absent reading as zero
  consumption. Absent readings are counted and characterised, never filled.

---

## 7. Timestamp checks

For the column believed to hold the reading time:

- **Observed format** — the exact string format(s) seen (e.g. `YYYY-MM-DD HH:MM:SS`), with real
  examples. List every distinct format found.
- **Earliest and latest timestamp** — in this file (and noted as file-scoped, since the archive
  range is wider).
- **Interval frequency** — the spacing between consecutive readings for a household, and whether
  it is consistent (e.g. every 30 minutes) or varies.
- **Timezone evidence** — any statement in the source documentation about timezone or local-time
  convention, quoted with a citation. Also note indirect evidence (e.g. behaviour around known
  daylight-saving change dates) but label it as indirect.
- **Timezone status** — recorded as `UNKNOWN` until authoritative evidence confirms it. No
  guess, no "probably UTC", no "probably London local".
- **No conversion** — this ticket performs **no** timezone conversion, normalisation or shifting
  of timestamps. Values are read and reported as-is.
- **Daylight-saving transitions** — investigation of DST behaviour (missing or doubled hours in
  spring/autumn) happens **only after** the source's timezone convention is known. Note the
  relevant UK DST change dates for later, but do not analyse them yet.
- **Timestamp semantics** — whether a timestamp marks the start or the end of its interval is
  `UNKNOWN` until the documentation says so; this affects section 9.

---

## 8. Duplicate checks

Keep these three questions separate and report them separately.

1. **Exact duplicate rows** — rows where every field is identical to another row. Count them and
   show examples. These are usually safe to collapse, but we only *count* them here.
2. **Duplicate candidate keys** — rows where `household_id + timestamp` matches another row,
   regardless of whether the other fields agree. Count the number of key collisions and the
   number of rows involved.
3. **Conflicting duplicates** — the subset of (2) where the candidate key matches but at least
   one other field (typically the consumption value) differs. These are the dangerous ones: they
   mean the source disagrees with itself and a later model must choose. Count them, show
   examples, and record what differs.

**Do not conclude that the candidate key is valid** just because it looks unique in one file.
Key validity must be re-tested across multiple files and across the whole archive (section 2b)
before any model relies on it.

---

## 9. Missing-interval checks

- **Per household** — gap analysis is done separately for each household identifier, never
  pooled across households.
- **Internal gaps vs edges** — distinguish:
  - *internal missing intervals*: gaps that fall between a household's first and last observed
    reading;
  - *edge periods*: time before a household's first reading or after its last reading, which is
    absence of observation, not a gap in service.
  These are counted separately and never merged.
- **Expected interval count** — computed only from *documented* timestamp semantics (interval
  length, and whether timestamps are interval start or end). If those semantics are still
  `UNKNOWN`, the expected count is also `UNKNOWN` and the check is deferred, not approximated.
- **Cause of missingness** — recorded as `UNKNOWN` for every gap unless there is specific
  supporting evidence (e.g. source documentation describing meter dropouts, or a documented
  collection outage). No gap is labelled "meter off" or "customer away" or "zero usage" without
  evidence.

---

## 10. Outputs

The eventual investigation (not this ticket) must produce all of the following:

- **`docs/source-data-profile.md`** — a human-readable narrative profile covering every section
  above, with the numbers, the commands used, and citations to source documentation.
- **A machine-readable profiling result** — a structured file (for example JSON) containing the
  per-column and per-check counts, so results can be compared and re-checked programmatically.
- **A verified-facts list** — statements we can defend with a command output, a query result, or
  a quotation from authoritative source documentation. Each fact carries its evidence.
- **A separate assumptions / open-questions list** — everything we believe but have not proven,
  everything marked `UNKNOWN`, and every question a later ticket must answer.
- **Enough evidence to make a go / no-go decision** on whether billing transformations can
  safely begin, or a clear statement of what is still missing before that decision can be made.

Raw input is preserved unchanged alongside these outputs.

---

## 11. Acceptance criteria

Objective, testable. The ticket is done only when all of these hold.

1. **Reproducible from a clean environment.** Someone with no prior state can follow the written
   steps — download, checksum, extract, profile — and obtain the same counts and the same
   profile. The steps and commands are written down, not implied.
2. **Raw input preserved.** The downloaded archive and the extracted CSV used are stored
   read-only, their SHA-256 checksums are recorded, and it is demonstrated that the working copy
   matches the original.
3. **No unsupported assumptions.** The outputs contain no timezone claim, no unit claim, no
   billing-semantics claim, and no missingness-cause claim that is not backed by a citation or
   evidence. Anything unproven is in the assumptions list and/or marked `UNKNOWN`.
4. **Counts reconcile end to end.** For the chosen file:
   `raw lines → parsed rows → accepted rows → rejected rows` all tie out, and the arithmetic is
   shown. Duplicate and null counts are consistent between the narrative and the machine-readable
   result.
5. **Every finding is supported.** Each statement in the profile is backed by a command, a query
   result, or a quotation from authoritative source documentation. No unsourced assertions.
6. **Both output lists exist and are non-overlapping.** The verified-facts list and the
   assumptions/open-questions list are both present, and no statement appears as both.
7. **Provenance complete.** Every field in section 3 is filled with a real value or an explicit
   `UNKNOWN`.
8. **Scope respected.** No billing, tariff, dbt, Airflow, Spark or dashboard work appears in the
   outputs (section 12).

---

## 12. Out of scope

The following are explicitly excluded from REP-001 and must not appear in its outputs:

- Billing calculations of any kind.
- Joining consumption to tariff data (the tariff workbook is noted for provenance only, not
  processed).
- Simulating register reads / meter register logic.
- dbt models or dbt project setup.
- Airflow DAGs or scheduling.
- Spark usage or performance tuning.
- Dashboards or visualisation tooling.
- Deciding *how* to handle nulls, duplicates or gaps — this ticket only measures and describes
  them.

---

## 13. Understanding checkpoints

Before writing any investigation code, the maintainer should be able to explain, in plain language
and in their own words:

1. **Why raw data is preserved.** Why do we keep an untouched, read-only copy of the original
   download, and why is a checksum useful?
2. **Null vs zero.** What is the difference between "we have no reading for this half-hour" and
   "the reading for this half-hour is 0.000 kWh"? Why does it matter for a bill?
3. **Exact duplicate vs duplicate candidate key.** What is the difference between two rows that
   are identical in every field, and two rows that only share the same household and timestamp
   but disagree elsewhere? Why is the second case more dangerous?
4. **Missing interval ≠ zero usage.** Why can we not simply fill a gap with 0? What would we need
   to know first?
5. **Why timezone evidence is required before conversion.** What could go wrong if we assume the
   timestamps are UTC (or London local) and convert them, and we are wrong?

The reviewer checks these answers before implementation begins. Working code is not evidence of
understanding.

---

## Definition of Done

- One CSV file from the official archive has been fully profiled through sections 4–9.
- `docs/source-data-profile.md` and the machine-readable profiling result both exist and agree.
- The verified-facts list and the assumptions/open-questions list both exist and are
  non-overlapping.
- Section 3 provenance is complete (real values or explicit `UNKNOWN`).
- All section 11 acceptance criteria are met and have been checked by the reviewer.
- The maintainer has explained the five section 13 checkpoints to the reviewer's satisfaction.
- A written go / no-go recommendation on starting billing transformations exists, with its
  reasoning and its list of blockers.
- The project status record is updated to reflect the new status (done as a separate step, not
  inside this ticket).

## Unresolved questions (to be carried into the investigation)

- Which single file from the archive do we choose, and does the choice bias any finding?
- What authoritative documentation exists for column meanings, units and timestamp semantics,
  and where does it live (dataset page, linked report, academic publication)?
- Are timestamps interval-start or interval-end?
- What is the timezone / local-time convention, and is DST represented in the raw timestamps?
- Is the consumption unit kWh per half-hour, and is it per-interval consumption rather than a
  cumulative register value?
- Is the household identifier stable and unique across the whole archive?
- Is `household_id + timestamp` actually a valid unique key across the whole archive?
- What does a negative consumption value mean, if any occur?
- What does the source say, if anything, about why readings are missing?
- Are all 168 files structurally identical (header, encoding, delimiter, columns)?
- What exact attribution string does the licence require, and where must we display it?

## Smallest safe first implementation step

Do **not** download the archive yet. The first implementation step is:

> Open the official dataset page, and write down — into a new `docs/source-data-profile.md`
> under a "Provenance (in progress)" heading — the publisher, the exact licence name and
> version, the exact required attribution string, the dataset page URL, and the date viewed.
> Quote the page; do not paraphrase the licence. Add every claim from section 0 that the page
> does **not** explicitly confirm to the assumptions/open-questions list.

This step touches no data, runs no code, and is fully reversible. It is planned and reviewed
before the next step (choosing and checksumming a single file) begins.

---

*Ticket REP-001. Investigation planning only — implementation is a separate, later step.*
