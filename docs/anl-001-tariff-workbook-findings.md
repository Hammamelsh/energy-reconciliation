# ANL-001 — Tariff workbook findings and proposed tariff model

**Date:** 2026-09-08. **Status:** inspection complete; model proposed; **no cost, bill or
saving has been calculated or published.**

## 1. Provenance

| Item | Value |
|---|---|
| File | `data/raw/Tariffs.xlsx`, 245,384 bytes |
| SHA-256 | `8a2eff6dcb737aee96cfa6c357d2947604d7f812896405c2ab5f98433d2cb150` — matches `data/manifests/raw-file-manifest.csv` |
| Read method | `openpyxl` 3.1.5 in an ephemeral environment, read-only; loaded twice (`data_only=False` for formulas, `True` for cached values) |
| Workbook properties | created 2015-06-16 14:37:47, modified 2015-06-16 14:38:46; creator recorded in the file metadata |

Every figure below is **VERIFIED** by direct read unless labelled otherwise.

## 2. Structure

| Sheet | Dimensions | Content |
|---|---|---|
| `Sheet1` | `A1:B17521` | Header row + **17,520** data rows |
| `Sheet2` | `A1:A1` | **empty** |
| `Sheet3` | `A1:A1` | **empty** |

- **Headers** (`Sheet1!A1`, `Sheet1!B1`): `TariffDateTime`, `Tariff`.
- **Formulas:** none. Every cell is a literal value; cached and formula views are identical.
- **Merged cells:** none.

## 3. Column evidence

| Column | Cells | Type | Detail |
|---|---|---|---|
| `TariffDateTime` (A2:A17521) | 17,520 non-blank | Excel datetime → naive `datetime` | min `2013-01-01 00:00`, max `2013-12-31 23:30`; **17,520 distinct, 0 duplicates**; **0 off the half-hour grid**; consecutive step is **1800 s for all 17,519 steps**; file order is sorted |
| `Tariff` (B2:B17521) | 17,520 non-blank | text | exactly three labels: `Normal` 15,072 · `Low` 1,660 · `High` 788; no padding, no blanks |

Band hours: Normal **7,536 h**, Low **830 h**, High **394 h**; non-Normal share 13.97%; 272
contiguous band runs; High occurs on 77 dates, Low on 104 dates, first on 2013-01-04/07 and
last on 2013-12-28/29.

**Daylight-saving probe.** `2013-03-31 01:00` and `01:30` (the UK spring-forward hour that
does not exist in local wall-clock time) are **present once each**; `2013-10-27 01:00` and
`01:30` (the repeated autumn hour) are present **once each**, not twice. 17,520 = 365 × 48.
**INFERRED:** the schedule is a fixed, continuous 48-slot-per-day grid with no clock-change
representation. This is consistent with a UTC/GMT-style or purely nominal convention and
**inconsistent with a local wall-clock convention.** It says nothing, on its own, about the
convention used by the *consumption* timestamps, which remains unresolved.

## 4. What the workbook provides

**A schedule of price bands. Not prices.** No numeric price, unit or currency appears in the
workbook. The prices belong to the dataset page, which is **PUBLISHER-DOCUMENTED**
(`docs/source-data-profile.md` §2, §5):

| Band label (workbook) | Page wording | Price (page) |
|---|---|---|
| `High` | "High" | 67.20 p/kWh |
| `Normal` | "normal" | 11.76 p/kWh |
| `Low` | "Low" | 3.99 p/kWh |
| — (non-ToU customers) | "flat rate tariff" | 14.228 p/kWh |

The page describes the band schedule as "the dates/times and the price signal schedule … as
part of this dataset", which is this sheet. The page states the dToU tariff applied
"throughout the 2013 calendar year period" — matching the sheet's span exactly.

## 5. Join to consumption — measured, read-only

Key tried: `readings.observed_at_naive` (naive) = `TariffDateTime` (naive). Results:

| Check | Real warehouse (members 4–5, all `Std`) | Synthetic demo |
|---|---|---|
| Readings in 2013 | 842,581 (55 households) | 12 |
| On-grid 2013 readings unmatched to the schedule | **0** | 0 |
| Off-grid 2013 readings (can never match) | 0 | 1 |
| Inner-join rows ÷ matched readings | **1.0000** — no multiplication | 1.0000 |
| Readings outside 2013 (no schedule row exists) | **1,157,419** | 0 |
| Consumption keys repeated within 2013 | 573 | 2 |
| `ToU` households loaded | **0** | 1 |

Conclusions:

- **Uniqueness holds on the schedule side**, so a join cannot multiply consumption rows.
  Repeated consumption keys are *inherited* by a join, not created by it; under the explorer
  policy exact duplicates collapse and conflicts withhold, so they must be resolved **before**
  joining, not after.
- **Coverage:** the schedule covers 2013 only. 58% of the loaded real readings lie outside it
  and would be unmatched by construction. For `ToU` households outside 2013, and for the
  flat-rate period boundaries, the page is silent — **UNKNOWN**, not zero.
- **Eligibility:** bands apply to `stdorToU = 'ToU'` households only; `Std` households take
  the flat rate. Whether the flag is fixed per household or time-varying is still AQ-23.
  **No `ToU` household is loaded in the real warehouse** (members 4–5 are the `Std` block), so
  eligibility has only been exercised on the demo. Loading a member from 135–167 is required
  before any real-data band assignment.
- **Timestamp convention is the blocker.** The join above equates two naive labels. That is
  only correct if both artefacts use the same convention. The schedule is DST-free (§3); the
  consumption timestamps' convention is *not established from the sources reviewed*. Equating
  labels is therefore an **assumption**, not a fact.

External documentation was not consulted in this phase: the only named gap is the timestamp
convention, which Phase G already searched for without result.

## 6. Proposed tariff model — validated, not yet costed

Three tables, each with the tests that would make it trustworthy.

**`dim_tariff_band_schedule`** (from `Sheet1`)

| Column | Type | Note |
|---|---|---|
| `schedule_label_naive` | TIMESTAMP (naive) | PK; the source text preserved alongside |
| `band_label` | VARCHAR | `Normal` / `High` / `Low` |
| `schedule_year` | INTEGER | 2013 |

Tests: 17,520 rows; PK unique; all on the half-hour grid; every step 1800 s; labels ∈ the
three values; workbook SHA-256 recorded with the load.

**`dim_tariff_price`** (from the dataset page, PUBLISHER-DOCUMENTED)

| `tariff_group` | `band_label` | `pence_per_kwh` DECIMAL(6,3) | `effective_from` | `effective_to` |
|---|---|---|---|---|
| `ToU` | `High` | 67.200 | 2013-01-01 | 2013-12-31 |
| `ToU` | `Normal` | 11.760 | 2013-01-01 | 2013-12-31 |
| `ToU` | `Low` | 3.990 | 2013-01-01 | 2013-12-31 |
| `Std` | (flat) | 14.228 | **UNKNOWN** | **UNKNOWN** |

Tests: exactly one price per (`tariff_group`, `band_label`) per date; no overlapping
effective ranges; citation column populated. The flat-rate dates are recorded as UNKNOWN,
never defaulted to the data span.

**`fact_interval_charge_scenario`** — deliberately named *scenario*

Joins undisputed, on-grid, deduplicated consumption to the schedule on the naive label and to
the price by (`tariff_group`, `band_label`), **carrying an `assumption_id` column** whose
first value is:

> **A1 — same-label convention.** The consumption timestamp label and the schedule label
> denote the same half hour. Not established from the sources reviewed. Reversible: the join
> key is a configuration value, and outputs are stamped with the assumption.

Tests: join row count == input row count (no multiplication); 0 unmatched on-grid 2013 `ToU`
readings; every row carries `assumption_id`; conflict-affected periods are withheld; off-grid
rows excluded and counted; Decimal arithmetic throughout with a stated rounding rule.

## 7. Two things that must stay separate

| | Assumption-labelled scenario | Historically verified cost |
|---|---|---|
| Time alignment | A1 assumed and stamped on every row | Established from documentation |
| Status | **Buildable now**, as an M3 scenario | **Blocked** on the timestamp convention |
| Presentation | Labelled "scenario under A1"; never a bill | Only after A1 is replaced by evidence |

Nothing in this document is a bill, a cost, or a saving.
