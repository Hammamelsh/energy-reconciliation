# Publication workflow — build, seal, promote, read, record, replay

The step-by-step commands behind the one-command quickstart in the README, the same steps on
the real dataset, and what must be kept for a result to be rebuilt later.

**Terms.** A *warehouse* is a DuckDB file loaded by `ingest-member`. A *candidate* is an isolated
copy of a warehouse that `dbt build` has run on. A candidate is *sealed* when the build is
recorded as complete and its tables still digest as recorded; *promoting* it writes a new
publication manifest naming that sealed file as the published version. A *baseline* records a
published result so that it can be rebuilt and compared.

Nothing below writes to `data/published/` unless you name it as `--root`. Every example uses a
disposable root under `data/proof-scratch/`, which is git-ignored.

## 1. Synthetic data, step by step

The committed archive `data/demo/demo-lcl-sample.zip` holds 12 invented rows for two households,
`DEMO0001` (`Std`) and `DEMO0002` (`ToU`). The `demo` schedule is a single invented day
(2013-01-01, 48 slots), so only readings on that date can be charged.

```bash
uv run ingest-member --demo --database data/proof-scratch/demo/warehouse.duckdb

uv run build-candidate \
  --source data/proof-scratch/demo/warehouse.duckdb \
  --root   data/proof-scratch/demo/published \
  --schedule demo
# prints: sealed <CANDIDATE> ... READY FOR PROMOTION -- not published

uv run publication --root data/proof-scratch/demo/published \
  promote <CANDIDATE> --expect-published none

uv run publication --root data/proof-scratch/demo/published read
```

`<CANDIDATE>` is the path printed after `sealed ` — a placeholder, not a literal.
`--expect-published none` states what you believe is currently published; promotion refuses if
the manifest disagrees, so two people cannot silently overwrite each other's promotion. `read`
resolves the manifest, validates the seal against the build record, and prints the accounting
ladder and the exact charge through the same contract the dashboard uses.

`build-candidate` never promotes. If the dbt build fails — including the
[open segfault incident](tickets/ANL-003-dbt-port.md#open-release-blocker--dbt-build-segfaults-intermittently-third-investigation-2026-09-09-unresolved)
— the attempt is recorded as failed, nothing is sealed, and the command exits non-zero. Rerun it.

### View it in the dashboard

```bash
ENERGY_RECONCILIATION_PUBLICATION_ROOT="$PWD/data/proof-scratch/demo/published" \
  PYTHONPATH=src uv run streamlit run src/energy_reconciliation/explorer/app.py
```

Choose **Source → Published version** in the sidebar. The manifest is resolved once per page
load and every tab reads that one sealed file. If nothing is published, or the seal and the build
record disagree, the page says so and shows nothing — it never falls back to a local file under
the word "published".

`PYTHONPATH=src` matters while editing code: Streamlit's file watcher reloads only modules on
`PYTHONPATH` or beside the script, so without it edits to `policy.py`, `tariff/` and `ingest/`
appear to have no effect. After changing model code, restarting the server is still the certain
option.

**Warehouse mode.** The sidebar's other source is a **warehouse file** you pick. The picker
offers **Main sample** (`data/warehouse/energy.duckdb`) and **Synthetic demo — invented data**
(`data/warehouse/demo.duckdb`), and keeps the two REC-001 comparison artefacts behind **Show
comparison warehouses**. A file with no recorded role is listed under its own name and never
hidden. Warehouse mode reads the Python-built tariff scenario (`build-tariff-scenario`), not a
dbt build:

```bash
uv run ingest-member --demo --database data/warehouse/demo.duckdb
uv run build-tariff-scenario --demo --database data/warehouse/demo.duckdb
PYTHONPATH=src uv run streamlit run src/energy_reconciliation/explorer/app.py
```

### Record the published result and rebuild it

```bash
uv run capture-published-baseline \
  --root data/proof-scratch/demo/published \
  --directory data/proof-scratch/demo/baselines
# prints: baseline : <BASELINE>   (a pub2-<id>.json file)

uv run replay-published-baseline \
  --baseline <BASELINE> \
  --into data/proof-scratch/demo/replay \
  --archive data/demo/demo-lcl-sample.zip
```

Replay verifies the archive, each recorded member's content digest and (for the workbook
schedule) the workbook **before** creating anything, then re-ingests those members and runs the
ordinary `build-candidate` path — a real dbt build with every model and test — into a directory
that must not already exist. Nothing is copied from the publication being checked. Exit `0`: every
input, identity and output matched. Exit `1`: something differs, and each differing field is
named. Exit `2`: it could not reproduce at all (a missing archive, for instance).

*Reproduced* means the inputs, the calculation and runtime identity, and every logical output are
identical: relation schemas, row counts, every row including duplicate multiplicity, the
accounting ladder and the exact unrounded decimals. Execution provenance — run ids, timestamps,
paths, the database bytes and the seal — is new by construction and is never compared.

**What must be kept to replay later.** A baseline is not self-contained. Replay needs the source
archive whose member digests it recorded and, for the real schedule, `data/raw/Tariffs.xlsx`. It
does **not** need the publication, the version file or the candidate: delete those and the
baseline still rebuilds.

**Two baseline formats.** Format 2 (`pub2-*.json`, the commands above) records a published dbt
build. Format 1 (`capture-baseline` / `replay-baseline`) records the Python scenario built by
`build-tariff-scenario`, and is what [`rec-001-source-expansion.md`](rec-001-source-expansion.md)
used. The two formats refuse each other's files.

## 2. The real dataset

Prerequisites: `Partitioned LCL Data.zip` and `Tariffs.xlsx` in `data/raw/` (see the README's
*Working with the real dataset*). The workbook schedule covers **2013 only**; readings outside it
are excluded as `outside_schedule_period`.

```bash
# load two adjacent Std files and the first ToU file into data/warehouse/energy.duckdb
uv run ingest-member \
  --member "Small LCL Data/LCL-June2015v2_4.csv" \
  --member "Small LCL Data/LCL-June2015v2_5.csv" \
  --member "Small LCL Data/LCL-June2015v2_135.csv"

# build an isolated candidate from it -- never point dbt at the warehouse itself
uv run build-candidate \
  --source data/warehouse/energy.duckdb \
  --root   data/proof-scratch/real/published \
  --schedule workbook

uv run publication --root data/proof-scratch/real/published \
  promote <CANDIDATE> --expect-published none
uv run publication --root data/proof-scratch/real/published read

uv run capture-published-baseline --root data/proof-scratch/real/published \
  --directory data/baselines
uv run replay-published-baseline --baseline data/baselines/pub2-<id>.json \
  --into data/proof-scratch/real/replay
```

`build-candidate` snapshots the source warehouse (opened read-only) into the candidate before
dbt touches anything, so the ingestion warehouse is never written by a build. On the
three-file warehouse the build takes several minutes and the read prints 456,096 charged
readings and the exact charge `11675.4339216532500000`
([ANL-002 §7.2](anl-002-tariff-scenario.md#72-loaded-households--27-tou-households-2013-only)).
The replay over that result compared 44 fields with 0 differing.

### What a published version looks like when it is read back

The dashboard's tariff tab, in **Published version** mode, states the identity of the version it
resolved before any figure on the page is read:

![Dashboard panel headed "Run identity — what would have to match to reproduce this", listing the published version v0001 and its candidate file, promotion and build timestamps, a required-build line reading "complete — every one of 54 required dbt nodes passed", the workbook schedule with 17,520 labels covering 2013-01-01 to 2013-12-31, the price catalogue version, digests for the calculation code, shared policy, dbt project, built tables and version file, the dbt and runtime versions, and the whole-run exact charge of £11675.4339216532500000.](images/dashboard-published-identity.png)

Three lines carry most of the weight. **Published version** names the sealed database the manifest
points at — the version label `v0001` and the candidate file `cand-<stamp>.duckdb` are different
things, and both are shown. **Required build** reads *complete — every one of 54 required dbt
nodes passed*, which is the condition the seal enforces: had any model or test been skipped or
failed, this version could not have been promoted, and the page would refuse to show figures
rather than show unsealed ones. **Whole-run exact charge** is the unrounded decimal
`£11675.4339216532500000`, counted from the built fact rather than read from a recorded row.

**What this screenshot is.** A capture of the demonstration publication kept at
`data/proof-scratch/demo-published-20260909/published`, taken on 2026-09-09 from a build of the
three-member real warehouse. It is **not** a build of the latest commit: its digests — the dbt
project digest in particular — belong to the tree as it stood when that build ran, and later
commits that touch `dbt/` or the calculation code will produce different ones. That is the
mechanism working as intended, not a discrepancy. Rebuild and republish to see current digests.

Re-running an ingest is a no-op only when **both** the source file and the transformation code
are unchanged; changing either replaces that member's rows, so a code change rebuilds rather than
silently keeping rows built by older logic.

The forecast backtest runs on the real warehouse only (the demo archive has no household with
168 contiguous usable days):

```bash
uv run run-forecast-experiment --database data/warehouse/energy.duckdb
```

Its report is written under `data/forecasts/` (git-ignored, because it names real household ids)
and appears in the dashboard's **Forecast (backtest)** tab whenever the selected dataset's rows
digest to what the report was run on.

## 3. Carrying a published version to another machine

A published version is bound to the path it was built at. To serve it elsewhere, export a
**serving snapshot** — the file and its seal copied byte for byte with a pinned manifest —
and read it through `reads.serving`, which verifies the bytes against the pin and the seal
and binds the attempt record to the exported origin. Contract, measurements and hosting
steps: [`deployment.md`](deployment.md).

```bash
uv run serving-snapshot export --root <publication root> --into data/serving
uv run serving-snapshot verify --directory data/serving
ENERGY_RECONCILIATION_SERVING_SNAPSHOT=data/serving uv run streamlit run streamlit_app.py
```

## 3. Other `publication` subcommands

| | |
|---|---|
| `status` | what is published, from one manifest read |
| `inventory` | every version file and its role (read-only) |
| `finalise <candidate>` | validate and seal a built candidate (`build-candidate` does this for you) |
| `rollback <version>` | publish a retained earlier version again |
| `recover` | remove an orphan temporary manifest and a dead lock; never edits the manifest |

Design and proofs: [`anl-003-dbt-design.md`](anl-003-dbt-design.md) (D5 publication, D6 identity,
D9 read contract).
