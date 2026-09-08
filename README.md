# Energy Reconciliation

Tools and analysis for half-hourly electricity meter data from the Low Carbon London trial.

What exists today:

- a **profiler** that reads one CSV member, classifies every value and writes a JSON report whose
  totals reconcile;
- an **ingestion command** that loads members into a local DuckDB database with a stable schema;
- a **household explorer** for looking at one household's data quality;
- a **tariff scenario**: the dToU band schedule and the publisher-documented prices, modelled in
  DuckDB and joined to consumption under a clearly stated, stored assumption.

This is the groundwork for billing and reconciliation work. It is not a billing system and produces
no bills. The tariff figures are a **scenario**, not a cost anyone was charged — see
[Tariff scenario](#tariff-scenario) below for exactly what that means.

## Try it without downloading anything

The repository includes a tiny synthetic archive so you can run the profiler immediately.

```bash
git clone https://github.com/Hammamelsh/energy-reconciliation.git
cd energy-reconciliation
uv sync

uv run profile-member \
  --archive data/demo/demo-lcl-sample.zip \
  --member "Small LCL Data/DEMO-sample_0.csv" \
  --output data/demo/demo-profile.json \
  --no-examples
```

```
status                : COMPLETE
member                : Small LCL Data/DEMO-sample_0.csv
data records          : 12
structurally valid    : 12
malformed             : 0
records ok            : 11
records with issues   : 1
header matches        : True
core partitions hold  : True
one line per record   : True
```

`data/demo/demo-lcl-sample.zip` is **invented data**, not a sample of the real dataset. It has 12
records for two made-up households, `DEMO0001` and `DEMO0002`, and contains one of everything worth
seeing: a zero reading, a `Null`, an exact duplicate row, two rows that share a household and
timestamp but disagree on the value, and a timestamp that is not on the half-hour. The counts above
are checked against hand-computed values in `tests/test_demo.py`.

Read the report it writes at `data/demo/demo-profile.json`.

**Exit status:** `0` when the run completes and the counts reconcile, `1` if the report was written
but is incomplete or a core reconciliation failed, `2` if the archive is missing.

## Explore household energy use

Load the synthetic demo into a local DuckDB database and browse it:

```bash
uv run ingest-member --demo --database data/warehouse/demo.duckdb
uv run build-tariff-scenario --demo --database data/warehouse/demo.duckdb
PYTHONPATH=src uv run streamlit run src/energy_reconciliation/explorer/app.py
```

`PYTHONPATH=src` matters while editing. Streamlit's file watcher only reloads modules in the
folder holding the script or on `PYTHONPATH`, so without it `policy.py`, `tariff/` and `ingest/`
stay loaded from their first import: edits to them appear to have no effect, and a half-applied
change can raise an `AttributeError` from a module the rest of the app has already moved past.
With it, every project module is watched. After changing model code, restarting the server is
still the certain option.

Choose the dataset under **Data source** in the sidebar — each option is labelled by what
it contains (synthetic demo, or which Low Carbon London members are loaded). Household and
period sit at the top of the page. Period presets of 7, 14 and 30 days are anchored to the
**last date recorded for that household**, not to today; the trial ended in 2014, so a window
around the current date would be empty. *Custom* exposes explicit start and end dates.

Everything on the page is computed for the same household and the same source-date range:

- **Overview** — recorded kWh, contributing readings, and items for review (missing values
  + gaps + conflicting timestamps + off-grid observations in the period); a status that says what was and
  was not detected, with the standing caveat that boundary coverage and clock semantics are
  unresolved; daily bars grouped by source date, with a day inside the recorded span but
  with no rows shown as "no readings recorded" rather than omitted; half-hour detail for a
  chosen day, with the line broken at gaps.
- **Data quality** — the counters for the period, findings first (conflicts, gaps, repeated
  timestamps, missing values) with source references, definitions collapsed below, and the
  whole-history figures in a separately labelled expander.
- **Tariff scenario** — the band schedule, the prices, and the scenario charge under
  assumption `A1`, for this household and for every charged household, with the schedule's
  own shape kept separate from what the loaded households did. See below.
- **Forecast (backtest)** — observed against predicted for one forecast origin, and the
  baseline comparison by model and horizon, with the prediction target, origin, horizon and
  evaluation scope all stated on the page.
- **Source records** — rows exactly as loaded, paginated, each with its member and record
  number, followed by the loaded-file inventory.

Identical source rows are collapsed and the number collapsed is always shown. One value
written two ways at the same timestamp (`0.5` and `0.50`) is kept as evidence and counted
once. Different values at the same timestamp — including a `Null` beside a number, by our
analytical policy — are a conflict: that day and the period have their totals withheld — shown as a labelled marker, never a bar — while the readings
that exist stay visible. Gaps are steps over half an hour between consecutive grid
timestamps, counted across midnight and attributed to the later date. Off-grid observations are
excluded from half-hour totals but stay counted, listed and plotted with their source reference.

With the real dataset, load two adjacent members:

```bash
uv run ingest-member \
  --member "Small LCL Data/LCL-June2015v2_4.csv" \
  --member "Small LCL Data/LCL-June2015v2_5.csv"
PYTHONPATH=src uv run streamlit run src/energy_reconciliation/explorer/app.py
```

Those two members share household `MAC000166`, whose readings run to `2012-02-14 15:00`
in member 4 and continue from `15:30` in member 5 — a good household to select first.

Members 0–134 hold only `Std` households, so add member 135 for the `ToU` group the dynamic
tariff applies to:

```bash
uv run ingest-member --member "Small LCL Data/LCL-June2015v2_135.csv"
```

Re-running an ingest is a no-op only when **both** the source file and the
transformation code are unchanged. Changing either replaces that member's rows, so a
code change rebuilds rather than silently keeping rows built by older logic. Superseded
loads stay in the registry as history, though their readings are replaced.

Three members out of 168 are not a household's complete history, and the explorer says so
on every page.

## Tariff scenario

The dynamic Time-of-Use tariff ran through 2013. `Tariffs.xlsx` supplies **a schedule of price
bands and no prices at all** — the prices are on the dataset page. Both are modelled, separately:

```bash
uv run build-tariff-scenario --demo --database data/warehouse/demo.duckdb   # synthetic schedule
uv run build-tariff-scenario --database data/warehouse/energy.duckdb        # the real workbook
```

Then open the **Tariff scenario** tab in the explorer.

If that tab reports it cannot read the scenario, the running process and the database were
written by different generations of the code — usually a long-lived server against a
rebuilt database. **Restart the app first**; that loads the current code and rebuilds
nothing. Only if the message survives a restart is `build-tariff-scenario` the fix. Either
way your readings, load history and baselines are untouched: the tariff tables are derived.
The other three tabs keep working throughout.

```
energy_charge_gbp = consumption_kwh × price_pence_per_kwh ÷ 100
```

All `Decimal`. **Nothing is rounded per row**; rounding happens once for display, to 2 decimal
places for money, half up, with the exact unrounded figure shown beside it. The `÷ 100` is done in
Python when the price catalogue is built, not in SQL, because DuckDB evaluates a `DECIMAL` divided
by 100 as a binary float.

**This is a scenario, not a bill.** Every charged row carries assumption `A1`:

> the consumption timestamp label and the schedule label denote corresponding half-hour intervals

That is **not established**. The consumption timestamps carry no timezone. The schedule's own
regularity — 17,520 labels, exact half-hour steps, both 2013 clock-change hours present once —
shows the schedule is a fixed nominal grid, and says nothing about the consumption data. A unique
schedule key stops the join multiplying rows; that is arithmetic, not semantics.

The charge is an **energy** charge only. **No separate tax adjustment is applied**, and whether
the published rates are quoted inclusive or exclusive of VAT or any levy is **not established** —
the publisher gives pence per kWh and does not say. No standing charge, discount or settlement
adjustment is modelled. No one was ever billed it.

**Nothing becomes zero.** Every distinct reading is either charged or excluded with one explicit
reason — ineligible tariff group, outside the schedule's coverage, conflicting readings, off-grid,
missing value, unmatched label — and `charged + excluded = distinct readings` is asserted on every
run.

The tab has three separate views — **selected household**, **loaded ToU sample**, **published
schedule** — with their own period control, bounded by the schedule's coverage and independent of
the period selector at the top of the page. A household with no charged readings is told the
**measured** reason with its count, and offered an explicit button to switch to one that has some.

### Reproducing a result

A fingerprint stored inside a warehouse is not historical replay: the warehouse is mutable, and
once another member is loaded the rows the fingerprint described are gone. So capture a baseline
first, then rebuild from it into a database that does not yet exist:

```bash
uv run capture-baseline --database data/warehouse/energy.duckdb
uv run replay-baseline  --baseline data/baselines/<id>.json
```

Replay re-ingests each recorded member after checking its decompressed content digest, rebuilds,
and compares field by field — per band, per household, per exclusion reason, the fingerprint, and
a digest over every charged row. It exits non-zero if anything differs. Baselines are git-ignored.

Measurements over members 4, 5 and 135 (27 real `ToU` households, 2013), what they show and what
they do not: [`docs/anl-002-tariff-scenario.md`](docs/anl-002-tariff-scenario.md).

## Forecasting (backtest)

How much of a household's next week is predictable from its own past daily totals?

```bash
uv run run-forecast-experiment --database data/warehouse/energy.duckdb
```

Then open the **Forecast (backtest)** tab. The target is one household's recorded
consumption, in kWh, grouped by **source-date label** — a grouping of labels as written,
whose correspondence to a local calendar day is not established, and not proof the meter
covered the whole day.

Two baselines are compared, plus a persistence reference: the same source weekday from the
previous week, and a four-week same-weekday mean. Origins roll weekly, each model sees only
data dated on or before its origin, and the final 28 days of each household's run are an
holdout scored once. **Holdout MAE: 1.901 kWh for the four-week mean**, against 2.121 for
the one-week naive, over holdout target days averaging 10.1 kWh. The forty households are
a retrospective, clean-run cohort chosen by data criteria, not an operational sample.

A model that needs an unusable day **declines** and says why. Nothing is filled with zero,
no absent date is bridged, and a partial date is never treated as whole. MAE is used rather
than MAPE because 975 daily totals in the loaded data are exactly zero.

This is a **historical backtest, not a live forecast**, and it is not a bill, a saving, an
appliance claim or a statement about tariff response. Details and limits:
[`docs/fore-001-forecasting-experiment.md`](docs/fore-001-forecasting-experiment.md).

## Tests

```bash
uv run pytest -q
```

305 tests, all synthetic. **No dataset needed** — every fixture builds a small zip archive in a
temporary directory. The tariff tests check hand-computed figures written in each test's
docstring: price-unit conversion, band boundaries, a duplicated schedule key, an unmatched
reading, readings outside the schedule period, conflicts, and repeated autumn timestamp labels.
Others assert the rendered chart specification, that every scope's two shares come from the same
rows, that an empty selection produces no zero substitutes, and that the calculation fingerprint
covers the shared policy module — checked against the models' real import closure, not assumed.

## What the profiler does

- Streams one member out of the zip without extracting it. The archive is opened read-only.
- Uses about 39 MB of memory for a million rows. Duplicate detection goes through a temporary
  SQLite database rather than holding rows in memory.
- Parses consumption with `Decimal`. `NaN` and `Infinity` are rejected into their own category
  rather than accepted as numbers.
- Validates timestamps against the observed format and keeps the original text. It attaches no
  timezone and converts nothing.
- Puts every record in exactly one category and states which counters are mutually exclusive and
  which overlap, so the totals can be checked.

Options and output layout: [`docs/profiling.md`](docs/profiling.md).

## Results from the real dataset

One member (`LCL-June2015v2_0.csv`) of the 168 in the archive, read in full. These numbers describe
that member only.

| | |
|---|---:|
| Data records | 1,000,000 |
| Malformed records | 0 |
| Records with no validation issue | 999,971 |
| Finite numeric values | 999,971 |
| `Null` tokens | 29 |
| Zeros (part of the finite values) | 45,538 |
| Negative values | 0 |
| Invalid timestamps | 0 |
| Timestamps off the half-hour | 29 |
| Exact duplicate rows | 688 |
| Household + timestamp collisions | 688 |
| Collisions where the value disagreed | 0 |
| Households | 30 |
| Runtime / peak memory | ~11 s / ~39 MB |

Consumption, over the 999,971 finite values. Count, minimum, maximum and sum are exact — accumulated
with `Decimal` while streaming. The mean is the only rounded figure. Percentiles use nearest rank, so
each one is a value that actually appears in the data.

| | |
|---|---:|
| Minimum | `0` |
| Median | `0.129` |
| 95th / 99th percentile | `0.829` / `1.85` |
| Maximum | `6.5279999` |
| Mean | `0.239579733` |
| Sum | `239572.7849879` |

The distribution is heavily skewed: the maximum is about fifty times the median. Some values carry
seven decimal places, such as `6.5279999` and `6.5100002`. Why the source stores them that way is
unknown, and the profiler reports them as they appear rather than rounding them.

Full report: [`data/profiles/lcl-june2015v2-0-profile.json`](data/profiles/lcl-june2015v2-0-profile.json).

## Running on the real dataset

The raw data is about 1.5 GB and is not in this repository; `data/raw/` is git-ignored.

1. Download from the London Datastore:
   <https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d>
2. Put `Partitioned LCL Data.zip` in `data/raw/`. Leave it zipped.
3. Run `uv run profile-member`.

To check what you downloaded, [`data/manifests/raw-file-manifest.csv`](data/manifests/raw-file-manifest.csv)
records the sizes and SHA-256 of each file. The partitioned archive is 795,722,689 bytes,
SHA-256 `149a6a9c43c622fd0a14b7d11be055665317d3018d9fb7e1043bd51420bfaea5`.

## Why the profiler counts what it counts

Three things decide whether a total built from this data is correct.

**Missing is not zero.** A `Null` or an absent row means the meter did not report. Zero means it
reported no consumption. Treating the first as the second understates a real customer's usage, and
nothing raises an error when it happens. The profiler counts them as separate categories and fills
nothing in.

**Duplicates come in two kinds.** Two rows can be identical, or they can share a household and
timestamp while disagreeing on the value. The first is usually safe to collapse; the second means the
source contradicts itself and something has to choose. They are counted separately. In the profiled
member there were 688 of the first kind and none of the second.

**The timestamps are ambiguous.** They carry no timezone, and nothing in the dataset or its
documentation says whether a timestamp marks the start or the end of its half-hour. Both are recorded
as unknown. The profiler stores timestamps exactly as supplied so that a later decision can be
applied — and changed — without reprocessing.

## Limitations

- No billing or settlement calculation, no forecasting, no AI features. The tariff figures are a
  scenario under a stated, unresolved assumption, not a cost anyone paid. No dbt models, Airflow
  DAGs, Spark jobs or cloud deployment. A dbt project now holds the staging view, the policy
  models, both tariff dimensions, the classification and both charge facts, with 49 dbt tests;
  all of its SQL is generated from `policy.py` and `models.py` so no rule is written twice, and
  it reproduces the Python figures exactly. **It has no publisher**: `build-tariff-scenario`
  still does every scenario build from its own dimensions, and the dbt tables are candidate
  outputs that nothing reads. `uv run build-candidate` creates and seals an isolated warehouse
  candidate — sealed only when its latest recorded build attempt succeeded and its tables still
  digest as that attempt recorded — and `uv run publication` promotes or rolls one back, but
  the dashboard is not yet pointed at them. Design in
  [`docs/anl-003-dbt-design.md`](docs/anl-003-dbt-design.md), progress in
  [`docs/tickets/ANL-003-dbt-port.md`](docs/tickets/ANL-003-dbt-port.md). See
  [`docs/roadmap.md`](docs/roadmap.md) for what is planned.
- One member of 168 has been profiled in full, and three loaded into the database. Findings are not
  archive-wide, and three members are not any household's complete history. The 27 `ToU` households
  in member 135 are a **bounded, non-representative subset** — the households that happen to occupy
  one file, not a sample drawn from the trial. Nothing here is representative of the trial or of
  London, and no figure should be scaled up.
- A household charged for far fewer readings than its neighbours has **limited observed coverage**
  in the loaded members. Why readings are absent is not established and is not guessed at.
- No geographic breakdown is produced. One would be legitimate only from metadata properly linked
  to these households, and none has been linked.
- No causal claim is made about the tariff. Nothing measured here can show whether anyone responded
  to a price signal.
- Ingestion holds a whole member in one transaction so that a failure cannot publish partial data.
  That costs about 1 GB of memory per million-row member.
- The explorer withholds a consumption total for any household whose readings conflict, rather than
  choosing between them.
- The timezone convention and the interval start/end question are unresolved, which is enough to
  block any defensible billing period.
- Causes are not interpreted. Why a zero, a `Null`, a gap or a duplicate occurs is recorded as
  unknown.
- Members are cut on row count, so a household's readings can continue into the next file.
  Processing members independently will truncate those households.

[`docs/portfolio-evidence.md`](docs/portfolio-evidence.md) keeps an explicit list of what is not yet
claimable.

## Requirements

Python 3.12+ and [uv](https://docs.astral.sh/uv/).

The profiler imports only the Python standard library — `csv`, `zipfile`, `sqlite3`, `decimal` and
similar. Ingestion and the explorer use `duckdb`, `pyarrow`, `pandas` and `streamlit`; the tariff
schedule is read with `openpyxl`. `pytest` and `ruff` are development dependencies.

## Documentation

| | |
|---|---|
| [`docs/roadmap.md`](docs/roadmap.md) | Seven delivery milestones and their completion conditions |
| [`docs/profiling.md`](docs/profiling.md) | Running the profiler; what the report contains |
| [`docs/anl-001-tariff-workbook-findings.md`](docs/anl-001-tariff-workbook-findings.md) | What the tariff workbook actually contains |
| [`docs/anl-002-tariff-scenario.md`](docs/anl-002-tariff-scenario.md) | The tariff scenario: model, measurements and limits |
| [`docs/rec-001-source-expansion.md`](docs/rec-001-source-expansion.md) | Reproducing a result, and explaining what more source changed |
| [`docs/fore-001-forecasting-experiment.md`](docs/fore-001-forecasting-experiment.md) | The forecasting backtest: design, results and limits |
| [`docs/source-data-profile.md`](docs/source-data-profile.md) | The full source investigation |
| [`docs/rep-001-verified-facts.md`](docs/rep-001-verified-facts.md) | What is established, with evidence |
| [`docs/rep-001-assumptions-and-open-questions.md`](docs/rep-001-assumptions-and-open-questions.md) | What is not established |
| [`docs/portfolio-evidence.md`](docs/portfolio-evidence.md) | Measured results and what is not yet claimable |

Statements in the investigation are labelled VERIFIED (measured), PUBLISHER-DOCUMENTED (stated by the
data publisher, quoted), INFERRED (reasoned), CONTRADICTED, or UNKNOWN.

## Data source and licence

> Contains data from *SmartMeter Energy Consumption Data in London Households*, published by UK Power
> Networks via the London Datastore, licensed under the Creative Commons Attribution 4.0
> International licence (CC BY 4.0). Accessed 2026-09-06 from
> <https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d>

The licence link on the dataset page resolves to <https://creativecommons.org/licenses/by/4.0/>. It
appears in the dataset's own licence field rather than in the site footer, so the version applies to
this dataset. The publisher supplies no required attribution sentence, so the wording above is this
project's own. Details in [`docs/source-data-profile.md`](docs/source-data-profile.md) §14.5.

Code in this repository is separate from the dataset and its licence.
