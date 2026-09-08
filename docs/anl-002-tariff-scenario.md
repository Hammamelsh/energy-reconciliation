# ANL-002 — Tariff scenario: model, measurements and limits

**Date:** 2026-09-08. **Status:** built and measured. **Nothing here is a bill.** Every
charge figure is a *scenario* computed under assumption **A1**, which is not established
from the sources reviewed.

Labels used throughout: **VERIFIED** (measured here), **PUBLISHER-DOCUMENTED** (stated by
the data publisher, quoted), **INFERRED** (reasoned), **UNKNOWN**.

---

## 1. What was built

Three models, materialised in the DuckDB warehouse by
`uv run build-tariff-scenario`, plus a run registry.

| Model | What it holds | Source |
|---|---|---|
| `dim_tariff_band_schedule` | 17,520 half-hour labels → band | `data/raw/Tariffs.xlsx`, `Sheet1` |
| `dim_tariff_price` | 4 prices with units, currency, evidence and citation | the dataset page + LCL Summary Report |
| `fact_interval_charge_scenario` | one row per **charged** reading, with `assumption_id` | the two above + `readings` |
| `fact_interval_charge_exclusion` | one row per **uncharged** reading, with a reason | same |
| `scenario_run` | the identity of the run that produced them | — |

**The schedule and the prices are kept apart on purpose.** The workbook contains a
schedule of price bands and **no price at all** — no number, no unit, no currency
(ANL-001 §4). The prices are separate evidence with their own citation, and the join
between them is explicit rather than assumed.

**The flat rate's effective dates are `NULL`, meaning UNKNOWN.** The publisher gives the
price (14.228 p/kWh) and not the period it applied to. They are never defaulted to the
span of the data: when meters reported is evidence about meters, not about prices.

## 2. The calculation

```
energy_charge_gbp = consumption_kwh × price_pence_per_kwh ÷ 100
```

**Precision.** `consumption_kwh` is `DECIMAL(28,10)` exactly as ingested. Prices are
`DECIMAL(9,4)` in pence and `DECIMAL(9,6)` in pounds. The row-level charge is
`DECIMAL(38,16)`; sums are `DECIMAL(38,16)`. Every one of these is exact.

**Rounding.** **None per row.** Rounding happens once, at the output stage: money to 2
decimal places, energy to 3, shares to 4, all `ROUND_HALF_UP`, and the exact unrounded
figure is carried beside every rounded one. No rounding drift can accumulate across
456,096 rows because no row is ever rounded.

**A defect found and avoided — VERIFIED.** That `÷ 100` is *not* written literally in
SQL. DuckDB evaluates a `DECIMAL` divided by an integer as `DOUBLE`:

```sql
SELECT 1.1250000000::DECIMAL(28,10) * 67.2000::DECIMAL(9,4) / 100;  -- 0.7559999999999999 (DOUBLE)
SELECT 1.1250000000::DECIMAL(28,10) * 0.672000::DECIMAL(9,6);       -- 0.7560000000000000 (DECIMAL(37,16))
```

So the division is done **once, in Python `Decimal`**, when the price catalogue is
built — every documented price has at most three decimal places in pence, so it is
exact — and the fact multiplies by the stored pounds price. `tests/test_tariff.py`
asserts the equality for all four catalogue prices.

**What this charge is not.** A historical scenario **energy** charge only: consumption ×
band price, and nothing else. **No separate tax adjustment is applied.** Whether the
published rates are quoted inclusive or exclusive of VAT or any levy is **not
established** from the sources reviewed — the publisher gives figures in pence per kWh
and does not state their tax treatment — so this figure must not be described as either
including or excluding tax. No standing charge, discount, capacity or metering charge and
no settlement adjustment is modelled. No one was ever billed this.

### 2.1 Validity is a half-open interval

A price applies on `[effective_from, effective_until)`: *from* is the first instant it
applies, *until* is the first instant it no longer does. The dToU year is therefore
**`[2013-01-01, 2014-01-01)`**. An inclusive end date would be a trap: compared against a
timestamp, `DATE '2013-12-31'` is `2013-12-31 00:00:00`, and the last 47 half hours of
the year silently fall outside it. A `NULL` bound is **UNKNOWN, not open-ended** — a price
with unknown validity prices nothing, which is why no `Std` reading is costed.

The price join enforces the interval, and it is checked **independently** of the
schedule's coverage: a label the schedule carries but no price covers is excluded as
`unpriced_band`, visible with a reason, never charged at zero. Verified through the whole
build at 2012-12-31 23:30 (outside), 2013-01-01 00:00, 2013-12-31 00:00, 00:30 and 23:30
(all charged) and 2014-01-01 00:00 (outside); enforcing the interval changed **no** real
figure, because the interval and the schedule's coverage coincide.

**A measured zero is charged at zero.** 133 of the 456,096 charged readings carry
`consumption_kwh = 0` and therefore `energy_charge_gbp = 0`; none has a zero charge with
non-zero kWh, and no excluded reading appears in the fact table. Zero *readings* are
measurements; excluded readings have no charge row at all. The two are not the same.

**Overflow is loud.** Products are `DECIMAL(37,16)`, sums `DECIMAL(38,16)`; DuckDB raises
`OutOfRangeException` on overflow rather than wrapping, so the failure mode is an error,
never a wrong total.

## 3. The assumption, stored with the output

> **A1 — same-label convention.** A consumption timestamp label and a tariff schedule
> label denote corresponding half-hour intervals.

`A1` is a column on **every** row of `fact_interval_charge_scenario` and on the run
record. It cannot be read off without it.

**Two things that are *not* evidence for A1, and are recorded as such:**

- **Regularity is not a timezone.** The schedule has 17,520 labels (365 × 48), every
  step exactly 1800 seconds, and both 2013 clock-change hours present once each. That
  shows the *schedule* is a fixed nominal grid with no daylight-saving representation.
  It is a fact about the workbook and says nothing about the convention used by the
  *consumption* timestamps, which remains UNKNOWN (AQ-01/AQ-02/AQ-03).
- **A unique key is not semantic alignment.** The schedule label is a primary key, and a
  duplicate is refused before a single row is loaded. That guarantees a join **cannot
  multiply** consumption rows. It is an arithmetic property of the join. It is not
  evidence that the two label sets mean the same half hour.

**Repeated identical labels remain semantically unresolved.** The duplicate policy
collapses them; that is our analytical resolution, not proof that two rows carrying one
label are one physical interval. `tests/test_tariff.py` pins this behaviour on the
2013-10-27 01:00 label and states in the test itself what the test does not establish.

## 4. Which policies apply, and where a figure is withheld

The duplicate, conflict, missing-value and off-grid rules are the ones ING-001 decided,
imported from one module (`src/energy_reconciliation/policy.py`) by both the explorer and
these models. There is one implementation, not two.

| Condition | Effect on the scenario |
|---|---|
| Exact duplicate rows | Collapsed; charged **once**; the count collapsed is reported |
| Equivalent representations (`0.5` / `0.50`) | One value; charged **once**; both rows kept as evidence |
| Conflicting label (incl. `Null` beside a number) | **Every** reading at that label is excluded; no charge, no aggregate for it |
| Missing value (`Null`) | Excluded; **never zero** |
| Off-grid observation | Excluded from the half-hour scenario; counted and listed |
| Outside the schedule's coverage | Excluded; **no charge exists**, not a zero |
| Ineligible tariff group | Excluded; band prices apply to `ToU` only |

**Withheld aggregate versus scoped subtotal.** A conflict withholds *that label*, and
every subtotal is then a **scoped** subtotal: it covers the readings that were charged,
and the excluded count with reasons is published beside it. Nothing is silently dropped
and nothing becomes zero. The single reconciliation identity is:

```
distinct readings in scope = charged + excluded (each with one reason)
```

**How a reason is chosen.** A reading can satisfy several conditions at once, so each is
stored as its own boolean and `exclusion_reason` is the **first** that applies in this
fixed order: ineligible group → outside schedule period → conflicting label → off-grid →
missing value → unmatched label → unpriced band. Eligibility and coverage come first
because they say a charge could not exist at all; a Standard-tariff reading from 2011 is
out of scope, not a defect. The ordering cannot hide anything, because every condition is
also stored on the row.

## 5. The loaded sample — VERIFIED

Member **135** of `Partitioned LCL Data.zip` was loaded beside the existing members 4 and
5. Members 4 and 5 (`Std`) and the synthetic demo remain **separate evidence contexts**
and were not disturbed.

| | Member 135 |
|---|---|
| Records read / published / rejected | 1,000,000 / 1,000,000 / 0 |
| Tariff groups present | **`ToU` only** |
| Households | 27 |
| Recorded span | 2011-11-23 10:00 → 2014-02-28 00:00 |
| Rows in 2013 | 456,408 |
| `Null` tokens | 27 — **all 27 also off-grid**, all in 2012 |
| Households recorded under more than one tariff group | **0** (measured, all three members) |

**These 27 households are a bounded, non-representative subset.** They are the
households that happen to occupy one member of 168, chosen because member 135 is the
first of the `ToU` block — not a sample drawn from the trial by any procedure. Nothing
measured over them is representative of the trial, of London, or of anyone else, and no
figure here should be scaled up.

**Whether `stdorToU` is fixed per household or varies over time (AQ-22/AQ-23) is still
not settled.** What is now measured is that **no loaded household is recorded under two
groups** — consistent with a fixed flag, and not proof of one, since only 3 of 168
members are loaded.

## 6. Accounting — VERIFIED, reconciles exactly

Scope: the whole warehouse (members 4, 5, 135), schedule coverage 2013-01-01 to
2013-12-31, tariff group `ToU`.

| | Readings |
|---|---:|
| Rows recorded | 3,000,000 |
| Collapsed by policy (identical rows, equivalent representations) | 2,038 |
| **Distinct readings** | **2,997,962** |
| Charged | 456,096 |
| Excluded, with a reason | 2,541,866 |
| — `ineligible_tariff_group` (members 4 and 5 are `Std`) | 1,998,647 |
| — `outside_schedule_period` (`ToU` readings in 2011, 2012, 2014) | 543,219 |
| **Reconciles** (`charged + excluded = distinct`) | **True** |

**Zero conflicts, zero missing values and zero off-grid rows were *assigned* in the 2013
`ToU` scope** — not because none exist, but because member 135's 27 `Null`/off-grid rows
all fall in 2012 and are therefore excluded as `outside_schedule_period` first. Their
`is_off_grid` and `is_missing_value` flags remain set on those rows. Across the whole
exclusion table, 81 readings are flagged off-grid and 81 flagged missing — the same
correlation REP-001 found at every scale so far.

456,408 raw `ToU` rows in 2013 minus 312 collapsed duplicates = **456,096 charged**, so
**every** distinct on-grid `ToU` reading in 2013 matched a schedule label. Zero unmatched.

## 7. The measurements

### 7.1 Schedule-wide — describes the published schedule, not anyone's consumption

| Band | Half-hour slots | Hours | Share of 17,520 slots | Price |
|---|---:|---:|---:|---:|
| `Normal` | 15,072 | 7,536 | 86.03% | 11.76 p/kWh |
| `Low` | 1,660 | 830 | 9.47% | 3.99 p/kWh |
| `High` | 788 | 394 | 4.50% | 67.20 p/kWh |

`High` slots by hour of the schedule label, across 2013: **68 in each of the hours
17, 18, 19, 20, 21 and 22**, against 18–26 in every other hour. By month, `High` peaks in
December (102 slots) and February (98) and is lowest in August (12).

### 7.2 Loaded households — 27 `ToU` households, 2013 only

Denominators, stated: **85,467.1329968 kWh** charged and **£11,675.4339216532500000**
scenario charge. Both cover only the readings this run charged.

| Band | Charged readings | kWh (exact) | Scenario charge (exact) | Share of kWh | Share of charge |
|---|---:|---:|---:|---:|---:|
| `Normal` | 392,515 | 72,325.8739944 | £8,505.5227817414400000 | 84.62% | 72.85% |
| `Low` | 43,081 | 8,955.8850019 | £357.3398115758100000 | 10.48% | 3.06% |
| `High` | 20,500 | 4,185.3740005 | £2,812.5713283360000000 | 4.90% | 24.09% |

Scenario charge by source month, all 27 households: highest December £1,250.71, lowest
August £670.04.

### 7.3 Independent check — VERIFIED

The whole 2013 `ToU` charge was recomputed **outside the model**, in pure Python
`Decimal`, reading the workbook and the readings directly and applying
`kwh × pence ÷ 100` literally per row. It agrees to every digit:

| | Charged readings | Total |
|---|---:|---|
| SQL model | 456,096 | `11675.4339216532500000` |
| Independent Python `Decimal` | 456,096 | `11675.433921653250` |
| Replay into a fresh database | 456,096 | `11675.4339216532500000` |

Per band it also agrees exactly: `High` `2812.571328336000`, `Normal`
`8505.522781741440`, `Low` `357.339811575810`. This is a second implementation used
**once, as a check** — it is not kept in the codebase, so there is no second policy
implementation to drift.

## 8. Three findings, and what each does not show

**Finding 1 — the price ratio dominates the charge, arithmetically.** `High` half hours
carry **4.90%** of the charged kWh and **24.09%** of the scenario charge; `Low` carries
**10.48%** of the kWh and **3.06%** of the charge. *What it does not show:* anything about
behaviour. It follows from the price ratio (67.20 : 11.76 : 3.99 ≈ 17 : 3 : 1) and the
timing of the bands. It is a property of the tariff, restated in this sample's numbers.

**Finding 2 — the expensive band sits in the evening, and so does consumption.** The
schedule places 68 `High` half-hour slots in each of the hours 17–22, against 18–26
elsewhere. In the loaded sample, **2,668.2 of the 4,185.4 `High`-band kWh (63.7%)** fall
in those same hours. *What it does not show:* that anyone responded to a price signal, or
failed to. There is no comparison group in this measurement, no before-and-after, and no
counterfactual; hours 17–22 are the household evening peak in the `Normal` band too
(3,907–4,380 kWh per hour, the highest of the day). Two things being concentrated in the
same hours is not evidence that one caused the other.

**Finding 3 — one household's small charge reflects limited observed coverage.** 26 of
the 27 households are charged for 17,375–17,520 of the 17,520 possible 2013 half hours.
`MAC000146` is charged for **864** — exactly the 48 half hours of each of the 18 days
2013-01-01 to 2013-01-18 — and has the smallest scenario charge in the sample, £16.64.

VERIFIED: its readings occupy records 1–7,441 of member 135, the next household begins at
record 7,442, and no reading for it is recorded after 2013-01-18 **in the loaded
members**. Because it is the first household in the member, whether more of its history
lies in member 134 is **not established** — 134 is not loaded, and this is not a reason to
load it.

*What it does not show:* low usage, a withdrawal, a meter fault, or any other cause. The
observed coverage is short; **why readings are absent is not established and is not
guessed at here.** A per-household charge that is not read alongside its charged-reading
count will be wrong about this household by a factor of twenty, which is why the explorer
shows the two together.

## 9. Reproducing a result — executed, not asserted

Every published run records enough to rebuild it: the schedule source and its SHA-256, a
digest of the schedule contents, the price catalogue version, a digest of the modelling
code and `policy.py`, the ingestion pipeline fingerprint, the exact set of published load
ids, the assumption ids, and the exact unrounded total. Rerunning with all of those
unchanged is a **no-op**; changing any one of them supersedes the previous run and
rebuilds. The whole build is one transaction, so a failure leaves the previous published
scenario untouched.

### 9.1 What participates in invalidation

Named file by file in `src/energy_reconciliation/tariff/identity.py`, not inferred from a
package directory. **A package-local source hash is not evidence that an imported shared
file is covered**, so the covered set is an explicit list of 17 files — the tariff models,
`policy.py`, and the whole of `ingest` and `profiling` — and a test takes the **real import
closure of the models in a fresh interpreter** and fails if anything in it is missing.

Reporting code is deliberately **outside** the set: `analytics.py`, the CLIs and the
baseline tooling cannot change a stored figure, and including them would invalidate every
result whenever a print statement moved.

Recorded alongside: the Python and library versions that evaluated the arithmetic
(`runtime_fingerprint`, folded into the scenario fingerprint — a different decimal engine
is a different calculation), the price catalogue version, the assumption id, the schedule
contents and the **content identity of every loaded member**.

### 9.2 Baseline and replay

A fingerprint stored inside a mutable warehouse is **not** historical replay: it detects
that the inputs changed, but cannot rebuild what came before. So a baseline is written to
`data/baselines/` (git-ignored) before any new member is loaded, naming the exact members
by decompressed content digest, the calculation identity, the runtime, and the result
broken down per band, per household and per exclusion reason.

```bash
uv run capture-baseline --database data/warehouse/energy.duckdb
uv run replay-baseline  --baseline data/baselines/<id>.json
```

Replay refuses to touch an existing database, re-ingests each recorded member after
checking its content digest, rebuilds, and compares field by field.

**What a replay establishes, exactly.** The comparison covers the accounting ladder,
the exact total, every per-band charge and count, every exclusion-reason count, all 27
per-household charges, the scenario fingerprint — and, from the baseline captured after
this review, a **SHA-256 over every charged row** (household, label, band, kWh, charge)
in a fixed order. Baselines captured before that hold aggregates only and say so; for
them a replay proves numerical and identity preservation, not row-level lineage.

**Executed, not asserted.** The newest baseline replayed into a fresh database with
**all 17 compared fields matching**, the row digest included.

### 9.3 Two defects the replay found

Neither was visible from tests that only ever built one warehouse.

1. **The fingerprint was over-sensitive.** It hashed `tariff/*.py` by directory glob, so
   adding the replay tooling changed the fingerprint of a scenario whose every figure was
   identical. A signal that fires on unrelated edits gets ignored. The covered set is now
   an explicit list of files that can change a **stored** figure.
2. **The fingerprint was not reproducible at all.** It included the published `load_id`s,
   and a load id embeds the moment of loading — so two databases holding byte-identical
   rows fingerprinted differently, and no replay could ever have matched. It now keys on
   member name, decompressed content digest and pipeline fingerprint. The load ids are
   still recorded as provenance.

### 9.4 Current published run over members 4, 5 and 135

| | |
|---|---|
| Schedule | `Tariffs.xlsx`, 17,520 labels, SHA-256 `8a2eff6dcb737aee…` (matches the manifest) |
| Coverage | 2013-01-01 00:00 → 2013-12-31 23:30 |
| Prices | catalogue `2026-09-08.1`, PUBLISHER-DOCUMENTED |
| Assumption | `A1` |
| Runtime | Python 3.12.14 CPython, duckdb 1.5.5, pyarrow 25.0.1, pandas 3.0.5, openpyxl 3.1.5 |
| Exact scenario charge | £11675.4339216532500000 |

### 9.5 Schema compatibility, kept separate from content identity

Two different questions, deliberately not conflated:

| Question | Answered by | Failure looks like |
|---|---|---|
| Can this code read these columns? | `analytics.scenario_availability` | a recovery instruction in the tariff tab |
| Is the stored result still current? | the scenario fingerprint | a rebuild on the next `build-tariff-scenario` |

**This was not hypothetical.** A Streamlit server that had imported `analytics.py` before
a rebuild kept the old module — the tariff package sits outside Streamlit's reload scope
unless `PYTHONPATH=src` is set — while `build-tariff-scenario` migrated `scenario_run`
underneath it. The old SQL asked for `tariff_code_sha256`, the table now had
`calculation_code_sha256`, and DuckDB raised a `BinderException` from the middle of the
page. Because a Streamlit script runs top to bottom, that also stopped everything below
it from rendering.

Three things changed as a result, none of them a migration — the database was already
correct:

1. `latest_run` compares the persisted columns against what it needs **before** the
   SELECT runs, and raises a typed `ScenarioSchemaError` rather than returning `None`:
   "never built" and "cannot be read" must not look alike.
2. The tariff tab renders the diagnosis and both recoveries — restart first, rebuild only
   if it survives a restart — and states that readings, load history and baselines are
   untouched either way. Only this recognised condition is contained; nothing else is
   caught.
3. The tariff section is written **last** in the script, so a failure there cannot stop
   the other three tabs from rendering. Tab order comes from `st.tabs`, not from this.

Extra unknown columns are **not** treated as a fault: only a column the code needs and
cannot find makes a schema unreadable.

### 9.6 A deliberate over-sensitivity that remains

The covered files are hashed **byte for byte**, so editing a docstring in `models.py`
invalidates the scenario and forces a rebuild even though no figure can change. That is
kept: the alternative is hashing something semantic, which means deciding which byte
changes are meaningful — and getting that wrong fails silently, in the direction of
reusing a result that should have been rebuilt. A spurious rebuild costs eight seconds.
The scope of the set is where the judgement is exercised, not the strictness within it.

### 9.7 Not covered by any digest here

The operating system, the CPU, locale, and the DuckDB build. Two runs agreeing on every
digest above can still, in principle, differ.

## 10. Limits

- **A1 is unresolved.** Until the timestamp convention is established, this is a scenario
  and cannot become a historical cost. ANL-001 §7 keeps the two apart.
- **3 members of 168 are loaded**, and one `ToU` member is not a sample of the trial.
- **The flat-rate period is UNKNOWN**, so no `Std` household has been costed at all.
- **The dToU schedule covers 2013 only.** 543,219 loaded `ToU` readings lie outside it and
  have no charge — not a zero charge.
- **Not in dbt.** The roadmap places these models in M3 with dbt, and **M3's dbt
  deliverable is not met**. Writing them as standalone SELECTs means the port starts from
  working, tested SQL rather than from scratch — it does **not** make the port a
  copy-and-paste. dbt would need model boundaries and materialisations chosen,
  `ref`/`source` wiring, the Python-side workbook read and price catalogue handled outside
  SQL, the rerun-and-supersede policy re-expressed, and the shared policy kept to one
  definition rather than duplicated in Jinja. See ANL-003 in `docs/roadmap.md`.
- **No geography.** No geographic breakdown is produced or implied. One would be
  legitimate **only** from metadata properly linked to these households; none has been
  linked, and no geographic research was done for this task.
- **No forecasting, no AI feature, no savings claim, no bill.** None was built, and none
  is implied by anything above.
