# REP-001 — Verified facts

Statements we can defend **right now** with a command output, a query result, or a quotation from
authoritative publisher documentation. Each carries its evidence.

**Companion document:** [`rep-001-assumptions-and-open-questions.md`](rep-001-assumptions-and-open-questions.md).
The two lists are **non-overlapping**: no statement appears in both, and `tests/test_rep001_lists.py`
enforces that mechanically.

**Labels used here**

| Label | Meaning |
|---|---|
| **VERIFIED** | We measured it. A command and its output exist. |
| **PUBLISHER-DOCUMENTED** | Stated by the publisher in authoritative documentation, quoted with a citation. Accepted as the source contract; not independently measured. |

Anything INFERRED, UNKNOWN or unresolved belongs in the companion document, not here.

**Scope warning that applies to every row-level fact below:** unless a fact says *archive-wide*, it
was measured on **member 0 of 168** and must not be generalised.

---

## A. Provenance and licence

| ID | Fact | Evidence |
|---|---|---|
| VF-01 | Publisher, author and maintainer are **UK Power Networks**; dataset title is *SmartMeter Energy Consumption Data in London Households* | Dataset page, accessed 2026-09-06 — profile §1 |
| VF-02 | The licence is **CC BY 4.0** ("Attribution 4.0 International") | Licence link followed — profile §14.5 |
| VF-03 | That licence link sits in **this dataset's own licence metadata field**, not in site chrome; no site-wide footer links to creativecommons.org | Page position checked 2026-09-07 — profile §14.5 |
| VF-04 | The publisher supplies **no mandated attribution sentence** on the dataset page | Explicit check — profile §6 |
| VF-05 | The three dataset files originated from an **internet download** (Mark-of-the-Web `ZoneId=3` on each) | profile §9.2 |
| VF-06 | The three files' sizes match the page's stated sizes **exactly in binary units** (764.54 MiB, 758.86 MiB, 239.63 KiB) | profile §9.9 |
| VF-07 | Each file's byte size, UTC mtime, magic-byte type and SHA-256 are recorded and reproduce on demand | `data/manifests/raw-file-manifest.csv` |
| VF-08 | `data/raw/` was **not modified** across every phase: size, mtime, inode and mode identical before and after | before/after `stat` diff, every phase |

## B. Archive structure

| ID | Fact | Evidence |
|---|---|---|
| VF-09 | `Partitioned LCL Data.zip` contains **168 CSV members**, indices 0–167, no gaps, no non-CSV members, no nested archives | profile §9.5 |
| VF-10 | All **168 members** pass a CRC-32 integrity test; 8,542,826,421 bytes verified | profile §9.4 |
| VF-11 | **All 168 members share exactly one header byte-string** (single SHA-256): `LCLid,stdorToU,DateTime,KWH/hh (per half hour) `, 47 bytes + CRLF = 49 — *archive-wide census* | profile §13.2 |
| VF-12 | Comma delimiter and **CRLF** line endings in all 168 members; 4 fields in every member's first data row — *archive-wide census* | profile §13.2 |
| VF-13 | The fourth column name **ends with a space** in all 168 members | profile §13.2 |
| VF-14 | The archive is ordered **(tariff group, household ID, timestamp)**: members 0–134 are entirely `Std`, members 135–167 entirely `ToU` | profile §13.3 |
| VF-15 | The two tariff blocks hold **disjoint households** — members 4 and 135 share zero household IDs despite interleaved ID ranges | profile §13.3 |
| VF-16 | **Households span member boundaries**: `MAC000166` appears in both member 4 and member 5. `LCLid` is not unique to a file | profile §13.4 |
| VF-17 | The split rule is **exactly 1,000,000 data rows per member**, with 932,474 in the final member (measured in members 0, 4, 5, 135, 167) | profile §13.5, §15.1 |
| VF-18 | The stream is **not globally time-ordered**; timestamps restart when `LCLid` changes | profile §13.8 |
| VF-19 | `LCL-FullData.zip` contains exactly one flat CSV member, compressed with **deflate64** | profile §9.6 |
| VF-20 | `Tariffs.xlsx` is a structurally valid, uncorrupted OOXML workbook with 3 worksheet parts | profile §9.8 |

## C. Member 0, profiled in full

All from `data/profiles/lcl-june2015v2-0-profile.json`, reproducible with `uv run profile-member`.

| ID | Fact | Value |
|---|---|---|
| VF-21 | Data records, counted directly | **1,000,000** |
| VF-22 | Malformed records | **0** |
| VF-23 | Invalid timestamps | **0** |
| VF-24 | **Negative consumption values** | **0** |
| VF-25 | Empty, unexpected-token and non-finite values | **0 / 0 / 0** |
| VF-26 | Finite numeric values | 999,971 |
| VF-27 | Numeric zeros (a **subset** of VF-26) | 45,538 |
| VF-28 | `Null` tokens | 29 |
| VF-29 | Off-grid timestamps | 29 |
| VF-30 | Off-grid rows and `Null` rows are **the same 29 records** | identical record numbers |
| VF-31 | Space-padded numeric values | 999,971 — exactly VF-26, so `Null` tokens are **not** padded |
| VF-32 | Exact duplicate extra rows | 688 |
| VF-33 | Candidate key collisions (`LCLid` + raw timestamp text) | 688 |
| VF-34 | **Conflicting** duplicate groups | **0** — the source never disagrees with itself here |
| VF-35 | Distinct households; tariff values | 30; `{Std: 1,000,000}` |
| VF-36 | Backwards timestamp steps within any household | **0** |
| VF-37 | Per-household row counts sum to the record total | 1,000,000 |
| VF-38 | Bytes ≥ 0x80 in the whole 50,755,532-byte member | **0** — ASCII-compatible |
| VF-39 | All five logical partitions reconcile | see VF-40 |
| VF-40 | `physical_lines == header + logical_records` holds **for this member** (1,000,001 == 1,000,001); all CRLF, 0 lone CR | measured, not assumed |

## D. Value semantics

| ID | Fact | Evidence |
|---|---|---|
| VF-41 | Consumption values are **per-interval, not a cumulative register**: 142 decreases against 134 increases across 299 consecutive pairs, maximum value 1.164 | profile §11.3 |
| VF-42 | The consumption unit is **kWh per half hour** | PUBLISHER-DOCUMENTED — dataset page + column name present in all 168 members — profile §14.4 |
| VF-43 | The dToU price bands are High 67.20p/kWh, Mid 11.76p/kWh, Low 3.99p/kWh | PUBLISHER-DOCUMENTED — dataset page and LCL Summary Report p9 |
| VF-44 | The dToU tariff ran during the **2013 calendar year**; the dataset spans Nov 2011 – Feb 2014 | PUBLISHER-DOCUMENTED — dataset page; LCL Closedown Report p15 |
| VF-45 | The missing-value token is spelled **`Null`** — capital `N`, no surrounding whitespace | profile §12.5 |
| VF-46 | The publisher does **not** use the term "control group" for the non-dToU households anywhere on the dataset page | full-page check, profile §5 |

## E. Negative results, properly scoped

| ID | Fact | Scope |
|---|---|---|
| VF-47 | Timezone, interval start-vs-end, DST handling and the meaning of `Null`/gaps/duplicates were **not found** in the LCL Project Closedown Report (101 pp), the LCL Summary Report (104 pp) or the dataset page | 205 pages / 610,932 characters, word-boundary searches for 19 recorded terms — profile §14.4. **This is "not found in these sources", not "not documented anywhere"**; other LCL documentation is unexplored |
