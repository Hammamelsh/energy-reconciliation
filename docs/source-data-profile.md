# Source Data Profile — Low Carbon London Smart-Meter Dataset

**Ticket:** REP-001 — Source Data Investigation
**Phases recorded here:**
  - **A** — Source provenance and licence verification (page evidence only), 2026-09-06 — sections 1-8
  - **B** — Raw-file inventory and archive validation (file metadata only), 2026-09-07 — section 9
  - **C** — First CSV member: header and 20-record sample, 2026-09-07 — section 10
  - **D** — Bounded non-zero consumption window, 2026-09-07 — section 11
  - **E** — Zeros, missing tokens and absent intervals across households, 2026-09-07 — section 12
  - **F** — Structural consistency across all 168 members, 2026-09-07 — section 13
  - **G** — Authoritative documentation research (time-boxed), 2026-09-07 — section 14
**Official page:** https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d
**Access date (page):** 2026-09-06
**Method:** Phase A was an automated fetch of the official dataset page above. Phase B measured the
downloaded files' metadata and archive structure. Phase C read the header and the first 20 data
records of one CSV member, streamed from the archive. **No workbook cell has been read, no file has
been extracted, and no whole-file profiling has been performed**, at any point.

---

## How to read this document

Every statement carries one of three labels. This separation is the point of the document —
it is what stops a plausible-sounding claim from being treated as an established fact later.

| Label | Meaning |
|---|---|
| **VERIFIED** | Stated on the official page, quoted here. Evidence is the quotation plus the page URL. |
| **UNVERIFIED** | Not confirmed from the page as displayed text. Must be confirmed before use. |
| **INFERRED** | Derived by reasoning from VERIFIED items. Reasoning shown. Not a source statement. |
| **CONTRADICTED** | Measurement disagrees with a claim made by the source. Both values shown. |
| **PUBLISHER-DOCUMENTED** | Stated by the publisher in authoritative documentation, quoted with a citation. Accepted as the source contract; not independently measured by us. |
| **UNKNOWN** | Cannot be answered from the page at all; requires inspecting downloaded files. |

Nothing in this document was taken from prior knowledge of this dataset. Where the page is
silent, this document says so rather than filling the gap.

---

## 1. Dataset identity

| Item | Value | Label |
|---|---|---|
| Exact dataset title | "SmartMeter Energy Consumption Data in London Households" | VERIFIED |
| Publisher | UK Power Networks | VERIFIED |
| Author | UK Power Networks | VERIFIED |
| Maintainer | UK Power Networks | VERIFIED |
| Maintainer email | Obscured on the page by an email-protection mechanism; the address was not retrievable from the fetched content | UNVERIFIED |
| Official page URL | https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d | VERIFIED |
| Tags shown | `#2013`, `#electricity`, `#power`, `#energy` | VERIFIED |
| Last update | Displayed as a relative date, "over 4 years ago" — no absolute date shown | VERIFIED (as displayed) |
| Update frequency | NOT STATED ON PAGE | UNKNOWN |

**Note on "last update":** the page shows a relative date only. The absolute date of the last
update is therefore UNKNOWN, and a relative date recorded today becomes misleading later. If an
absolute date is needed, it must be obtained another way.

---

## 2. Dataset description — verbatim

The following is the description text as displayed on the official page, reproduced exactly,
including the original spelling (the misspelling "availaible" is in the source):

> "Energy consumption readings for a sample of 5,567 London Households that took part in the UK
> Power Networks led Low Carbon London project between November 2011 and February 2014. Readings
> were taken at half hourly intervals. The customers in the trial were recruited as a balanced
> sample representative of the Greater London population. The dataset contains energy
> consumption, in kWh (per half hour), unique household identifier, date and time. The CSV file
> is around 10GB when unzipped and contains around 167million rows."

> "Within the data set are two groups of customers. The first is a sub-group, of approximately
> 1100 customers, who were subjected to Dynamic Time of Use (dToU) energy prices throughout the
> 2013 calendar year period. The tariff prices were given a day ahead via the Smart Meter IHD (In
> Home Display) or text message to mobile phone. Customers were issued High (67.20p/kWh), Low
> (3.99p/kWh) or normal (11.76p/kWh) price signals and the times of day these applied. The
> dates/times and the price signal schedule is availaible as part of this dataset. All
> non-Time of Use customers were on a flat rate tariff of 14.228pence/kWh. The remaining sample
> of approximately 4500 customers energy consumption readings were not subject to the dToU
> tariff."

Evidence: official page, accessed 2026-09-06.

---

## 3. Facts stated by the publisher

All items below are **VERIFIED** — each is stated on the official page and quoted in section 2.

| Item | Stated value | Exact supporting wording |
|---|---|---|
| Households in sample | 5,567 | "a sample of 5,567 London Households" |
| Coverage period | November 2011 to February 2014 | "between November 2011 and February 2014" |
| Reading frequency | Half-hourly | "Readings were taken at half hourly intervals" |
| Consumption unit | kWh per half hour | "energy consumption, in kWh (per half hour)" |
| Fields described | Energy consumption, unique household identifier, date and time | "energy consumption, in kWh (per half hour), unique household identifier, date and time" |
| Total row count | Approximately 167 million | "contains around 167million rows" |
| Uncompressed size | Around 10 GB | "The CSV file is around 10GB when unzipped" |
| Sampling basis | Balanced sample representative of Greater London | "recruited as a balanced sample representative of the Greater London population" |
| Project | UK Power Networks led Low Carbon London project | "the UK Power Networks led Low Carbon London project" |

**Important qualifier:** the page describes the *fields* as "energy consumption, unique household
identifier, date and time". It does **not** give the exact column header names, their spelling, or
their order. Those remain UNKNOWN (section 7).

---

## 4. Downloadable resources

Resource names, formats, sizes and descriptions as displayed. **VERIFIED.**

| Resource name (as displayed) | Format | Size | Description (as displayed) |
|---|---|---|---|
| `low-carbon-london-data` | ZIP | 764.54 MB | "Very large dataset (CSV). 167million rows of data." |
| `low-carbon-london-data-168-files` | ZIP | 758.86 MB | "Same data as in other Zip file but split into 168 separate CSV files" |
| `Tariffs` | XLSX | 239.63 kB | "Time of Use Tariffs for 2013" |

### Split-file count

- **168 separate CSV files** — **VERIFIED.** Supporting wording: "Same data as in other Zip file
  but split into 168 separate CSV files".

### Rows per split file

- **"Approximately one million rows per file"** — **UNVERIFIED.** The page extraction reported a
  phrase "each containing 1 million rows", but that phrase was not returned as a complete quoted
  sentence in its page context, so this profile does not treat it as displayed page text. Confirm
  by viewing the page directly before relying on it.
- **INFERRED alternative:** 167,000,000 ÷ 168 ≈ **994,048 rows per file**, if rows were split
  evenly. This is arithmetic from two VERIFIED figures, not a publisher statement. The publisher's
  own row count is itself approximate ("around 167million"), so this figure is approximate twice
  over and must not be used as an expected count for reconciliation.

> **CORRECTED BY MEASUREMENT IN PHASE F (section 13.5).** The split is **exactly 1,000,000 rows per
> file**, with the remainder (932,474) in the final member — measured in members 0, 4, 5, 135 and
> 167. The "approximately one million rows" phrasing is therefore **VERIFIED**, and the 994,048
> even-split inference above was **wrong by 5,952 rows per file**. It was correctly labelled
> INFERRED and correctly flagged as unusable as an expected count; this is what that caution was
> for. Inferred archive total: **167,932,474 rows**.

**Consequence for REP-001:** the actual row count of any downloaded file must be measured, not
assumed. The page figures serve only as a sanity check on the order of magnitude.

---

## 5. Tariff information

**VERIFIED** — all figures quoted from the page text in section 2.

| Group | Approx. customers | Tariff structure | Published rates (as written) |
|---|---|---|---|
| dToU (Dynamic Time of Use) | ~1,100 | Day-ahead dynamic price signals during the 2013 calendar year | High **67.20p/kWh**, Low **3.99p/kWh**, normal **11.76p/kWh** |
| Remaining non-dToU sample | ~4,500 | Flat rate | **14.228pence/kWh** |

Additional VERIFIED points:

- Price signals were delivered "a day ahead via the Smart Meter IHD (In Home Display) or text
  message to mobile phone".
- The dToU period is stated as "throughout the 2013 calendar year period" — narrower than the
  full dataset coverage of November 2011 to February 2014.
- The page states "The dates/times and the price signal schedule is availaible as part of this
  dataset", which corresponds to the `Tariffs` XLSX resource.
- 1,100 + 4,500 = 5,600, which does not equal the stated 5,567 households. The page uses
  "approximately" for both group figures, so this is consistent with rounding, but it means
  **group sizes must not be used as exact counts**. INFERRED observation, flagged here so it is
  not mistaken for a data-quality defect later.
- **Terminology — "control group" is NOT the publisher's word. INFERRED.** The page says only that
  "The remaining sample of approximately 4500 customers energy consumption readings were not subject
  to the dToU tariff." It never states that these households were assigned to a non-treatment arm;
  the whole 5,567 was recruited as one "balanced sample representative of the Greater London
  population", not as treatment and control arms. Calling them a control group would import an
  experimental-design claim the page does not make, so this profile calls them the **remaining
  non-dToU sample**. Checked against the full page on 2026-09-06: the words "control", "controlled",
  "control group", "baseline group" and "comparison group" do not appear anywhere on it — **VERIFIED
  absence**, checked explicitly. If a later analysis wants to treat this group as a comparison
  baseline, that is an analytical choice to be argued and labelled INFERRED at that point, not a
  fact inherited from the source.

**Not done in this phase:** no tariff has been joined to consumption, and no charge has been
calculated. That is explicitly out of scope for REP-001 (ticket section 12).

---

## 6. Licence and attribution

### Licence as displayed

> "Creative Commons Attribution"

**VERIFIED** as the exact wording displayed. Additional findings:

- **No version number is displayed as text** on the page. A linked Creative Commons logo appears
  below the label.
- The licence version is therefore **UNKNOWN**. This profile does **not** infer 4.0, 3.0, or any
  other version. Determining the version requires following the linked logo to the licence deed
  and recording where that link points — a separate verification step, not done here.

> **RESOLVED IN PHASE G (section 14.5): the licence is CC BY 4.0. VERIFIED.** The verification step
> described above was carried out on 2026-09-07: the page's licence link points to
> `https://creativecommons.org/licenses/by/4.0/`, whose deed is titled **"Attribution 4.0
> International"**, canonical identifier **CC BY 4.0**. The version was resolved by following the
> link, exactly as this paragraph required — not by inference.
>
> It was also confirmed that the link belongs to **this dataset's own Licence metadata field** and
> not to site chrome: the URL appears only in that field, positioned between the resource list and
> `Last Update`, and no site-wide footer on the page links to creativecommons.org. See 14.5 for the
> check. Without that confirmation the version could have belonged to the site rather than the
> dataset, and the conclusion would not stand.

### Required attribution wording

- **NOT STATED ON PAGE.** No "how to cite", "attribution", "acknowledgement" or "terms of use"
  wording was found. **VERIFIED absence on this page** — checked explicitly. Scoped to the dataset
  page; other publisher documentation was not searched for attribution wording.
- Because a Creative Commons Attribution licence requires attribution but the publisher supplies
  no mandated sentence, we must compose one. It carries no official status.

### PROPOSED attribution (not official — our own wording)

> Contains data from *SmartMeter Energy Consumption Data in London Households*, published by UK
> Power Networks via the London Datastore, licensed under a Creative Commons Attribution licence.
> Accessed 2026-09-06 from
> https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d

**Status: PROPOSED.** This sentence was written by us, not supplied by the publisher.

> **UPDATED IN PHASE G:** the licence version is now VERIFIED as **CC BY 4.0**, so the omission this
> paragraph flagged can be closed. Revised proposed wording:
>
> > Contains data from *SmartMeter Energy Consumption Data in London Households*, published by UK
> > Power Networks via the London Datastore, licensed under the Creative Commons Attribution 4.0
> > International licence (CC BY 4.0). Accessed 2026-09-06 from
> > https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d
>
> Still **PROPOSED**: the publisher supplies no mandated attribution sentence (VERIFIED absence
> above), so this remains our own wording and carries no official status.

---

## 7. Remaining unknowns — require inspecting downloaded files

None of the following can be answered from the official page. Each is **UNKNOWN** and must stay
that way until actual file contents are inspected under a later phase of REP-001.

### Structural unknowns

| Item | Status | Why the page cannot answer it |
|---|---|---|
| File encoding (UTF-8, BOM, Latin-1, …) | UNKNOWN | Not described anywhere on the page |
| Field delimiter | UNKNOWN | "CSV" implies a comma by convention but is not a guarantee |
| Exact column header names and spelling | UNKNOWN | Page describes fields in prose, never the header line |
| Column order | UNKNOWN | Not stated |
| Whether headers repeat inside a file | UNKNOWN | Requires reading the file |
| Whether all 168 files share one structure | UNKNOWN | Requires reading multiple files |

> **Update 2026-09-07:** Phase C (section 10) closed the delimiter, header spelling and column
> order **for one file only**, and partly closed encoding. **Phase F (section 13.2) then censused
> all 168 members and closed delimiter, header spelling, column order, line endings and
> "whether all 168 files share one structure" ARCHIVE-WIDE.** Encoding remains partly open: headers
> and first rows are ASCII in all 168, but the bodies have never been scanned for bytes >= 0x80.
> The Phase A statements in this table are left unchanged as the record of what the *page* could
> not answer.

### Value-level unknowns

| Item | Status | Why the page cannot answer it |
|---|---|---|
| Null representation (empty field, `Null`, `NA`, …) | UNKNOWN | Not mentioned |
| Presence and meaning of zero readings | UNKNOWN | Not mentioned |
| Presence and meaning of negative readings | UNKNOWN | Not mentioned |
| Exact duplicate rows | UNKNOWN | Requires reading the data |
| Duplicate candidate keys (household + timestamp) | UNKNOWN | Requires reading the data |
| Conflicting duplicates | UNKNOWN | Requires reading the data |
| Whether household id + timestamp is a valid unique key | UNKNOWN | Requires whole-archive checking |
| Actual row count per file | UNKNOWN | Page gives only an approximate total |

### Time-related unknowns — deliberately left open

| Item | Status | Note |
|---|---|---|
| Timestamp timezone convention | **UNKNOWN** | The page makes no timezone statement. No guess is recorded, and no conversion will be performed. |
| Whether a timestamp marks interval **start** or **end** | **UNKNOWN** | The page does not say. This blocks expected-interval arithmetic in ticket section 9. |
| Observed timestamp string format | UNKNOWN | Requires reading the data |
| Daylight-saving behaviour (missing / doubled hours) | UNKNOWN | Ticket section 7 forbids investigating this until the timezone convention is known |

### Missingness unknowns

| Item | Status | Note |
|---|---|---|
| Whether readings are missing at all | UNKNOWN | Requires reading the data |
| Cause of any missing readings | **UNKNOWN** | The page offers no explanation. No gap may be labelled "meter off", "customer away" or "zero usage" without evidence. |
| Whether a missing reading means zero consumption | **UNKNOWN — and assumed NOT to** | Ticket section 6 forbids treating absence as zero. |

**All of the above require inspecting the downloaded files.** They cannot be resolved by reading
the dataset page again.

---

## 8. Phase A summary

**Completed:** provenance and licence evidence has been recorded from the official page, with
every statement labelled and quoted.

**What we now know with evidence:** publisher, author, maintainer, title, coverage period,
half-hourly frequency, kWh-per-half-hour unit, approximate 167 million row total, the three
downloadable resources with names/formats/sizes/descriptions, the 168-file split, both tariff
groups with their published rates, and the licence label.

**What we do not know:** the licence version, the maintainer's email address, any official
attribution wording, the true rows-per-file figure, and every structural, value-level, temporal
and missingness property of the actual data.

**Decision on proceeding to billing work:** not yet possible, and not close. Two unknowns alone —
the timezone convention and whether a timestamp marks interval start or end — are sufficient to
block any correct billing transformation, and neither can be resolved from the page.

**Next step:** acquire the official files and record their integrity metadata (downloaded
filename, download date, compressed and extracted sizes, SHA-256 checksum, and confirmation the
file was not modified), per ticket section 3.

---

*Phase A of REP-001. Evidence source: the official dataset page only, accessed 2026-09-06.
No dataset files downloaded. No file contents inspected. No code written.*

---

## 9. Phase B — raw file inventory and archive validation

**Phase:** B — raw-file inventory, integrity and archive structure.
**Date performed:** 2026-09-07. **Scope:** files directly inside `data/raw/` only.
**Boundary respected:** no raw file was altered, renamed, extracted or deleted; no CSV row was
read or parsed; the tariff workbook was not loaded as a workbook. Archive members were streamed
through a checksum function in memory and discarded — nothing was written to disk.

Machine-readable companion: [`data/manifests/raw-file-manifest.csv`](../data/manifests/raw-file-manifest.csv).

### 9.1 Commands used

```bash
# discovery, metadata, fingerprints
find data/raw -maxdepth 1 -type f
stat -c '%n|%s|%Y|%i|%a' data/raw/*        # size, mtime, inode, mode (before AND after)
file -b data/raw/*                          # type from magic bytes, not from the extension
sha256sum data/raw/*

# archive structure — central directory metadata only, no extraction
python3 -c 'import zipfile; zipfile.ZipFile(path).infolist()'

# corruption test — decompress each member in memory, recompute CRC-32, discard bytes
python3 -c 'import zipfile; zipfile.ZipFile(path).testzip()'   # per-member CRC comparison
```
`unzip`, `zipinfo`, `7z`, `7za`, `p7zip` and `bsdtar` are **all absent from this machine**
(checked with `command -v`). Every archive operation therefore used the Python standard-library
`zipfile` module. This matters for one result below.

### 9.2 What is actually in `data/raw/`

`find data/raw -type f` returns **6 entries**, not the 3 downloadable resources Phase A
described. The difference is explained, not ignored:

| Entry | Bytes | What it is |
|---|---:|---|
| `LCL-FullData.zip` | 801,674,949 | dataset file |
| `LCL-FullData.zip:Zone.Identifier` | 25 | Windows metadata stream — **not dataset data** |
| `Partitioned LCL Data.zip` | 795,722,689 | dataset file |
| `Partitioned LCL Data.zip:Zone.Identifier` | 25 | Windows metadata stream — **not dataset data** |
| `Tariffs.xlsx` | 245,384 | dataset file |
| `Tariffs.xlsx:Zone.Identifier` | 25 | Windows metadata stream — **not dataset data** |

The three 25-byte `:Zone.Identifier` entries are **NTFS alternate data streams**, which WSL2
surfaces as separate files. Windows attaches one to any file downloaded from the internet; the
mechanism is called **Mark of the Web**. Each contains exactly `[ZoneTransfer]` / `ZoneId=3`,
and all three share one SHA-256 (`b952d24c…`) because their 25 bytes are identical. `ZoneId=3`
means "Internet zone".

- **VERIFIED:** the three dataset files were obtained from an internet download, not created
  locally. Evidence: the Mark-of-the-Web stream exists on each with `ZoneId=3`.
- **UNKNOWN:** *which* URL they came from. These streams carry no `HostUrl` or `ReferrerUrl`
  line, so they do not prove the London Datastore was the source.
- These streams are recorded in the manifest for completeness and marked `NOT-DATASET`. They
  are not part of the dataset and must never be parsed as data.

### 9.3 File identity — measured

| File | Size (bytes) | Modified (UTC) | Detected type (magic bytes) | SHA-256 |
|---|---:|---|---|---|
| `LCL-FullData.zip` | 801,674,949 | 2026-09-06T14:39:52Z | Zip archive data, at least v4.5 to extract, compression method=deflate64 | `68a35598cc8e70898a7651c482216fb096a0a6910c2d180c616632dfc7a9b014` |
| `Partitioned LCL Data.zip` | 795,722,689 | 2026-09-06T14:39:56Z | Zip archive data, at least v2.0 to extract, compression method=deflate | `149a6a9c43c622fd0a14b7d11be055665317d3018d9fb7e1043bd51420bfaea5` |
| `Tariffs.xlsx` | 245,384 | 2026-09-06T14:39:47Z | Microsoft Excel 2007+ | `8a2eff6dcb737aee96cfa6c357d2947604d7f812896405c2ab5f98433d2cb150` |

**VERIFIED:** all three files' declared extensions match their actual detected type. A `.zip`
that was secretly an HTML error page — a common failure when a download is redirected to a login
or error screen — would have been caught here.

**UNKNOWN — the download date.** The modification timestamps above are when these files came to
exist *on this filesystem*, not when they were retrieved from the publisher. A copy, move or
extraction on Windows can rewrite an mtime. Ticket section 3 requires a real download date;
it is **not** satisfied by this evidence and remains `UNKNOWN`.

### 9.4 Archive integrity — corruption test without extraction

Each ZIP member stores a **CRC-32** checksum recorded when the archive was built. Testing
integrity means decompressing each member in memory, recomputing that checksum, and comparing.
Nothing is written to disk. This is a different question from SHA-256: SHA-256 asks *did this
file change since I last measured it*, CRC-32 asks *is this archive internally consistent*.

| Archive | Members tested | CRC matched | Failed | Untestable | Bytes verified | Result |
|---|---:|---:|---:|---:|---:|---|
| `Partitioned LCL Data.zip` | 168 | 168 | 0 | 0 | 8,542,826,421 | **PASSED** |
| `LCL-FullData.zip` | 0 | 0 | 0 | 1 | 0 | **INCOMPLETE** |

**`Partitioned LCL Data.zip` — VERIFIED sound.** All 168 members decompressed and every CRC-32
matched. 8,542,826,421 bytes were verified in 8.8s. That byte
count equals the archive's own declared uncompressed total exactly, so the test covered the
whole archive with nothing skipped.

**`LCL-FullData.zip` — integrity UNKNOWN, and this is a real gap.** Its single member is compressed with
**deflate64**, a variant of the deflate algorithm. Python's `zipfile` recognises the method name
but cannot decompress it (`NotImplementedError: That compression method is not supported`), and
no external tool on this machine can either. The consequence, stated precisely:

- **VERIFIED:** the file is a well-formed ZIP container and its central directory is readable and
  internally consistent (member name, sizes, CRC and offsets all parse).
- **UNKNOWN:** whether the compressed payload is intact. A truncated or corrupted body would
  still present a valid-looking central directory, because that structure sits at the *end* of
  the file and was read successfully.
- **Therefore `LCL-FullData.zip` must not be treated as validated.** Ticket acceptance criterion
  2 is not met for this file. Resolving it needs a deflate64-capable tool (`p7zip-full`).

### 9.5 Partitioned archive — structure

| Property | Measured value |
|---|---|
| Compressed size on disk | 795,722,689 bytes (758.86 MiB) |
| Total **uncompressed** size | 8,542,826,421 bytes (7.96 GiB / 8.54 GB) |
| Entries in archive | 168 |
| File members | 168 |
| CSV members | 168 |
| Non-CSV members | none |
| Nested archives inside | none |
| Directory entries | 0 |
| Compression method(s) | deflate |
| Member uncompressed **min** | 47,441,437 bytes |
| Member uncompressed **median** | 50,884,769 bytes |
| Member uncompressed **max** | 50,962,578 bytes |
| Member timestamps (in-archive) | [2021, 8, 25, 11, 27, 54] to [2021, 8, 25, 11, 32, 28] |

**Naming — VERIFIED.** Every member matches exactly one template:
`Small LCL Data/LCL-June#v#_#.csv` (168 of them). All
members sit under a single internal directory, `Small LCL Data/`. There are **no** subdirectory
trees beyond that one level, no nested archives, and no non-CSV members.

**Numbering reconciles exactly — VERIFIED.** The numeric suffixes are 0 to 167 inclusive, 168
distinct values, **no gaps and no duplicates**. First three by numeric index:
`LCL-June2015v2_0.csv`, `_1.csv`, `_2.csv`; last three: `_165.csv`, `_166.csv`, `_167.csv`.
(Note that *alphabetical* order differs from numeric order — `_10.csv` sorts before `_2.csv` —
which is why the sequence was checked numerically. Sorting file names as text is a routine way
to process files in the wrong order.)

**Size spread.** Members are close in size but **not identical**: the smallest is
47,441,437 bytes and the largest 50,962,578,
a spread of 3,521,141 bytes
(~7% of the median). So the split was **not** into equal-sized files, and it is not yet known
whether it was into equal *row counts*. Rows per file remains **UNKNOWN** — byte size cannot be
converted to a row count without knowing the average bytes per row, which requires reading data.

### 9.6 Full-data archive — structure

| Property | Measured value |
|---|---|
| Compressed size on disk | 801,674,949 bytes (764.54 MiB) |
| Entries in archive | 1 |
| Member name | `CC_LCL-FullData.csv` |
| Member **uncompressed** size | 8,542,818,238 bytes (7.96 GiB / 8.54 GB) |
| Member compressed size | 801,674,781 bytes |
| Compression method | deflate64 |
| Subdirectories | none — member sits at archive root |
| Member timestamp (in-archive) | [2021, 8, 25, 12, 1, 22] |

**VERIFIED:** the archive contains exactly one member, a single flat CSV at the archive root,
with no directory structure. The full CSV was **not** opened or parsed — every figure above comes
from the archive's central directory, which is metadata about the member, not the member's
contents.

**UNKNOWN:** the meaning of the `CC_` prefix in `CC_LCL-FullData.csv`. The dataset page never
mentions this filename. No meaning is guessed here.

### 9.7 Are the two archives the same data? — INFERRED, not verified

The two archives' uncompressed totals are strikingly close, and the difference is not random:

```
partitioned, 168 CSVs, uncompressed :   8,542,826,421 bytes
full data,   1 CSV,    uncompressed :   8,542,818,238 bytes
difference                          :           8,183 bytes
extra files in the split (168 - 1)  :             167
difference / extra files            :            49.0  (exact integer: True)
```
**INFERRED:** the partitioned archive is very likely the same data as the full archive, split
into 168 files, where each additional file repeats a header line of **49 bytes**
(including its line terminator). The split archive is larger by *exactly*
167 × 49 bytes — 167 extra copies of something 49 bytes long.

**Why this is INFERRED and not VERIFIED:** the arithmetic is consistent with that explanation but
does not prove it. No header has been read. Other explanations — trailing-newline differences, or
a coincidental combination of content differences — have not been ruled out. This is a
**prediction to be tested in Phase C**, and it is a good one precisely because it is falsifiable:
reading the first line of any one member will either show a 49-byte header or not.

**VERDICT (added 2026-09-07): the 49-byte prediction was CONFIRMED by measurement** — see section
10.4. The header of `Small LCL Data/LCL-June2015v2_0.csv` is 47 bytes of text plus a 2-byte CRLF
terminator, exactly 49. This raises confidence but does not make the two archives *proven*
equivalent: equal header sizes are necessary, not sufficient. Until a content comparison is possible
— currently blocked by the deflate64 issue in section 9.4 — **do not** assume the two archives are
interchangeable.

### 9.8 Tariff workbook — structural check only

An `.xlsx` file is itself a ZIP container holding XML parts (the OOXML format). That lets us
confirm it is a structurally sound workbook **without opening it as a spreadsheet** and without
reading a single cell.

| Check | Result |
|---|---|
| First 4 bytes (magic) | `PK\x03\x04` — ZIP local file header — **VERIFIED** |
| Valid ZIP container | yes |
| Member parts | 12 |
| CRC-32 test | **PASSED** — no corrupt part |
| `[Content_Types].xml` | PRESENT (required by OOXML) |
| `_rels/.rels` | PRESENT (required by OOXML) |
| `xl/workbook.xml` | PRESENT (required by OOXML) |
| Worksheet parts | 3 (`xl/worksheets/sheet1..3.xml`) |
| Total uncompressed parts | 2,330,454 bytes |

**VERIFIED:** `Tariffs.xlsx` is a structurally valid, uncorrupted Excel 2007+ workbook containing
three worksheet parts.

**UNKNOWN — everything about its business content:** sheet names, headers, tariff dates, price
bands, row counts and whether it actually contains the 2013 dToU schedule. The worksheet *parts*
were counted by filename only; no XML was parsed and no cell was read. Ticket section 12 keeps
the tariff workbook out of scope for processing, so this is deliberate.

### 9.9 Reconciliation against Phase A page claims

Each Phase A claim is re-labelled against Phase B measurement. **No Phase A finding was edited**;
this table records what measurement now says about each one.

| # | Phase A claim (from the page) | Phase B measurement | Label |
|---|---|---|---|
| 1 | Three downloadable resources | Exactly 3 dataset files present in `data/raw/` | **VERIFIED** |
| 2 | Resource names `low-carbon-london-data`, `low-carbon-london-data-168-files`, `Tariffs` | On-disk names are `LCL-FullData.zip`, `Partitioned LCL Data.zip`, `Tariffs.xlsx` — **different from the displayed resource names** | **CONTRADICTED (naming only)** |
| 3 | `low-carbon-london-data` is 764.54 MB | `LCL-FullData.zip` = 801,674,949 bytes = **764.54 MiB** | **VERIFIED** |
| 4 | `low-carbon-london-data-168-files` is 758.86 MB | `Partitioned LCL Data.zip` = 795,722,689 bytes = **758.86 MiB** | **VERIFIED** |
| 5 | `Tariffs` is 239.63 kB | `Tariffs.xlsx` = 245,384 bytes = **239.63 KiB** | **VERIFIED** |
| 6 | "split into 168 separate CSV files" | 168 CSV members, indices 0–167, no gaps, no non-CSV members | **VERIFIED** |
| 7 | "around 10GB when unzipped" | Measured 8,542,826,421 bytes = 8.54 GB / 7.96 GiB | **INFERRED — approximate only** |
| 8 | "around 167million rows" | Not measurable without reading CSV data | **UNKNOWN** |
| 9 | "each containing 1 million rows" (Phase A: UNVERIFIED) | Still not measurable; member *byte* sizes vary by ~7% | **UNKNOWN** |
| 10 | Last update "over 4 years ago" | In-archive member timestamps are [2021, 8, 25] | **INFERRED — consistent, not proof** |
| 11 | Licence version | Nothing in the files was inspected for licence text | **UNKNOWN (unchanged)** |

**Row 2 — the naming mismatch.** This is a genuine discrepancy and is labelled CONTRADICTED
rather than smoothed over. The London Datastore page displays resource *titles*; the files it
delivers carry different *filenames*. The mapping between them is **INFERRED from the exact size
match in rows 3–5**, not observed — nobody recorded the download. It is a strong inference (three
independent sizes matching to two decimal places) but it is still an inference.

**Rows 3–5 — an important unit lesson.** The page's figures matched **only** when bytes were
divided by 1024-based units (MiB, KiB), not 1000-based units (MB, kB). 801,674,949 bytes is
801.67 MB but 764.54 MiB. The page writes "MB" and "kB" while displaying **binary** quantities.
Had we compared using decimal MB we would have reported a false mismatch of about 5%. Always
state which unit convention a size comparison uses.

**Row 7 — do not call this a match.** The publisher says "around 10GB"; measurement says
8.54 GB (or 7.96 GiB, which is
further from 10, not closer). The gap is roughly 1.5 GB, or about 15% — larger than rounding.
The page said "around", so this is **not** recorded as a contradiction, but the page figure is a
loose approximation and **must not be used as a check value** for any later reconciliation. The
measured byte count is the figure to use.

### 9.10 Proof that `data/raw/` was not modified

`stat -c '%n|%s|%Y|%i|%a'` was captured for every file **before** the checks and **after** them,
and the two captures were compared with `diff`. They are **identical** — no size changed, no
modification time moved, no inode was replaced (which would indicate a file was rewritten), and
no permission bit changed. The file count is still 6, so no extraction artefact was left behind.

**Open risk — the raw files are not actually write-protected.** They are mode `644` and owned by
`root`, so your user cannot overwrite their contents. But `data/raw/` itself is owned by your
user and is writable, which means files inside it can still be **renamed or deleted** without
`sudo`. Ticket section 3 requires raw input to be kept read-only. That is currently enforced by
convention, not by the filesystem. Making the directory itself read-only is recommended and has
**not** been done, because it would modify `data/raw/` and this phase's scope forbids that.

### 9.11 Phase B summary

**Newly VERIFIED:** the inventory of `data/raw/` (6 entries: 3 dataset files, 3 Mark-of-the-Web
streams); each file's exact byte size, UTC modification time, magic-byte type and SHA-256; that
the files originated from an internet download; that the partitioned archive is **fully
uncorrupted** across all 168 members; that it holds exactly 168 CSVs numbered 0–167 with no gaps,
no nested archives and no non-CSV members, under one internal directory; that the full-data
archive holds exactly one flat CSV member; that `Tariffs.xlsx` is a structurally valid three-
worksheet workbook; and that all three page-stated sizes match exactly in binary units.

**Newly CONTRADICTED:** the on-disk filenames do not match the resource names displayed on the
page (content mapping inferred from size, not observed).

**Newly INFERRED (unproven, testable):** the two archives hold the same data, with the split
version repeating a 49-byte header in each of its 167 extra files.

**Still UNKNOWN:** the integrity of `LCL-FullData.zip` (blocked on a deflate64-capable tool); the
true download date; the meaning of the `CC_` prefix; row counts of any kind; and every structural,
value-level, temporal and missingness property from section 7 — encoding, delimiter, header names,
column order, timezone, interval semantics, nulls, duplicates and gaps. **Phase B moved none of
section 7 to VERIFIED**, because none of it can be answered without reading data.

**Go / no-go on billing work: still NO,** and for the same Phase A reasons. Phase B strengthened
our confidence in the *container*, not in the *contents*. The timezone convention and
interval-start-vs-end semantics remain unresolved and remain blocking.

**Next smallest safe step:** read only the **first line** of a single member of the *verified*
partitioned archive, in memory, to test the 49-byte header prediction and to record
the encoding, delimiter and exact header spelling. That touches one line of one file, uses the
archive we have proven sound, and either confirms or kills the section 9.7 inference immediately.

---

*Phase B of REP-001, performed 2026-09-07. No raw file altered, renamed, extracted or deleted.
No CSV row read. No workbook cell read.*

---

## 10. Phase C — first CSV member: header and 20-record sample

**Phase:** C — file-level inspection of a single member (REP-001 section 4, partial).
**Date performed:** 2026-09-07.
**Member inspected:** `Small LCL Data/LCL-June2015v2_0.csv` from the CRC-verified `Partitioned LCL Data.zip`.
**Bytes read:** 1,024 of 50,755,532 — reading stopped as soon as 21 line terminators were present.
**Method:** the member was streamed in memory with `zipfile.ZipFile.open()`. Nothing was
extracted, and nothing in `data/raw/` was modified. Raw bytes were examined before decoding so
that byte-order marks and line terminators could not be hidden by a text tool.

### 10.1 Encoding — partly VERIFIED, partly UNKNOWN

| Check | Result | Label |
|---|---|---|
| UTF-8 / UTF-16 / UTF-32 byte-order mark | **absent** — file starts `4c 43 4c 69 64` = `LCLid` | **VERIFIED** |
| Bytes >= 0x80 (non-ASCII) in the sample | **0** | **VERIFIED (sample only)** |
| Line terminator | **CRLF** (`\r\n`) on every sampled line — 21 CR and 21 LF | **VERIFIED** |

**The honest limit of this evidence.** Every sampled byte is 7-bit ASCII. ASCII is a subset of
UTF-8, Latin-1 *and* Windows-1252, so on this sample those encodings are **indistinguishable**.
We have verified the file is *ASCII-compatible* and carries no BOM; we have **not** determined
its encoding. That stays **UNKNOWN** until the whole file is scanned for bytes >= 0x80.

**CRLF is an operational hazard worth naming.** These are Windows line endings on a Linux
machine. Splitting lines on `\n` alone leaves a stray `\r` welded to the final field:

```
correct (split on b'\r\n') : ['MAC000002', 'Std', '2012-10-12 00:30:00.0000000', ' 0 ']
naive   (split on b'\n')   : ['MAC000002', 'Std', '2012-10-12 00:30:00.0000000', ' 0 \r']
```
The consumption value would then be the string `' 0 \r'`. Python's `csv` module handles this
correctly when the file is opened with `newline=''`; hand-rolled line splitting does not.

### 10.2 Delimiter — VERIFIED

| Candidate | Occurrences per line across the 21 sampled lines |
|---|---|
| comma `,` | **3 on every line** |
| semicolon `;` | 0 |
| tab | 0 |
| pipe `\|` | 0 |

**VERIFIED: the delimiter is a comma.** The evidence is not merely that commas are present, but
that the count is *identical* on every line — 3 separators giving 4 fields. No quoting characters
appeared, and a strict CSV parse accepted all 21 lines without a single rejection.

### 10.3 Header — VERIFIED verbatim

Reproduced exactly as bytes, then decoded:

```
raw   : b'LCLid,stdorToU,DateTime,KWH/hh (per half hour) \r\n'
hex   : 4c 43 4c 69 64 2c 73 74 64 6f 72 54 6f 55 2c 44 61 74 65 54 69 6d 65 2c 4b 57 48 2f 68 68 20 28 70 65 72 20 68 61 6c 66 20 68 6f 75 72 29 20 0d 0a
length: 47 bytes without terminator, 49 bytes with CRLF
```
**4 columns**, in this order:

| # | Column name (exact) | Note |
|---|---|---|
| 0 | `'LCLid'` | Household identifier. |
| 1 | `'stdorToU'` | Tariff-group flag. **Not predicted** — see 10.7. |
| 2 | `'DateTime'` | Reading timestamp. |
| 3 | `'KWH/hh (per half hour) '` | **Name ends with a trailing space.** See warning below. |

**Trap — the fourth column name contains a trailing space.** It is
`'KWH/hh (per half hour) '`, not `'KWH/hh (per half hour)'`. Code that refers to the column without that space
will raise a KeyError, or worse, silently miss the column in a tolerant tool. It also contains a
`/` and parentheses, which are awkward in SQL identifiers. Any later model should rename this
column explicitly and record the mapping — but the **source** spelling is as printed above.

### 10.4 The 49-byte prediction — CONFIRMED

Phase B (section 9.7) inferred from arithmetic alone that the partitioned archive repeats a
**49-byte** header in each of its 167 extra files, because the two archives' uncompressed totals
differ by exactly 8,183 = 167 x 49 bytes. Measured directly:

```
header text                    : 47 bytes
CRLF terminator                : 2 bytes
total                          : 49 bytes
Phase B prediction             : 49 bytes
match                          : True
```
**VERIFIED.** The prediction was made before any byte of CSV was read and it held exactly. This
**raises** confidence that the two archives contain the same underlying data, split differently.
It does **not** prove it: identical header sizes are necessary but not sufficient. Confirming the
archives are equivalent would need a content comparison, which is blocked anyway because
`LCL-FullData.zip` cannot be decompressed by any tool on this machine (section 9.4). The
**INFERRED** label in 9.7 is upgraded to *strongly supported*, not to VERIFIED.

### 10.5 Record structure — VERIFIED

First three records verbatim, terminators visible:

```
b'MAC000002,Std,2012-10-12 00:30:00.0000000, 0 \r\n'
b'MAC000002,Std,2012-10-12 01:00:00.0000000, 0 \r\n'
b'MAC000002,Std,2012-10-12 01:30:00.0000000, 0 \r\n'
```
- Field count across all 20 records: **[4]** — every record has exactly
  4 fields, matching the header. **VERIFIED.**
- Strict CSV parse: **20/20 records accepted, 0 rejected.**
- Distinct `LCLid` in sample: **['MAC000002']** — one household only.
- Distinct `stdorToU` in sample: **['Std']**.
- **Values carry surrounding whitespace.** The consumption field is literally `' 0 '`, with a
  leading and a trailing space. Any numeric conversion must strip first; `float(' 0 ')` happens
  to work in Python, but a strict SQL cast or a `CASE WHEN value = '0'` comparison would not.

### 10.6 Timestamps — format VERIFIED, meaning UNKNOWN

| Item | Observation | Label |
|---|---|---|
| Observed format | `YYYY-MM-DD HH:MM:SS.fffffff` — 27 characters, 7 fractional-second digits | **VERIFIED** |
| Example (first) | `2012-10-12 00:30:00.0000000` | **VERIFIED** |
| Example (last of sample) | `2012-10-12 10:00:00.0000000` | **VERIFIED** |
| Fractional seconds | always `.0000000` in this sample — no sub-second precision actually used | **VERIFIED (sample)** |
| Spacing between consecutive rows | **[1800.0] seconds** = exactly 30 minutes, on all 19 gaps | **VERIFIED (sample)** |
| Timezone offset in the string | **none** — no `Z`, no `+00:00`, no `T` separator | **VERIFIED** |
| Timezone convention | | **UNKNOWN** |
| Interval start vs interval end | | **UNKNOWN** |

**Why the timezone must stay UNKNOWN.** The string carries no offset. The information is simply
not present in the file, so no amount of inspection can recover it — it can only come from
authoritative documentation. Ticket section 7 forbids guessing, and nothing here overrides that.

**Why interval start-vs-end must stay UNKNOWN, including one observation that is NOT evidence.**
The first reading is `2012-10-12 00:30:00.0000000` — 00:30, not 00:00. It is tempting to argue that a day starting at
00:30 implies the timestamp marks the interval *end*. **That argument does not hold.** This is
this household's first-ever reading, not necessarily a day boundary; a meter commissioned partway
through 2012-10-12 would produce exactly this pattern under either convention. The observation is
recorded so it can be re-examined later against many households, but it proves nothing now.
The seven-digit fractional-second format is characteristic of SQL Server `datetime2`, hinting the
data was exported from such a system — also **INFERRED**, also not evidence of timezone.

### 10.7 Consumption values — the interval-vs-cumulative question

This is the single most consequential question for billing, and **the sample cannot answer it.**

All 20 sampled values are `0`. Measured: min=0.0, max=0.0, distinct values
= [0.0], sum = 0.0.

A naive test — *a cumulative register never decreases, so zero decreases implies cumulative* —
returns `True` here and would be **wrong to trust**:

```
increasing steps : 0/19
decreasing steps : 0/19
unchanged steps  : 19/19   <- the series is constant; it carries no information
```
A constant series is technically non-decreasing, so it passes the cumulative test — but a real
cumulative register would *increase* whenever any energy was consumed, and this one never does.
The series is consistent with both readings and discriminates between neither.

**Label: UNKNOWN at the time of Phase C.** Whether these are per-interval values or cumulative
register readings was **not determined** by this evidence.

> **RESOLVED IN PHASE D (section 11.3): VERIFIED per-interval.** A 300-record window from the same
> household showed **142 decreases** against 134 increases, with a maximum value of 1.164 — far
> below any register rollover threshold, and far too many decreases for meter exchanges. Cumulative
> register readings are ruled out by observed behaviour, not by the column label alone.

The Phase C reasoning below is retained because the discipline it demonstrates still applies. This matters enormously: if they are per-interval you SUM
them to bill; if they are cumulative you must DIFFERENCE consecutive readings. Summing cumulative
readings produces a bill wrong by orders of magnitude.

**The one supporting signal, labelled honestly.** The source's own column name is
`'KWH/hh (per half hour) '` — the publisher naming the unit as *per half hour*, which is a per-interval
description. This agrees with the dataset page quoted in section 2 ("energy consumption, in kWh
(per half hour)"). Two independent documentary statements both describe per-interval values.
That is **INFERRED — strongly supported by documentation, not yet confirmed by observed value
behaviour.** A column label is a claim by the publisher, not a demonstration. It is confirmed the
moment we observe values that rise and fall, which a cumulative register cannot do.

**Also UNKNOWN: why 20 consecutive zeros.** A run of exact zeros at a household's first readings
could be a meter installed but not yet reporting, a genuinely empty property, or a recording
artefact. Ticket section 6 forbids interpreting absence or zero without evidence. No
interpretation is offered here.

### 10.8 Null tokens — UNKNOWN from this sample

Scanning all four fields of all 20 records for `Null`, `NULL`, `null`, `NA`, `N/A`, `nan`, `NaN`,
`-` and empty strings found **none**, and **0 empty fields**.

**This is not evidence that the file contains no nulls.** Twenty consecutive rows from one
household is far too small a sample to conclude anything about null representation. Ticket
section 0 lists "a literal token such as `Null`" as an unverified claim; it remains **UNKNOWN**,
neither confirmed nor refuted. The exact spelling and casing still has to be established before
any missing-reading count can be trusted, because `Null`, `NULL` and `null` are three different
strings and a filter written for one silently passes the others into your totals.

### 10.9 What this step closed, and what it did not

Answers below apply to **one member of one archive**. Section 2b of the ticket requires
re-testing across files before any of it is treated as archive-wide.

| Section 7 unknown | Status after Phase C |
|---|---|
| File encoding | **partly closed** — no BOM, ASCII-compatible, CRLF; exact encoding still UNKNOWN |
| Field delimiter | **CLOSED (this file)** — comma, VERIFIED |
| Exact column header names and spelling | **CLOSED (this file)** — VERIFIED verbatim, incl. trailing space |
| Column order | **CLOSED (this file)** — VERIFIED |
| Whether headers repeat inside a file | **still UNKNOWN** — 20 records cannot show this |
| Whether all 168 files share one structure | **still UNKNOWN** — only one file inspected |
| Null representation | **still UNKNOWN** — none seen in 20 records |
| Zero readings — presence and meaning | presence **VERIFIED**; meaning **UNKNOWN** |
| Negative readings | **still UNKNOWN** |
| Timestamp string format | **CLOSED (this file)** — VERIFIED |
| Timezone convention | **still UNKNOWN** — not present in the data at all |
| Interval start vs end | **still UNKNOWN** — not determinable from data |
| Interval vs cumulative values | **still UNKNOWN** — sample was constant; INFERRED per-interval from column name |
| Row counts of any kind | **still UNKNOWN** — no counting performed |

**Go / no-go on billing work: still NO.** Phase C resolved how to *read* the file. It did not
resolve what the numbers *mean*. The timezone convention, the interval-start-vs-end semantics and
the interval-vs-cumulative question are all still open, and each on its own is enough to make a
billing calculation confidently wrong.

---

*Phase C of REP-001, performed 2026-09-07. One member streamed read-only from the archive;
1,024 bytes read; nothing extracted, nothing in `data/raw/` modified.*

---

## 11. Phase D — bounded non-zero consumption window

**Phase:** D — consumption behaviour (REP-001 section 6, partial). **Date:** 2026-09-07.
**Member:** `Small LCL Data/LCL-June2015v2_0.csv`, streamed read-only from
`Partitioned LCL Data.zip`. Nothing extracted; `data/raw/` unmodified.

### 11.1 Bounds, declared before the scan

Thresholds were fixed **in advance and in writing** so that the qualifying window could not be
chosen after seeing which window gave a preferred answer.

| Bound | Value | Outcome |
|---|---|---|
| Max records scanned | 200,000 | not reached |
| Max bytes read | 16 MiB | not reached |
| Qualifying window | >= 300 consecutive records, one `LCLid`, >= 100 non-zero numeric values | met at record 299 |
| Household boundary | window terminates at any `LCLid` change | single household throughout |

**Scan stopped after 300 records** — the first qualifying window was also the first 300 records,
so no window selection took place at all. There was nothing to cherry-pick from.

### 11.2 Window contents — VERIFIED counts

Household `MAC000002`, records 0-299, `2012-10-12` to `2012-10-18`.

| Measure | Value |
|---|---|
| Records inspected | 300 |
| Field-count distribution | `{4: 300}` — every record has 4 fields |
| Numeric values | 300 |
| Zero values | 21 |
| Non-zero values | 279 |
| Empty fields | 0 |
| Non-numeric values | 0 |
| **Negative values** | **0** |
| Minimum | 0.0 |
| Maximum | 1.164 |

Ticket section 6 requires negatives to be counted and characterised: **none occur in this
window.** That is a window-scoped result, not a statement about the file.

### 11.3 Step behaviour — the decisive evidence

Across 299 consecutive pairs:

| Transition | Count |
|---|---|
| Increases | 134 |
| **Decreases** | **142** |
| Equal | 23 |
| Monotonically non-decreasing (cumulative signature) | **False** |

**VERIFIED: these are not cumulative register readings.** The reasoning, stated carefully
because a single decrease would prove nothing:

- A cumulative register *can* decrease, but only by **rollover** (the dial passes its maximum,
  e.g. 99999.9, and wraps to 0) or by **meter exchange**. The maximum value observed is
  **1.164** — nowhere near any rollover threshold.
- 142 decreases occurred in **six days**. Neither rollover nor meter replacement can happen
  142 times in six days for one household.
- Increases (134) and decreases (142) are almost balanced and interleaved throughout,
  which is the signature of a quantity that rises and falls — consumption during each interval —
  not of a total that only accumulates.

Combined with the publisher's own column name
`'KWH/hh (per half hour) '` and the dataset page's "energy consumption, in kWh (per half hour)" (section 2),
**the values represent per-interval consumption, not a cumulative register. VERIFIED by observed
behaviour, corroborated by two independent documentary statements.**

**Billing consequence:** these values are **summed** over a billing period. They must **not** be
differenced.

**What this does NOT establish.** The *unit* is taken on the publisher's word. Ticket
section 6 requires the unit to come from authoritative documentation, and states plainly that
plausibility of the observed range may be noted but **does not confirm the unit**. Accordingly:

> **RECLASSIFIED IN PHASE G (section 14.1): the unit is PUBLISHER-DOCUMENTED, not UNKNOWN.**
> Section 6 requires a *citation*, and one exists — the dataset page states "energy consumption, in
> kWh (per half hour)", and Phase F confirmed by census that all 168 members carry the column name
> `KWH/hh (per half hour) `. Recording the unit as UNKNOWN was over-strict. The documented contract
> and the per-interval behaviour VERIFIED below agree with each other.

> Corroborating note only: 48 consecutive values from the first non-zero reading sum to
> **12.4530**, with individual values from 0.106 to 0.933. If the unit is kWh
> per half hour, that is a plausible daily total for a single household. This is **noted, not
> relied upon.** It is consistent with the documented unit; it does not prove it.

### 11.4 Timestamps and one missing interval

| Item | Observation |
|---|---|
| First / last | `2012-10-12 00:30:00.0000000` -> `2012-10-18 06:30:00.0000000` |
| Strictly increasing | **True** — no out-of-order or duplicate timestamps |
| Distinct gaps | {1800s: 298, 3600s: 1} |

**One 3600-second gap — a genuinely missing half-hourly reading. VERIFIED.**

```
record 20 : 2012-10-12 10:30:00.0000000
record 21 : 2012-10-12 11:30:00.0000000     <- the 11:00 reading is ABSENT
```
Ticket section 9 calls this an **internal gap**: it lies between the household's first and last
observed reading, not at an edge. It is **one absent row**, not a row containing zero — the two
must never be conflated, and ticket section 6 forbids filling it with zero.

**Cause: UNKNOWN.** No interpretation is offered, and no daylight-saving analysis was performed
(ticket section 7 defers that until the timezone convention is known).

### 11.5 An observed co-occurrence — recorded, deliberately not explained

The 21 zero values are **not scattered**. They form a single unbroken run at indices 0-20,
`00:30` to `10:30` on 2012-10-12. The very next expected reading (11:00) is the missing one, and
the first non-zero value — `' 0.143 '` — is at 11:30.

```
00:30 .. 10:30   21 consecutive readings, all ' 0 '
11:00            MISSING
11:30            0.143    <- first non-zero; normal variation continues from here
```
**This pattern is recorded as an observation. Its cause is UNKNOWN and no explanation is adopted
here.** It is tempting to read it as a meter being commissioned mid-morning, but ticket section 6
forbids labelling a zero or a gap without evidence, and a single household proves nothing. It is
a **hypothesis for a later phase**, testable by checking whether other households also show a
leading zero-run terminating at a gap. Until then it is a coincidence we have written down.

### 11.6 Null tokens and tariff flag

- **Null tokens: none found** across all 300 scanned records — 0 empty fields, 0 non-numeric
  values, no `Null`/`NULL`/`null`/`NA` in any field. **Still UNKNOWN for the file**: 300 records
  from one household cannot establish how the source represents a missing reading. Ticket
  section 0's "a literal token such as `Null`" is neither confirmed nor refuted.
  > **RESOLVED IN PHASE E (section 12.5): the token exists and is `Null`.** A 152,811-row scan
  > across 5 households found 5 occurrences, spelled `Null` with **no surrounding whitespace**,
  > unlike numeric values which are space-padded. Phase D's null-free result was correct for its
  > 300-row scope and is a good illustration of why "not observed" is not "does not exist".
- **`stdorToU`: only `Std` observed**, on every record. Per your
  instruction this label is **not** assumed to determine the applicable tariff. Two reasons it
  cannot be taken at face value yet: the dToU tariff ran only during **2013** while this data is
  from **2012**, and we have not established whether the flag is fixed per household or can vary
  over time. Treating a static label as a time-varying tariff assignment is exactly the kind of
  error this project exists to catch. **UNKNOWN.**

### 11.7 Human-viewable preview

`data/sample/lcl-june2015v2-0-preview.csv` — **git-ignored, never committed** (`.gitignore`
line 8, `data/sample/`).

| Property | Value |
|---|---|
| Source member | `Small LCL Data/LCL-June2015v2_0.csv` |
| Source records | 0-based data indices **11-60**, contiguous |
| Rows | 1 header + **50** data rows |
| Bytes | 2,556 |
| SHA-256 | `04affe9fdfa6374cfadf62ae38159f106534972ecc614b0b28cb9496991a6f9e` |
| Span | `2012-10-12 06:00` to `2012-10-13 07:00` |
| Contents | 10 zeros, the missing 11:00 interval, then 40 non-zero readings |

**Faithfulness.** The file was built by copying **raw bytes** from the decompressed stream, not
by re-serialising parsed values. Verified: the header line and all 50 record lines appear
verbatim in the source, and the 50 records form one contiguous run. Surrounding spaces (` 0.143 `)
and CRLF line endings are preserved. Nothing was cleaned, trimmed or reformatted.

**Provenance is recorded here, not in the CSV**, precisely so the CSV stays byte-faithful.

**This file is derived data, not source data.** The originals in `data/raw/` remain the only
authoritative copy. The preview is fully regenerable from the record range above.

### 11.8 Status after Phase D

| Question | Status |
|---|---|
| Per-interval vs cumulative | **VERIFIED per-interval** (142 decreases; max 1.164) |
| Negative values | **none in window** (window-scoped) |
| Missing intervals exist | **VERIFIED** — one internal gap observed |
| Cause of missing interval | **UNKNOWN** |
| Meaning of the zero run | **UNKNOWN** |
| Consumption unit | **PUBLISHER-DOCUMENTED** (reclassified in Phase G 14.1) — kWh per half hour |
| Null token representation | **UNKNOWN** — none seen in 300 records |
| Timezone convention | **UNKNOWN** — not present in the data |
| Interval start vs end | **UNKNOWN** — not determinable from data |
| Whether `stdorToU` determines the tariff | **UNKNOWN** |
| File encoding | **UNKNOWN** — all sampled bytes ASCII |
| Whether all 168 files share one structure | **UNKNOWN** |
| Row counts | **UNKNOWN** — no counting performed |

**Go / no-go on billing: still NO.** Phase D removed one of the three blocking semantic unknowns
— we now know to sum rather than difference. The timezone convention and the
interval-start-vs-end question remain open, and either alone is enough to place energy in the
wrong billing period.

---

*Phase D of REP-001, 2026-09-07. 300 records streamed read-only; bounds declared in advance and
not reached; nothing extracted; `data/raw/` unmodified.*

---

## 12. Phase E — zeros, explicit missing tokens and absent intervals across households

**Phase:** E — missing-value characterisation (REP-001 sections 6, 8, 9; partial).
**Date:** 2026-09-07. **Member:** `Small LCL Data/LCL-June2015v2_0.csv`, streamed read-only from
`Partitioned LCL Data.zip`. Nothing extracted; `data/raw/` unmodified.

### 12.1 The three cases, kept separate

| Case | Definition | Why it must not be merged with the others |
|---|---|---|
| **Numeric zero** | A row exists; its value parses as `0`. | The source asserts a measurement of zero. It is data. |
| **Explicit missing token** | A row exists; its value is empty or non-numeric. | The source asserts *it has no value here*. Silently coercing it to 0 under-bills. |
| **Absent interval** | **No row exists** for an expected half-hourly slot. | Nothing was asserted at all. Filling it with 0 invents a measurement (REP-001 section 6 forbids this). |

### 12.2 Pre-registered bounds

Fixed in writing before the scan, so the stopping point could not be chosen to suit the result.

| Bound | Value | Outcome |
|---|---|---|
| Primary stop | 5 **complete** household runs | **triggered** |
| Hard cap — records | 500,000 | not reached (152,812 read) |
| Hard cap — bytes | 32 MiB | not reached |
| Gap analysis input | complete runs only | 5 households |
| Pooling | never across households | honoured |

**Why only complete runs.** The last household in any bounded scan is cut off mid-stream. Using
it would give a false "last reading" and misclassify real internal gaps as edge periods. The
sixth household (`MAC000008`, 1 row) was therefore **excluded** from all analysis.

### 12.3 A narrower gap check than REP-001 section 9 — reasoning recorded for challenge

Section 9 states that the **expected interval count** may only be computed from *documented*
timestamp semantics, and that while interval-start-vs-end is UNKNOWN the check is "deferred, not
approximated". That remains true and **section 9's full check is still deferred.**

What was done here is narrower and does not depend on those semantics. Absences are counted
**strictly between each household's own first and last observed timestamp**:

```
absent = (last_observed - first_observed) / 1800s + 1 - distinct_observed_timestamps
```
Shifting every timestamp label by half an hour (the start-vs-end ambiguity) moves both endpoints
equally, so this count is **invariant** to which convention is correct. What the ambiguity does
affect — which billing period a reading belongs to — is not claimed anywhere in this phase.

**Ceiling on these numbers.** If the timestamps are UK local time, a spring daylight-saving
transition legitimately skips slots. We do not know the timezone, and section 7 forbids DST
analysis until we do. **Every absent-interval figure below is therefore an UPPER BOUND** on
genuinely missing readings.

### 12.4 Measured results — 5 complete households, 152,811 rows

| Measure | Value |
|---|---|
| Rows inspected | **152,811** |
| Distinct households (complete) | **5** — `MAC000002`, `MAC000003`, `MAC000004`, `MAC000006`, `MAC000007` |
| Valid numeric values | **152,806** |
| Numeric zeros | **26,229** |
| **Negative values** | **0** |
| Empty values (`''`) | **0** |
| Non-numeric token values | **5** |
| Malformed field counts | **0** — every row has exactly 4 fields |

**Reconciliation (all rows accounted for):**

```
152,806 numeric rows  +  5 'Null' rows  =  152,811 rows            OK
152,706 distinct keys + 105 duplicate extras = 152,811 rows        OK
```
### 12.5 The missing-value token — OBSERVED, recorded exactly

A missing-value token **was** found. Recorded verbatim, whitespace preserved:

| Token (exact `repr`) | Count | Casing |
|---|---|---|
| `'Null'` | 5 | capital `N`, lower-case `ull` |

**Critical formatting asymmetry — VERIFIED.** Numeric values are wrapped in spaces; the token is
**not**:

```
numeric value : ' 0.2 '     <- leading and trailing space
missing token : 'Null'      <- no surrounding whitespace at all
```
A parser that assumes a uniform ` value ` shape, or that compares against `' Null '`, will miss
every one of these. Ticket section 0 listed "a literal token such as `Null`" as unverified; the
spelling is now **VERIFIED as `Null`** within this scope.

**Scope limit — required wording.** Other tokens (`NULL`, `null`, `NA`, `-`, empty strings) were
**not observed within this scope**. That is *not* a claim that none exist elsewhere in the
archive. 152,811 rows from 5 households in 1 of 168 members cannot establish that.

### 12.6 Every `Null` row is off the half-hour grid — VERIFIED co-occurrence

| Household | Timestamp | Value | On half-hour grid? |
|---|---|---|---|
| `MAC000002` | `2012-12-19 12:37:27.0000000` | `Null` | **no** |
| `MAC000003` | `2012-12-19 12:37:26.0000000` | `Null` | **no** |
| `MAC000004` | `2012-12-19 12:32:40.0000000` | `Null` | **no** |
| `MAC000006` | `2012-12-19 12:37:26.0000000` | `Null` | **no** |
| `MAC000007` | `2012-12-19 12:37:27.0000000` | `Null` | **no** |

The correlation is **perfect in this sample**: all 5 `Null` rows are off-grid (seconds and
minutes not at `:00:00` or `:30:00`), and all 5 off-grid rows are `Null` rows. All five fall on
**2012-12-19**, within about five minutes of each other, one per household.

**Structural consequence.** These rows are **not missing half-hourly readings**. They are extra
rows that do not belong to the half-hour series at all. Counting them as absent intervals, or as
gaps in the grid, would be wrong. They are counted separately throughout this section.

**Cause: UNKNOWN.** REP-001 sections 6 and 9 forbid attributing a cause without evidence. The
co-occurrence is recorded as an observation and as a hypothesis for a later, wider test.

### 12.7 Absent intervals — per household, grid rows only

Computed after removing the 5 off-grid rows, so the arithmetic describes the half-hour grid only.
Never pooled across households (REP-001 section 9).

| Household | Grid rows | First observed | Last observed | Span (slots) | Distinct observed | **Absent** | % of span |
|---|---:|---|---|---:|---:|---:|---:|
| `MAC000002` | 24,157 | 2012-10-12 00:30 | 2014-02-28 00:00 | 24,192 | 24,140 | **52** | 0.215% |
| `MAC000003` | 35,468 | 2012-02-20 13:00 | 2014-02-28 00:00 | 35,447 | 35,444 | **3** | 0.008% |
| `MAC000004` | 31,676 | 2012-05-08 13:00 | 2014-02-28 00:00 | 31,703 | 31,654 | **49** | 0.155% |
| `MAC000006` | 36,460 | 2012-01-30 11:30 | 2014-02-28 00:00 | 36,458 | 36,435 | **23** | 0.063% |
| `MAC000007` | 25,045 | 2012-09-24 12:00 | 2014-02-28 00:00 | 25,033 | 25,028 | **5** | 0.020% |
| **Total** | | | | **152,833** | | **132** | **0.086%** |

These are **internal** gaps only — between each household's own first and last reading. **Edge
periods** (before a household's first reading, after its last) are a different thing entirely and
are **not** counted here: they are absence of observation, not gaps in service. Note the five
households start on five different dates but all end on **2014-02-28**.

Largest observed single gaps: 88,200s (24.5 hours) in `MAC000002` and `MAC000004`; 19,800s
(5.5 hours) twice in `MAC000006`. **Causes UNKNOWN, and no gap is filled, interpolated or
deleted.**

### 12.8 Duplicates — REP-001 section 8, three separate figures

| Question | Result |
|---|---|
| 1. Exact duplicate rows (every field identical) | **105 extra rows** |
| 2. Duplicate candidate keys (`household` + `timestamp`) | **105 colliding keys** |
| 3. **Conflicting** duplicates (same key, different value) | **0** |

**The reassuring result is (3).** Every duplicate pair is identical in *all four* fields, so the
source never disagrees with itself within this scope. Had (3) been non-zero, a later model would
have had to choose between competing values and justify the choice.

**Structural pattern — VERIFIED, cause UNKNOWN.** All 105 duplicate timestamps occur at exactly
`00:00:00`, across **25 distinct dates** spread from 2012-02-15 to 2014-02-28 at roughly monthly
intervals (15th-28th of successive months).

In section 12.3 a daylight-saving transition was raised as a candidate explanation for duplicate
timestamps. **The evidence does not support that**: DST occurs once a year in late October, not on
25 dates at roughly monthly spacing. That candidate is set aside on structural grounds without
performing any DST analysis. **The actual cause remains UNKNOWN.**

**Not yet a valid key.** REP-001 section 8 warns against concluding `household + timestamp` is a
valid unique key from one file. It is **not** unique even here — 105 collisions. Whether the
collisions are always benign duplicates elsewhere in the archive is **UNKNOWN**.

### 12.9 Timestamp ordering

All five households store rows in **non-decreasing** timestamp order: zero backwards steps, with
the only non-increasing steps being the exact repeats from 12.8.

| Household | Backwards steps | Exact repeats |
|---|---:|---:|
| `MAC000002` | 0 | 17 |
| `MAC000003` | 0 | 24 |
| `MAC000004` | 0 | 22 |
| `MAC000006` | 0 | 25 |
| `MAC000007` | 0 | 17 |

**VERIFIED:** the file is not shuffled. Earlier phases reported "not strictly increasing", which
is true but was ambiguous; the cause is duplicate timestamps, **not** out-of-order data.

### 12.10 Zero rates vary enormously between households — VERIFIED, unexplained

| Household | Zeros | Rows | Zero rate |
|---|---:|---:|---:|
| `MAC000002` | 21 | 24,158 | 0.1% |
| `MAC000003` | 0 | 35,469 | **0.0%** |
| `MAC000004` | 24,307 | 31,677 | **76.7%** |
| `MAC000006` | 1,901 | 36,461 | 5.2% |
| `MAC000007` | 0 | 25,046 | **0.0%** |

**This is the most consequential finding for later modelling.** Zero rates range from 0.0% to
76.7% among five neighbouring household IDs. Two households record *no* zero in over 60,000 rows
combined; one records zero in three readings out of four.

**No explanation is adopted.** REP-001 section 6 forbids labelling a zero without evidence. What
this does establish is that **any aggregate zero statistic computed across households would be
meaningless** — it would average together populations that behave completely differently. Zero
analysis must stay per-household until the variation is understood.

### 12.11 Selection risk — two layers, both material

**This scan is not a random sample of the dataset, and its results must not be generalised.**

1. **One member of 168.** Approximately 0.6% of the archive, and the only member ever inspected
   in any phase. If member 0 differs structurally from the others, every finding since Phase C
   inherits that bias. Phase B established that members vary in size by about 7%, which is
   consistent with, but not evidence of, structural variation.
2. **The first records of that member — the sharper problem.** Rows are grouped by household in
   ascending ID order, so these are the five lowest household IDs in the file. Household IDs
   plausibly track recruitment order, which may track trial cohort and meter installation date.
   "The first five households" is therefore potentially the **earliest-installed** group —
   precisely the population most likely to show unusual early-life meter behaviour, which is
   exactly what this phase measures. The 5 households are also drawn from only 6 consecutive IDs
   (`MAC000002`-`MAC000008`, with `MAC000005` absent from this member).

**Consequence for every number in this section:** they are VERIFIED *for these five households in
this member*, and are **UNKNOWN** as archive-wide quantities. In particular the `Null` count, the
0.086% absence rate and the 105 duplicates must not be extrapolated.

**Proposed mitigation (for a later phase):** a stratified sample — a bounded window from several
members spread across the 0-167 range, and from different offsets within each member, rather than
more rows from the same place.

> **ACTED ON IN PHASE F (section 13).** The stratified sample was performed (members 0, 42, 84, 126,
> 167, shallow and deep windows) and the header census covered all 168 members. Structure is now
> census-verified archive-wide. Phase F also revealed that member 0 is **not** representative in one
> respect: it contains only `Std` households, so Phases C-E never saw the `ToU` tariff group at all.

### 12.12 Status after Phase E

| Question | Status |
|---|---|
| Does an explicit missing token exist? | **VERIFIED — yes, `Null`** (within scope) |
| Exact spelling / casing / whitespace of the token | **VERIFIED** — `'Null'`, unpadded |
| Are there other tokens? | **UNKNOWN** — not observed within this scope |
| Are empty fields used? | **not observed within this scope** |
| Do absent intervals exist? | **VERIFIED — yes**, 132 across 5 households (upper bound) |
| Cause of any absence, zero or token | **UNKNOWN** |
| Negative values | **none observed** in 152,811 rows |
| Malformed rows | **none observed** in 152,811 rows |
| Is `household + timestamp` unique? | **VERIFIED NO** — 105 collisions, all benign here |
| Are duplicates ever conflicting? | **none observed within this scope** |
| Is the file time-ordered? | **VERIFIED non-decreasing** per household |
| Timezone convention | **UNKNOWN** |
| Interval start vs end | **UNKNOWN** |
| Consumption unit | **PUBLISHER-DOCUMENTED** (reclassified in Phase G 14.1) |
| Archive-wide generality of all the above | **UNKNOWN** — see 12.11 |

**Handling policy is deliberately absent.** REP-001 section 12 places "deciding *how* to handle
nulls, duplicates or gaps" out of scope: this ticket measures and describes them only. A proposed
policy has been put to the reviewer separately and must be decided in its own ticket.

**Go / no-go on billing: still NO.** Timezone and interval-start-vs-end remain unresolved.

---

*Phase E of REP-001, 2026-09-07. 152,812 rows streamed read-only; bounds pre-registered and not
reached; nothing filled, interpolated or deleted; `data/raw/` unmodified.*

---

## 13. Phase F — structural consistency across the partitioned archive

**Phase:** F — cross-member structural verification (REP-001 section 2b, partial).
**Date:** 2026-09-07. **Source:** `Partitioned LCL Data.zip`, streamed read-only.
Nothing extracted; `data/raw/` unmodified.

### 13.1 Census versus sample — why the two halves carry different weight

| Evidence type | Coverage | What it can establish |
|---|---|---|
| **Census** — headers + first data row of every member | **168 of 168 (100%)** | Findings are **VERIFIED archive-wide** |
| **Sample** — bounded record windows | 5 of 168 members | Can **refute** uniformity; can never **prove** it |

Pre-registered before scanning: members **0, 42, 84, 126, 167**; **5,000** records per window;
a **shallow** window (from row 1) and a **deep** window (skip 500,000 rows) in each, to test
whether position *within* a member matters; **50,000** rows maximum.

Three further checks were **declared before running** after the census raised specific questions:
(a) `stdorToU` in the first 200 rows of members 128-140; (b) the full household-ID sets of
members 4 and 135; (c) full row counts and household-block sequences of members 0, 4, 5 and 167.

### 13.2 Header census — all 168 members. VERIFIED ARCHIVE-WIDE

```
distinct header byte-strings across 168 members : 1
sha256  : 4980f3cc398ca4b241006c8bcd617fedb4d5df221c94dbf945aae788880233f4
repr    : b'LCLid,stdorToU,DateTime,KWH/hh (per half hour) '
length  : 47 bytes text + 2 bytes CRLF = 49 bytes
```
| Property | Result | Coverage |
|---|---|---|
| Member count | **168** | census |
| Distinct headers | **exactly 1** | census |
| Column names and order | `LCLid`, `stdorToU`, `DateTime`, `KWH/hh (per half hour) ` — identical everywhere | census |
| Trailing space in column 4 | present in **all 168** | census |
| Delimiter | comma; 3 per header line in all 168 | census |
| Line ending | **CRLF** in all 168 | census |
| First data row field count | 4 fields in **168/168** | census |
| Non-ASCII bytes in header or first row | **0** across all 168 | census |

**VERIFIED for the whole archive:** every member has the same header, byte for byte, the same
four columns in the same order, the same comma delimiter and CRLF line endings. This is the
first archive-wide structural fact the project has, and it retires the Phase B/C caveat
"one file only" for schema, delimiter and line endings.

It also confirms the Phase B arithmetic independently: 168 identical 49-byte headers is exactly
what the 8,183 = 167 x 49 byte difference between the two archives predicted.

### 13.3 The archive is two blocks, split by tariff group — VERIFIED

The first-household census revealed the ID sequence **restarts once**:

```
member 134 first household = MAC005555   stdorToU = Std
member 135 first household = MAC000146   stdorToU = ToU     <- sequence restarts
```
Checking `stdorToU` across members 128-140 shows a clean boundary:

| Members | Count | `stdorToU` | First household |
|---|---:|---|---|
| **0 - 134** | 135 | **`Std`** | `MAC000002` -> `MAC005555` ascending |
| **135 - 167** | 33 | **`ToU`** | `MAC000146` -> `MAC005470` ascending |

**VERIFIED:** the partitioned archive is ordered by *(tariff group, household ID, timestamp)*.
The single ordering break is the boundary between the two groups, not corruption.

**INFERRED — the ToU block is the dToU trial cohort.** 33 of 168 members is 19.6% of the archive.
Phase A recorded ~1,100 dToU customers out of 5,567, which is 19.8%. The agreement is close but
this is **INFERRED, not VERIFIED** — we have not counted households in the ToU block.

**VERIFIED: the two blocks hold disjoint households.** Member 4 (`MAC000131`-`MAC000166`, all
`Std`) and member 135 (`MAC000146`-`MAC000298`, all `ToU`) share **zero** household IDs, even
though their ID ranges interleave: `MAC000146` falls inside member 4's range but is **not** in
member 4. So a household belongs to exactly one tariff block.

**This does NOT mean `stdorToU` is safe to use as a tariff rate selector.** It is a per-household
group label. Phase A established the dToU tariff ran only during **2013**, while the data spans
Nov 2011 - Feb 2014. A `ToU` household's 2012 readings carry the `ToU` label but predate the
tariff. Whether the label is time-varying is still **UNKNOWN**.

### 13.4 Households SPAN member boundaries — VERIFIED, and it changes how the data must be read

```
member 4 : 1,000,000 rows, 30 household blocks, first=MAC000131, LAST =MAC000166
member 5 : 1,000,000 rows, 27 household blocks, FIRST=MAC000166, last =MAC000200
shared household ids: ['MAC000166']
```
**VERIFIED: `LCLid` is not unique to a file.** `MAC000166`'s readings are split across members 4
and 5. This answers REP-001 section 2b's first question directly: **the household identifier
repeats across files.**

**Consequence for any pipeline:** a household's readings cannot be analysed from a single member.
Any per-household calculation — first/last reading, gap analysis, totals — must union the
adjacent member, or it will silently truncate the household at the file boundary.

**Correction to a Phase E method (not to its results).** Phase E treated a household run as
"complete" when the `LCLid` changed within member 0. That test is **only valid for households
wholly interior to a member.** The five households Phase E analysed (`MAC000002`-`MAC000007`) sit
at the very start of member 0, far from the 1,000,000-row boundary, so **their results stand.**
The *method*, however, must not be reused near a member boundary.

### 13.5 Row counts — the split rule is 1,000,000 rows per file. Phase B's inference CORRECTED

| Member | Data rows | Household blocks |
|---|---:|---:|
| 0 | **1,000,000** | 30 |
| 4 | **1,000,000** | 30 |
| 5 | **1,000,000** | 27 |
| 135 | **1,000,000** | 27 |
| 167 (last) | **932,474** | 31 |

**VERIFIED for these five members. INFERRED for the rest:** the archive is split at exactly
1,000,000 data rows per file, with the remainder in the final member.

```
members 0-166 at 1,000,000 rows (inferred) : 167,000,000
member 167 (measured)                      :     932,474
inferred archive total                     : 167,932,474 rows
```
**Independent corroboration from Phase B's byte measurements, with no further reading:**

```
total uncompressed 8,542,826,421 - (168 headers x 49) = 8,542,818,189 data bytes
  / 167,932,474 rows                                  =  50.871 bytes/row
median member 50,884,769 bytes / 1,000,000 rows       =  50.885 bytes/row   <- agrees
smallest member / median size ratio                    =  0.9323
member 167 rows / 1,000,000                            =  0.9325           <- agrees
```
Two independent routes agree to about 0.02 bytes per row, and the smallest member's **size**
ratio matches the last member's measured **row** ratio.

**A Phase B inference is hereby corrected.** Phase B (section 4) inferred 167,000,000 / 168 =
**994,048** rows per file on the assumption of an even split. Measurement says **1,000,000**.
The inference was reasonable, clearly labelled INFERRED, and **wrong by 5,952 rows per file** —
which is exactly why Phase B recorded that it "must not be used as an expected count".

**Phase A's UNVERIFIED claim is now settled.** Section 4 recorded "approximately one million rows
per file" as UNVERIFIED because the phrase could not be confirmed as displayed page text. It is
now **VERIFIED by measurement** — and it is exact, not approximate, for every member but the last.

### 13.6 Bounded record samples — 50,000 rows across 5 members

| Member | Window | Rows | Field fails | TS-format fails | `stdorToU` | Numeric | Zeros | Negatives | Empty | Tokens |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|
| 0 | shallow | 5,000 | 0 | 0 | Std | 4,999 | 21 | 0 | 0 | `'Null'` x1 |
| 0 | deep | 5,000 | 0 | 0 | Std | 4,999 | 0 | 0 | 0 | `'Null'` x1 |
| 42 | shallow | 5,000 | 0 | 0 | Std | 5,000 | 0 | 0 | 0 | none observed |
| 42 | deep | 5,000 | 0 | 0 | Std | 5,000 | 0 | 0 | 0 | none observed |
| 84 | shallow | 5,000 | 0 | 0 | Std | 5,000 | 13 | 0 | 0 | none observed |
| 84 | deep | 5,000 | 0 | 0 | Std | 5,000 | 0 | 0 | 0 | none observed |
| 126 | shallow | 5,000 | 0 | 0 | Std | 5,000 | 0 | 0 | 0 | none observed |
| 126 | deep | 5,000 | 0 | 0 | Std | 5,000 | 0 | 0 | 0 | none observed |
| 167 | shallow | 5,000 | 0 | 0 | ToU | 5,000 | 0 | 0 | 0 | none observed |
| 167 | deep | 5,000 | 0 | 0 | ToU | 5,000 | 0 | 0 | 0 | none observed |
| **Total** | | **50,000** | **0** | **0** | `Std` 40,000 / `ToU` 10,000 | **49,998** | **34** | **0** | **0** | `'Null'` x2 |

**Shallow and deep windows agree** on every structural measure in every member. Position within
a member does not change the structure — the residual selection risk flagged in Phase E is
**reduced**, though not eliminated.

**Zero field-count failures and zero timestamp-format failures in 50,000 rows across 5 members**
spanning both tariff blocks.

### 13.7 A new value discovered: `ToU` — VERIFIED

| Column | Values observed to date | Exact form |
|---|---|---|
| `stdorToU` | `Std`, **`ToU`** | `'Std'`, `'ToU'` — no surrounding whitespace |

Phases C-E only ever saw `Std`, because they only ever read member 0. **`ToU` is new** and was
found exactly where the census predicted it would be. Both values are unpadded, unlike the
space-padded numeric column.

**Required wording (REP-001 discipline):** other `stdorToU` values were **not observed within
this scope**. That is not a claim that the domain is exactly two values.

### 13.8 Timestamps are ordered per household, NOT per file — VERIFIED

Several sampled windows end at an *earlier* timestamp than they start:

```
member  84 shallow: 2014-01-24 08:30 .. 2012-12-12 22:30   (2 households in window)
member 126 shallow: 2013-12-19 20:00 .. 2012-03-12 10:00   (2 households in window)
```
This is **not** disorder. Each household's block is internally non-decreasing (Phase E); when the
`LCLid` changes, the timestamp restarts at that household's own earliest reading.

**Consequence:** the file is sorted by *(group, household, timestamp)*, **not** by timestamp. Any
code that assumes a globally time-ordered stream — a windowed read, an incremental watermark, an
early-exit on date — will be wrong.

### 13.9 Do the proposed ingestion rules survive Phase F?

| Rule proposed from member 0 | Verdict |
|---|---|
| 4 columns, exact names, trailing space in column 4 | **HOLDS — now census-verified across all 168** |
| Comma delimiter, CRLF line endings | **HOLDS — census-verified** |
| Timestamp `YYYY-MM-DD HH:MM:SS.fffffff` | **HOLDS** — 0 failures in 50,000 rows, 5 members |
| Numeric values are space-padded; parse after strip | **HOLDS** |
| `Null` token, unpadded, parse to NULL never 0 | **HOLDS** — seen again in member 0's deep window |
| Quarantine off-grid rows | **HOLDS** — no counter-example |
| Never fill an absent interval | **HOLDS** |
| Fail loudly on conflicting duplicates | **HOLDS** — none seen |
| ~~A household is contained in one file~~ | **BROKEN — see 13.4.** Never assumed in the rules, but it must now be explicitly forbidden. |
| ~~The stream is globally time-ordered~~ | **BROKEN — see 13.8.** |
| `stdorToU` domain | **EXTENDED** — `ToU` added; domain still not closed |

**No sampled row contradicted any parsing rule.** The two broken assumptions are about *file
organisation*, not row structure, and neither was part of the proposed parsing rules — but both
would have produced silently wrong per-household results.

### 13.10 What Phase F did NOT establish

- **Row-level uniformity beyond the sample.** 50,000 rows of ~167.9 million is 0.03%. An anomaly
  in an unsampled member remains entirely possible. Per instruction, no unobserved token is
  claimed impossible.
- **Cross-file duplicate keys.** Whether `household + timestamp` is unique *archive-wide* is
  still **UNKNOWN** and now demonstrably harder: households straddle file boundaries, so the
  check must union adjacent members.
- **The 1,000,000-row rule for the 163 unmeasured members** — INFERRED, corroborated by byte
  arithmetic, not measured.
- **Timezone, interval start-vs-end, the consumption unit, causes of any anomaly** — all
  unchanged and still **UNKNOWN**.
- **File encoding.** Headers and first rows are ASCII across all 168, but a scan for bytes >=
  0x80 in the body has never been run.

### 13.11 Status after Phase F

| Question | Status |
|---|---|
| Member count | **VERIFIED 168** |
| Header identical in every member | **VERIFIED (census)** |
| Column names, order, delimiter, line endings | **VERIFIED (census)** |
| Archive ordering scheme | **VERIFIED** — (tariff group, household, timestamp) |
| `stdorToU` domain | `Std`, `ToU` observed; **domain not closed** |
| Household IDs repeat across files | **VERIFIED YES** |
| Rows per file | **VERIFIED 1,000,000** (5 members); INFERRED archive-wide |
| Archive row total | **INFERRED 167,932,474** |
| Global time ordering | **VERIFIED absent** |
| Cross-file key uniqueness | **UNKNOWN** |
| Timezone / interval semantics | **UNKNOWN** |
| Consumption unit | **PUBLISHER-DOCUMENTED** (Phase G) |
| Cause of any zero, token, gap or duplicate | **UNKNOWN** |

**Go / no-go on billing: still NO** — timezone and interval-start-vs-end are untouched by this
phase and remain blocking.

---

*Phase F of REP-001, 2026-09-07. 168 headers censused; 50,000 sampled rows plus four declared
targeted checks; nothing extracted; `data/raw/` unmodified.*

---

## 14. Phase G — authoritative documentation research (time-boxed)

**Phase:** G — publisher-documented semantics (REP-001 sections 6, 7). **Date:** 2026-09-07.
**Method:** official sources only. No blogs, no Kaggle notebooks, no third-party interpretations.
Web search was used **only for navigation** — to locate official URLs — and nothing from a search
results page is recorded as evidence here.

**Time box: 8 network calls (6 fetches, 2 searches).** The box was reached and research stopped.
Where an answer was not found inside it, the item is preserved as UNKNOWN and designed around
(section 14.6) rather than guessed.

### 14.1 A correction to how this project applied REP-001 section 6

Section 6 says the consumption unit "must be taken from authoritative source documentation and
quoted with a citation. **Until such a citation exists**, the unit is `UNKNOWN`."

Phases C–F recorded the unit as UNKNOWN on the grounds that observed values cannot prove their own
physical unit. That was **over-strict, and it misread the rule.** Section 6 asks for a *citation*,
not an experiment. The citation has existed since Phase A. Authoritative publisher metadata defines
a **source contract**: if the contract says kWh per half-hour and reality differs, that is a
publisher defect, not an unsupported assumption on our side.

A fourth label is therefore introduced and used from here on:

| Label | Meaning |
|---|---|
| **PUBLISHER-DOCUMENTED** | Stated by the publisher in authoritative documentation, quoted with a citation. Accepted as the source contract. Not independently measured by us. |

This sits between VERIFIED (we measured it) and INFERRED (we reasoned it).

### 14.2 Sources consulted

| # | Source | URL | Coverage |
|---|---|---|---|
| 1 | London Datastore dataset page | `https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d` | full page, fetched twice (2026-09-06, 2026-09-07) |
| 2 | UK Power Networks — Low Carbon London project page | `https://innovation.ukpowernetworks.co.uk/projects/low-carbon-london/` | full page + link inventory |
| 3 | **LCL Project Closedown Report, March 2015** | `https://d1oyzg0jo3ox9g.cloudfront.net/app/uploads/2023/10/Project-Closedown-Report-March-2015.pdf` | **101 pages, 331,432 characters** searched |
| 4 | **LCL Summary Report** | `https://d1oyzg0jo3ox9g.cloudfront.net/app/uploads/2023/10/Summary-Report.pdf` | **104 pages, 279,500 characters** searched |
| 5 | Creative Commons Attribution licence deed | `https://creativecommons.org/licenses/by/4.0/` | target of the dataset page's licence link |
| 6 | Imperial College Spiral deposit (LCL dToU trial data) | `https://spiral.imperial.ac.uk/handle/10044/1/31454` | **NOT RETRIEVED — HTTP 405** |

Source 2 links directly to source 1, and sources 3 and 4 are linked from source 2, so all are
inside the permitted source rules. Source 6 is recorded as **attempted and unavailable**; nothing
from it is used.

**Search-result text is explicitly excluded.** A search snippet stated a specific dToU participant
count. It is **not recorded here** because it did not come from a fetched official document. The
figures used in this profile remain the page's own "approximately 1100" / "approximately 4500".

### 14.3 A method note — how the search was actually done, and one false result it produced

The two PDFs could not be text-extracted by the remote fetcher, but were saved locally, so they were
searched directly with `pypdf` in an **ephemeral environment outside the repository** (no project
dependency was added).

The first search pass reported **55 hits for "UTC" and 95 for "BST"** in the Closedown Report. Both
were **false**: a case-insensitive substring search matches `utc` inside "o**utc**omes" and `bst`
inside "s**ubst**ation". Re-running with word boundaries (`\bUTC\b`) returned **zero** for both.

This is recorded because it is exactly the failure this project is meant to guard against: a
plausible-looking result, confidently produced, that would have led to a *false positive* — claiming
the reports discuss timezones when they never do. The corrected counts are the ones used below.

### 14.4 Findings against the five questions

| # | Question | Answer | Label |
|---|---|---|---|
| 1 | Is `DateTime` UTC, GMT, UK local civil time, or something else? | **Not found in the sources listed in 14.2, using the searches recorded in 14.3** | **UNKNOWN** |
| 2 | Does `DateTime` mark interval start or interval end? | **Not found in those sources, using those searches** | **UNKNOWN** |
| 3 | Is the consumption unit documented as kWh per half-hour? | **YES** | **PUBLISHER-DOCUMENTED** |
| 4 | How were daylight-saving transitions represented? | **Not found in those sources, using those searches** | **UNKNOWN** |
| 5 | Are `Null`, off-grid rows, duplicates or missing readings explained? | **Not found in those sources, using those searches** | **UNKNOWN** |

**Scope of these four negatives — read this before quoting them.** They mean: *these specific search
terms did not appear in the two named reports or on the dataset page.* They do **not** mean the
semantics are undocumented in general. Substantial LCL documentation remains unexplored — see the
unopened learning-report series in 14.5 — and a document may define a convention in wording none of
our search terms would match. The correct summary is **"not found in the sources searched"**, never
"not documented anywhere".

**Evidence for the four negatives — a searched absence, not an unchecked box.** Word-boundary
searches across 205 pages and 610,932 characters of the two named reports returned:

```
UTC 0    GMT 0    BST 0    DST 0    "British Summer" 0    "local time" 0
"time zone" 0    "timezone" 0    "daylight" 0    "clock change" 0
"interval start" 0    "interval end" 0    "data dictionary" 0
LCLid 0    stdorToU 0    DateTime 0    Null 0    "missing data" 0    "duplicate" 0
```

The dataset page was separately confirmed to contain no such text. **The CSV's own column names do
not appear in either report**, which is itself informative: these two reports describe project
outcomes, not the published data files — which is a reason to expect the answer to live in a
different document rather than a reason to conclude no such document exists. No data dictionary was
found in the sources consulted within the time box.

**Evidence for question 3 — two independent publisher statements:**

> "The dataset contains energy consumption, in **kWh (per half hour)**, unique household identifier,
> date and time."
> — London Datastore dataset page, accessed 2026-09-06

> Column 4 of the header, present byte-identically in **all 168 members** (Phase F census):
> `KWH/hh (per half hour) `

The unit is therefore **PUBLISHER-DOCUMENTED as kWh per half-hour**. Phase D separately VERIFIED by
observation that the values behave as *per-interval* quantities rather than a cumulative register
(142 decreases in 299 pairs), so the documented contract and the observed behaviour agree.

### 14.5 Corroborations and one blocker resolved

**RESOLVED — the licence version. VERIFIED.** Phase A recorded the licence version as UNKNOWN
because the page displays "Creative Commons Attribution" with no version in text, and noted that
resolving it required following the linked logo. That link points to
`https://creativecommons.org/licenses/by/4.0/`, whose deed is titled **"Attribution 4.0
International"**, canonical identifier **CC BY 4.0**.

**The link belongs to THIS dataset, not to the site — checked explicitly on 2026-09-07**, because a
site-wide footer link would prove nothing about this dataset's licence:

| Check | Result |
|---|---|
| Does a licence field belong to this dataset's metadata? | **Yes** — a "Licence" field reading "Creative Commons Attribution" with a linked CC logo |
| Where does the `creativecommons.org/licenses/by/4.0/` URL appear? | **Only inside that dataset metadata field** |
| Position on the page | Between the final resource (`Tariffs (239.63 kB)`) and the `Last Update` field — i.e. within the dataset's own metadata block |
| Does any site-wide footer link to creativecommons.org? | **No** — the footer (contact, governance, standards, privacy, FAQs, accessibility, terms, credits) contains no CC link |

Because the URL occurs **only** in this dataset's licence field and nowhere in site chrome, the
version resolved through it applies to this dataset. Had it appeared in a footer, this conclusion
would have been withdrawn.

**Corroborated — the dToU price bands.** The Summary Report, p9, independently confirms the figures
Phase A took from the dataset page:

> "The values of the price bands were: High price: 67.20 pence/kWh; Mid-price: 11.76 pence/kWh; and
> Low price: 3.99 pence/kWh."
> — LCL Summary Report, p9

Note the wording difference: the dataset page calls the middle band **"normal"**, the report calls it
**"Mid-price"** and adds that it "was used as a baseline tariff". Same numbers, different labels.

**Corroborated — the 2013 dToU window.**

> "During the trials half-hourly meter reading data for the full 2013 calendar year was successfully
> collected for the meter population."
> — LCL Project Closedown Report, p15

**Context for what was published:**

> "Domestic half hourly (HH) consumption complete with socio-demographic metadata; Dynamic Time of
> Use HH consumption complete with price signal schedule"
> — LCL Project Closedown Report, p63

**A documentation trail that exists but was not opened.** Both reports cite a lettered LCL learning
report series (**A1–A11, C2, D3 …**), authored by **Imperial College London, 2014**, for the LCNF
project — for example *"Report A3 – Residential consumer responsiveness to time varying pricing"*.
These were **not** listed on the UKPN project page's download index and were not retrieved inside
the time box. They are the **single most likely remaining home for a data dictionary** and are the
first place a future phase should look.

### 14.6 Reversible ingestion design for the unresolved unknowns

Three semantics remain undocumented: **timezone**, **interval start-vs-end**, and the meaning of
zeros, tokens, gaps and duplicates. Ingestion must proceed without them, and must do so in a way
that costs nothing to revise if a document later turns up.

**The design rule: never let an unknown destroy the original, and make every output identify what
produced it.**

| Layer | Rule |
|---|---|
| **Raw** | Store `DateTime` **exactly as supplied** — the 27-character string, unparsed, unshifted. Store the consumption field as its raw string too. No conversion, no normalisation, no timezone attached. |
| **Typed** | Parse to a **naive** timestamp (no timezone) and a decimal. Parsing is not interpretation. Keep the raw string alongside. |
| **Semantic** | Timezone convention and interval anchor live in **configuration**, not code — e.g. `source_timezone = UNKNOWN`, `interval_anchor = UNKNOWN`. |
| **Derived** | Anything depending on those parameters — billing-period assignment, daily totals, DST handling — **may be stored or materialised**, and often should be for cost and speed. What matters is that it is **reproducible and re-derivable**, not that it is left uncomputed. |
| **Quarantine** | Off-grid rows, unexpected tokens and malformed rows are routed aside with a reason code, never dropped and never coerced. |
| **Stamping** | Every derived output records the four identities below, so any figure can be traced and reproduced. |

**What reproducibility actually requires.** Not "don't store derived data" — that would rule out
materialising anything. It requires that every stored output can be tied back to the exact inputs
that produced it:

| Identity | What it pins down |
|---|---|
| **Source identity** | Which raw bytes — member name plus SHA-256, as recorded in `data/manifests/raw-file-manifest.csv`. |
| **Code version** | Which transformation logic — a commit hash or release tag. |
| **Configuration version** | Which assumptions — the values of `source_timezone`, `interval_anchor` and the handling policy in force. |
| **Output / run identity** | Which execution produced this row set — a run id and timestamp, so two runs under different assumptions are distinguishable rather than one silently overwriting the other. |

**Keeping the original data is what makes correction possible.** Because the raw layer preserves the
supplied strings unchanged, a wrong assumption is repaired by re-deriving from source, not by
attempting to reverse a transformation that already lost information.

**Why this is genuinely reversible.** If the convention is learned tomorrow, you change the
configuration version and re-derive. There is no re-ingestion, because the raw layer never lost
anything; no irreversible corruption, because nothing was shifted in place; and no archaeology to
work out what the old numbers assumed, because each output names its source, code, configuration and
run. Old and new figures can then be compared directly, and the difference explained — which is the
project's stated question.

The opposite approach — converting to UTC at ingestion under a guess — destroys the original string,
and if the guess is wrong every downstream figure is silently wrong with no way to detect or reverse
it.

**This unknown is also the project's own subject matter.** The project question is *"what did we
calculate at the time, what would we calculate now, and can we explain every difference?"* An
assumption-stamped output is exactly what makes that question answerable. The unresolved semantics
are not merely an obstacle here; they are a worked example of the thing being built.

### 14.7 Status after Phase G

| Item | Status |
|---|---|
| Consumption unit | **PUBLISHER-DOCUMENTED** — kWh per half hour |
| Values are per-interval, not cumulative | **VERIFIED** (Phase D) — agrees with the contract |
| Licence version | **VERIFIED — CC BY 4.0** |
| dToU price bands | **PUBLISHER-DOCUMENTED**, corroborated in two sources |
| Timezone convention | **UNKNOWN** — not found in the 14.2 sources using the 14.3 searches |
| Interval start vs end | **UNKNOWN** — not found in those sources, those searches |
| DST representation | **UNKNOWN** — not found in those sources, those searches |
| Meaning of `Null`, gaps, duplicates, zeros | **UNKNOWN** — not found in those sources, those searches |
| A data dictionary | **not found within the time box**; other LCL documentation is unexplored |
| LCL learning reports A1–A11 | **exist, not yet retrieved** |

**Go / no-go on billing: still NO**, but the blocker has changed character. It is no longer "we
have not looked at all" — it is **"we searched two named reports and the dataset page with recorded
search terms, and did not find it."** Documentation we have not opened may still define these
conventions, so the research question stays open; what has changed is that we no longer have to wait
on it, because section 14.6 handles the unknown as a design constraint.

**A distinction that matters for scheduling work:** the unknown timezone blocks **authoritative
billing** — assigning energy to a specific billing period and defending the figure. It does **not**
block **lossless ingestion**, profiling, data-quality measurement or reconciliation, none of which
require knowing the convention. Ingestion work can proceed now; billing cannot.

---

*Phase G of REP-001, 2026-09-07. Time-boxed to 8 network calls; official sources only; no raw data
read, modified or extracted.*
