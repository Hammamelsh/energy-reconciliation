# Energy Reconciliation

Tools and analysis for half-hourly electricity meter data from the Low Carbon London trial.

What exists today is a **profiler**: it reads one CSV member from the dataset archive, classifies
every value, counts everything, and writes a JSON report whose totals reconcile. It is the
groundwork for billing and reconciliation work, not a billing system.

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

## Tests

```bash
uv run pytest -q
```

83 tests, all synthetic. **No dataset needed** — every fixture builds a small zip archive in a
temporary directory.

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

- No billing or settlement calculation. No ingestion layer, dbt models, Airflow DAGs, Spark jobs or
  cloud deployment. See [`docs/roadmap.md`](docs/roadmap.md) for what is planned.
- One member of 168 has been profiled in full. Findings are not archive-wide.
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
similar. `uv sync` also installs `duckdb`, `pandas` and `pyarrow`, which `pyproject.toml` declares for
planned work but this code does not use, plus `pytest` and `ruff` as development dependencies.

## Documentation

| | |
|---|---|
| [`docs/roadmap.md`](docs/roadmap.md) | Seven delivery milestones and their completion conditions |
| [`docs/profiling.md`](docs/profiling.md) | Running the profiler; what the report contains |
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
