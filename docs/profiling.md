# One-member profiler — how to reproduce the result

Profiles a single CSV member of the Low Carbon London partitioned archive and writes a
machine-readable JSON report with fully reconciled counts.

The archive is **never extracted and never modified**. The member is decompressed on the
fly and discarded as it is read.

## Prerequisites

- `data/raw/Partitioned LCL Data.zip` present (git-ignored; see `data/manifests/raw-file-manifest.csv`
  for the expected SHA-256).
- `uv` installed. No dependencies beyond the project's existing ones — the profiler uses only
  the Python standard library.

## The exact command

```bash
cd energy-reconciliation
uv run profile-member
```

That reproduces the committed report at `data/profiles/lcl-june2015v2-0-profile.json`.

### Options

```bash
uv run profile-member \
  --archive "data/raw/Partitioned LCL Data.zip" \
  --member  "Small LCL Data/LCL-June2015v2_0.csv" \
  --output  data/profiles/lcl-june2015v2-0-profile.json
```

| Option | Purpose |
|---|---|
| `--archive` | Archive path (default: `data/raw/Partitioned LCL Data.zip`) |
| `--member` | Member to profile (default: `Small LCL Data/LCL-June2015v2_0.csv`) |
| `--output` | JSON report path (default: `data/profiles/…-profile.json`) |
| `--examples-output` | Row-level diagnostic examples — **contains source rows**, defaults to the git-ignored `data/sample/` |
| `--no-examples` | Skip the examples file entirely |
| `--work-dir` | Where the temporary SQLite database goes (default: system temp) |

Exit code `0` means complete and all reconciliation equations held; `1` means the report was
written but is incomplete or an equation failed; `2` means the archive was not found.

## Where output goes, and why

| Path | Tracked? | Contents |
|---|---|---|
| `data/profiles/*.json` | **yes** | Counts, fingerprints, per-household row counts and timestamp ranges. **No source rows, no consumption values.** |
| `data/sample/*-examples.json` | **no** (ignored) | Diagnostic examples including full source rows. |

The tracked report carries household identifiers because per-household observations are part of
the profile; it carries no consumption values and no reconstructable rows.

## Running the tests

```bash
uv run pytest -q
```

Tests use synthetic archives built in temp directories. They never read `data/raw/`.

## What the consumption distribution reports

Over the finite consumption values only (`Null`, empty and non-finite values are excluded):

| Figure | How it is computed |
|---|---|
| count, minimum, maximum, sum | **Exact.** Accumulated with `Decimal` while streaming — constant memory, no floating point. |
| mean | **Derived** from the exact sum and count, rounded to 9 decimal places. The only rounded figure. |
| percentiles p1/p5/p25/p50/p75/p90/p95/p99 | **Exact selection** by nearest rank of an actually observed value. No interpolation, so no value is invented. |
| interquartile range | p75 − p25, from those observed values. |
| 5 smallest and 5 largest values | Value and record number in the report; household id and timestamp in the ignored examples file. |

Standard deviation is deliberately omitted: it would need a second pass or floating-point
accumulation, and percentiles describe the spread without either cost.

## What the report will not tell you

By design, and per REP-001 sections 6, 7 and 9, the profiler:

- assigns **no timezone** and performs no conversion — the source convention is UNKNOWN;
- makes **no claim about interval start vs end**;
- does **not** fill, interpolate or delete anything;
- does **not** interpret why a zero, `Null`, gap or duplicate exists;
- does **not** describe a household as complete — households are known to span members, so
  ranges are reported as *first/last observed in this member*.
