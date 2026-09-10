# Energy Reconciliation

[![CI](https://github.com/Hammamelsh/energy-reconciliation/actions/workflows/ci.yml/badge.svg)](https://github.com/Hammamelsh/energy-reconciliation/actions/workflows/ci.yml)

Inspect smart-meter data, calculate a historical tariff scenario and reproduce the results from their recorded inputs. Built with **Python, SQL, DuckDB, dbt and Streamlit** using Low Carbon London data.

Meter readings arrive with duplicates, missing values, ambiguous timestamps and household histories split across files. This project preserves the source evidence, applies explicit rules and accounts for every reading included in—or excluded from—a tariff calculation.

The main warehouse contains **3 million source rows from three files, covering 83 households**. The dashboard brings together consumption, data quality, tariff calculations and forecasting baselines. Separate workflows support profiling a source file, publishing a validated build and replaying a recorded result.

## Findings

These results describe the loaded samples, which were not selected to represent the full trial or London.

### High-price periods account for 4.9% of charged consumption and 24.1% of the charge

Across **456,096 charged readings from 27 time-of-use households**, the 2013 tariff scenario totals **£11,675.43**. High-price periods account for a disproportionate share of that charge, reflecting both the higher price and the consumption recorded during those periods.

![Tariff dashboard for the loaded ToU sample: 27 charged households and 456,096 charged readings, with a chart comparing each band's share of consumption with its share of charge — Low 10.5% against 3.1%, Normal 84.6% against 72.9%, High 4.9% against 24.1% — above the per-band table.](docs/images/dashboard-tariff-bands.png)

*Historical energy-charge scenario for the loaded sample, 2013. Calculated under assumption A1; this is not a bill.*

**A1 assumes that a consumption timestamp and the matching schedule label refer to the same half-hour interval.** Their correspondence is unverified. No standing charges or separate tax adjustments are modelled, and the result does not establish a behavioural response to prices.

Coverage varies: 26 households contribute 17,375–17,520 of the year's 17,520 scheduled labels; one contributes 864. The tariff scenario covers the 27 time-of-use households; the 56 flat-rate households remain available for consumption and data-quality analysis. [Tariff measurements, coverage and assumptions](docs/anl-002-tariff-scenario.md).

**The same readings priced at the flat rate.** Under a second stated assumption — **A2**, the documented flat price of 14.228 p/kWh applied throughout 2013, because its effective dates are not documented — the same 456,096 charged readings carry an energy charge of **£12,160.26**, so the dynamic schedule priced this recorded consumption **£484.83 (4.0%) lower**. The direction is broadly shared: **25 of the 27 households are lower under the dynamic scenario** (by 0.9% to 11.4%) and two are higher (by 0.3% and 1.2%); 16 of 27 sit within two points of the pooled 4.0%, and the largest household contributes 13% of the pooled difference. This is a fixed-consumption comparison of two prices on the usage that was recorded — not what anyone paid or saved, since consumption on a flat tariff might have differed and no standing charge is modelled. [Comparison, household table and assumptions](docs/anl-005-flat-price-comparison.md).

### Profiling distinguishes missing consumption from recorded zeros

A separate profile of **source file 0—1 million records across 30 households—**found 688 exact duplicate rows, 29 `Null` values and 45,538 zero readings. All 29 `Null` records were off the half-hour grid. No conflicting values were found at shared household/timestamp keys in that file.

The pipeline preserves these distinctions. Missing values are not replaced with zero; equivalent numeric representations count once; conflicting readings remain visible and cause the affected explorer total to be withheld.

Across the three loaded files, **963 of 61,799 usable days total exactly zero** — every one of the day's 48 readings is `0`. They belong to 5 of 83 households and fall in 52 runs, 13 of them four weeks or longer. 38 of the 52 runs have a non-zero usable day immediately before and after, and none touches the edge of a household's recorded span, so within the loaded data they are bounded events rather than artefacts of where a file was cut. One household accounts for 780 of the 963; another records a median of 38 kWh on its non-zero days and exactly zero for a month at a time, twice. Why a day reads zero is not established from readings and is not inferred.

[Profile report](data/profiles/lcl-june2015v2-0-profile.json) · [Source investigation](docs/source-data-profile.md) · [Zero-day runs](docs/anl-004-zero-days.md)

### A four-week weekday mean has the lowest error in the baseline comparison

The backtest compares seven-day predictions for **40 households**, using the final 28 days of each selected run as holdout.

| Forecast baseline | Holdout mean absolute error (kWh per source-date total) |
|---|---:|
| Mean of the four preceding same weekdays | **1.901** |
| Same weekday last week | 2.121 |
| Origin day's consumption repeated | 2.322 |

Predictions use observations available at their origin. However, the cohort was selected retrospectively for long, clean runs, including knowledge of the holdout period. These results describe that historical benchmark, not expected performance across all households. Daily totals are grouped by source-date label; correspondence to local calendar days is unresolved.

[Forecast design and results](docs/fore-001-forecasting-experiment.md) · [Prior-data eligibility analysis](docs/i-08-prior-data-eligibility.md)

## Try the synthetic demo

Requires **Git, [uv](https://docs.astral.sh/uv/) and Linux**. The demo uses a committed, invented 12-row archive; no real-data download is needed. Dependency installation may require network access.

```bash
git clone https://github.com/Hammamelsh/energy-reconciliation.git
cd energy-reconciliation
uv sync --frozen
bash tools/synthetic-quickstart.sh
```

The script ingests the demo, runs dbt and its tests, publishes into a disposable root, captures a baseline and rebuilds it in a fresh destination. It checks expected figures throughout:

- **12 source rows → 11 distinct readings → 2 charged + 9 excluded.**
- **Exact charge: £0.7959**, from `1.000 × £0.0399 + 1.125 × £0.6720`.
- **Replay: 38 fields compared, 0 differences.**

Outputs stay under `data/proof-scratch/quickstart/`. To open the dashboard against that publication:

```bash
ENERGY_RECONCILIATION_PUBLICATION_ROOT="$PWD/data/proof-scratch/quickstart/published" \
  PYTHONPATH=src uv run streamlit run src/energy_reconciliation/explorer/app.py
```

Choose **Source → Published version** in the sidebar. The small demo supports consumption, quality and tariff views; forecasting requires the longer real-data histories.

[Individual commands, replay requirements and cleanup](docs/publication-workflow.md)

## How it works

| Component | Responsibility |
|---|---|
| Python | Profile and ingest archives; read the tariff workbook; build decimal prices; coordinate builds, publication and replay. |
| DuckDB | Store source readings and load history, execute transformations and serve analytical queries. |
| dbt | Apply policy and classification rules; build tariff dimensions and charged/excluded facts; test structure and reconciliation. |
| Streamlit | Explore consumption, quality findings, tariff results and forecast reports, with source and calculation details. |

A candidate is a fresh warehouse copy. A complete dbt build currently executes **5 materialised models and 49 tests**. Validation also checks the recorded attempt and output integrity before sealing the file. Promotion atomically changes the manifest naming the published version; it does not rebuild the file readers are using. Each dashboard rerun resolves one published version for all tabs.

[Architecture and dbt design](docs/anl-003-dbt-design.md) · [Publication workflow and captured build identity](docs/publication-workflow.md)

## Decisions behind the results

- **Shared rules.** SQL macros are generated from the Python policy definitions. Drift checks and row-level equivalence tests check consistency between implementations. [Tests](tests/test_dbt_equivalence.py).
- **Explicit exclusions.** Each distinct reading is either charged or given a reason. Reconciliation checks require `charged + excluded = distinct`, with no overlap. A valid reading can be outside the tariff's scope; exclusion does not necessarily mean bad data.
- **Exact monetary arithmetic.** Pence-to-pounds conversion happens once in Python `Decimal`; charges remain decimal values in DuckDB. Rounding is for display. [Arithmetic evidence](docs/anl-002-tariff-scenario.md).
- **Failed builds stay unpublished.** Attempt tracking and complete-build checks refuse interrupted or incomplete candidates. Tests exercise process termination and readers spanning promotion. [Publication tests](tests/test_publication.py).
- **Replay rebuilds the result.** A baseline records inputs, calculation/runtime identity and logical outputs. Replay re-ingests and rebuilds before comparing them. This process exposed defects in an earlier reproducibility fingerprint. [Replay findings](docs/anl-002-tariff-scenario.md#93-two-defects-the-replay-found).

Forecast reports are also checked against the selected dataset's content and displayed context claims, so changing a filename alone does not invalidate a matching report. [Applicability checks](src/energy_reconciliation/forecast/applicability.py).

## Validation and known limitations

```bash
uv run pytest -q
```

[Hosted CI run 34503994982](https://github.com/Hammamelsh/energy-reconciliation/actions/runs/34503994982), for commit `4a7fcdb`, passed lint, formatting, macro-drift checks, **568 tests**, and the synthetic quickstart. One check skipped by name: it needs the real warehouse and its forecast reports, which are local. Real-data equivalence remains a separate local check.

**An intermittent `dbt build` segmentation fault remains unresolved.** Observed crashes were recorded as failed attempts and refused sealing. The workflow is not ready for unattended operation; [the incident record](docs/tickets/ANL-003-dbt-port.md) documents the evidence and investigation.

The workflow has been exercised on Ubuntu 24.04 under WSL2 and GitHub-hosted Ubuntu, with Python 3.12.14 and 3.12.3 respectively. Other platforms are unverified. Publication recovery uses Linux-specific behaviour. Builds are started manually or by CI; there is no scheduled service.

[Roadmap](docs/roadmap.md) · [Evidence and claim boundaries](docs/portfolio-evidence.md)

## Real inputs and attribution

Download **Partitioned LCL Data.zip** (about 796 MB) and **Tariffs.xlsx** from the [London Datastore](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d). Place them in `data/raw/` and leave the archive zipped. [Recorded file sizes and digests](data/manifests/raw-file-manifest.csv) and the [workflow guide](docs/publication-workflow.md) describe the real-data setup. Workbook-based replay requires both the recorded archive and workbook, plus compatible calculation code and runtime.

> Contains data from [*SmartMeter Energy Consumption Data in London Households*](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d), published by UK Power Networks via the London Datastore under the [Creative Commons Attribution 4.0 International licence (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). Accessed 2026-09-06.

The tariff workbook is a resource of the same dataset. [Attribution evidence](docs/source-data-profile.md) is recorded in §14.5. Raw meter records and the workbook are not redistributed. The repository includes an invented demo archive and a derived real-data profile containing summary statistics and pseudonymous household identifiers.

**Code licence:** not yet selected; default copyright applies. Dataset attribution is separate from permission to reuse the project code.
