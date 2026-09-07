# Source Data Profile — Low Carbon London Smart-Meter Dataset

**Ticket:** REP-001 — Source Data Investigation
**Phase:** A — Source provenance and licence verification (page evidence only)
**Official page:** https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d
**Access date:** 2026-09-06
**Method:** Automated fetch of the official dataset page above. No dataset files have been
downloaded. No file contents have been inspected.

---

## How to read this document

Every statement carries one of three labels. This separation is the point of the document —
it is what stops a plausible-sounding claim from being treated as an established fact later.

| Label | Meaning |
|---|---|
| **VERIFIED** | Stated on the official page, quoted here. Evidence is the quotation plus the page URL. |
| **UNVERIFIED** | Not confirmed from the page as displayed text. Must be confirmed before use. |
| **INFERRED** | Derived by reasoning from VERIFIED items. Reasoning shown. Not a source statement. |
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

### Required attribution wording

- **NOT STATED ON PAGE.** No "how to cite", "attribution", "acknowledgement" or "terms of use"
  wording was found. **VERIFIED absence** — checked explicitly.
- Because a Creative Commons Attribution licence requires attribution but the publisher supplies
  no mandated sentence, we must compose one. It carries no official status.

### PROPOSED attribution (not official — our own wording)

> Contains data from *SmartMeter Energy Consumption Data in London Households*, published by UK
> Power Networks via the London Datastore, licensed under a Creative Commons Attribution licence.
> Accessed 2026-09-06 from
> https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d

**Status: PROPOSED.** This sentence was written by us, not supplied by the publisher. It
deliberately omits a licence version because none is displayed. It should be reviewed once the
licence version is confirmed, and before any public publication of derived results.

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
