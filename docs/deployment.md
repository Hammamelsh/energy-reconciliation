# Deploying the dashboard as a public viewer

How a published version is carried to a hosting machine without weakening what
"published" means, what was measured, and the exact steps to host it.

## 1. The problem a serving snapshot solves

A sealed version is bound to the place it was built. Its attempt record names the absolute
path the build wrote, and `publication.build_record` refuses a file whose path differs — a
snapshot of a built warehouse inherits a history that does not authorise the copy. That
protection is right for candidates, and it means a published file cannot simply be copied to
another machine and read as published.

The **serving snapshot** contract (`serving-snapshot-1`, [`serving.py`](../src/energy_reconciliation/serving.py))
keeps that protection and adds a relocation path with its own evidence:

| Step | What is checked | Where |
|---|---|---|
| Export | The publication validates **in place**: manifest, seal, attempt record and path binding all agree. The version file and its seal are copied byte for byte; the copy's sha256 must equal the seal's. | `serving-snapshot export` |
| Manifest | `serving.json` pins the whole-file sha256, size, run id, version, required-build status, and the **build origin path** exactly as the record names it — provenance, distinct from the serving location. | written by export |
| Fetch | Downloads to a `.part` name, checks size, then sha256, then that the downloaded seal certifies the pinned digest; renames atomically. A partial or mismatched download leaves **no** usable file. | `serving-snapshot fetch` |
| Read | Hashes the file **before opening it** and refuses on mismatch with the pin or the seal; then every attempt-record gate, with one substitution: the record must name the **origin the manifest declares**, not the current path. A copy of some other build still fails, because its record names some other origin. | `reads.serving` |

What the serving read deliberately does not do: recompute the built-tables digest. The
whole-file hash certifies every byte, including those tables, and the digest was checked at
origin when the file was sealed and again at export. Recomputing it over three million rows
peaks at ~900 MB (measured), which on a small host is the difference between fitting and not.
Candidates and live publications are unchanged: they still recompute it.

Tested in [`tests/test_serving.py`](../tests/test_serving.py): valid relocation; wrong pinned
digest; a changed byte; a partial file; a missing file; a manifest naming another origin or
another run; a truncated or wrong download leaving no file; and the candidate path binding
still refusing a relocated copy.

## 2. What was measured (2026-09-10, this machine)

| Measurement | Result |
|---|---|
| Version file | 210,251,776 bytes (v0001, run `dbtcand-fbd1f2566700@…`) |
| Serving read (hash + record gates) | 0.43 s, peak RSS 145 MB |
| Complete first render of the dashboard on the snapshot, headless | 1.6 s, **peak RSS 265 MB** |
| The same render with local forecast reports present | 1.95 GB peak — the forecast-applicability digest over three million rows. Reports are git-ignored and never on a host, so this does not apply to a deployment; it is recorded so nobody adds them without knowing. |
| Server process after a browser render | 256 MB RSS |
| Browser check | Desktop 1440 px and phone 390 px rendered with headless Chromium: landing title, scope line, four metrics, outcome line, chart, household inspection and methods expander all present; controls reachable by keyboard. |

These are local measurements of the artifact a host would run. They are not the host's
cold-start time, which includes downloading 210 MB once per process and the platform's own
startup; that must be observed on the platform.

## 3. What the published snapshot contains

Inspected relation by relation on 2026-09-10 (`serving.json` pins the file: v0001,
210,251,776 bytes, sha256 `708a55da…`).

| Relation | Rows | What it holds |
|---|---:|---|
| `main.readings` | 3,000,000 | **Row-level meter readings** from three of the dataset's 168 files: household identifier, tariff group, the timestamp exactly as written, the value as written and as a decimal, and the profiler's classification of each row. This is the dataset's content, restructured. |
| `main.load_registry` | 3 | Which archive members were loaded, their content digests and counts. Archive *name* only; no path. |
| `main.rejected_records` | 0 | Empty: no source row was rejected. |
| `main.dim_tariff_band_schedule`, `scenario_build.dim_tariff_band_schedule` | 17,520 each | The dynamic tariff's half-hour band schedule, **derived from the publisher's workbook** (the workbook file itself is not included). |
| `main.dim_tariff_price`, `scenario_build.dim_tariff_price` | 4 each | The publisher-documented prices with citations. |
| `main.fact_interval_charge_scenario`, `scenario_build.…` | 456,096 each | **Derived rows, one per charged reading**: household, timestamp, band, kWh, exact charge, assumption id. The Python scenario and the dbt build; identical figures. |
| `main.fact_interval_charge_exclusion`, `scenario_build.…` | 2,541,866 each | Derived rows, one per excluded distinct reading, with its reason. |
| `main.scenario_run`, `scenario_build.dbt_build_run` | 1 each | The Python run record and the dbt attempt record: identities, versions, digests. |
| `main.v_*` views, `scenario_build.stg_readings` | — | Views over the tables above; no additional data. |

**So, precisely:** the asset redistributes row-level meter readings (3,000,000 rows), derived
per-reading rows (about 3,000,000 more, across two copies of each fact), the dataset's household
identifiers for 83 households, and per-reading timestamps. The README's statement that the
*repository* redistributes no readings remains true; the statement is now made about the
repository and the viewer separately.

**Identifiers.** `MAC…` codes are the publisher's own household identifiers. In this project
they are linked to no person, address, coordinate or other attribute; the dataset carries none.
They are pseudonymous in the plain sense that each stands in for one household; whether they
are anonymous in any legal sense is not assessed here.

**Licence and attribution.** The readings, the schedule and the prices are content of a dataset
published under CC BY 4.0. Redistribution is permitted with attribution and an indication of
changes; the attribution is the notice in the README and in the release notes below. Changes
made: three source files parsed into one table (values kept as written and as decimals; no rows
removed; exact duplicates retained in `readings` and collapsed only in derived tables), the
workbook schedule parsed into a table, and derived tariff tables added. The project's code
licence is a separate, unchosen matter.

**Machine-specific metadata that remains, and why.** Three strings name a directory on the
build machine: `dbt_build_run.database_path`, the `--target-path` inside `dbt_command`, and
`project_dir` inside `dbt_vars`, all under `/home/hammam/projects/energy-reconciliation/…`.
They are the attempt record the seal certifies — `database_path` is the very value the serving
reader binds the record to — so editing them would change the file's bytes, break the seal's
whole-file hash, and remove the origin the contract depends on. They are disclosed rather than
removed. Nothing else machine-specific was found: no credentials, no user names beyond that
directory, no archive paths (the registry stores names only). The scan covered every text column
of every table.

## 4. Full snapshot or an extract — measured, and decided

| Candidate | Size | What it can drive |
|---|---:|---|
| Full snapshot (chosen) | 210 MB | Everything: landing comparison, household inspection, tariff bands and exclusions, the accounting ladder, and the Overview / Data quality / Source records tabs that read `readings`. |
| Tariff-tab extract | 75 MB | Landing, bands, exclusions; **not** the accounting ladder or the three readings-based tabs. |
| Landing-only extract | 15 MB | Landing, household inspection, bands; nothing else. |

The 15 MB extract is attractive on paper: fourteen times smaller and a faster first download.
Two facts decide against it. First, it does not change what is redistributed in kind — its
456,096 charged rows are still per-reading consumption with household identifiers and
timestamps — so the README's claim has to be corrected either way. Second, it would need its own
provenance contract (the seal certifies the whole original file, not a derived one) and a
degraded dashboard mode with most tabs hidden, for a viewer whose purpose includes the evidence
behind the comparison: the accounting ladder and the data-quality views are what the readings
make possible. The full snapshot costs a one-time 210 MB download per process (memory measured
at 265 MB peak) and keeps one contract, already tested. That is the better trade for a first
public viewer; an extract remains the fallback if the platform's cold start proves unacceptable.

## 5. Publishing the snapshot (one-time, per version)

```bash
# 1. export from a validated publication root
uv run serving-snapshot export --root <publication root> --into data/serving

# 2. inspect the export before uploading: no credentials, no raw archive; the only
#    machine-specific strings are the build-origin paths in the attempt record
strings -n 12 data/serving/*.duckdb | grep -E "/home/|password|token" | sort -u

# 3. upload the two files as assets of a GitHub release tagged for the version
gh release create serving-v0001 data/serving/<file>.duckdb data/serving/<file>.duckdb.validated.json \
   --title "Serving snapshot v0001" \
   --notes "<version, run id, sha256; the contents table above in brief; the CC BY 4.0 attribution; the changes made>"

# 4. pin the download URLs and commit the pin
uv run serving-snapshot pin --manifest data/serving/serving.json \
   --file-url https://github.com/<owner>/<repo>/releases/download/serving-v0001/<file>.duckdb \
   --seal-url https://github.com/<owner>/<repo>/releases/download/serving-v0001/<file>.duckdb.validated.json
git add serving/snapshot.json && git commit -m "serving: pin snapshot v0001"

# 5. verify the pinned snapshot end to end, as a host would
rm -rf data/serving && uv run serving-snapshot fetch && uv run serving-snapshot verify
```

A release asset can be replaced by its owner; the committed pin's sha256 is what the fetch
trusts, so a replaced asset fails verification rather than being served.

**Data terms.** The readings are the CC BY 4.0 dataset; sharing is permitted with attribution,
which the dashboard and README carry. The release notes should repeat the attribution.

## 6. Hosting on Streamlit Community Cloud (free tier) — owner steps

The entrypoint is [`streamlit_app.py`](../streamlit_app.py) at the repository root. It puts
`src` on the path, fetches and verifies the pinned snapshot once per process if absent, and
runs the explorer. A page request never runs ingestion, dbt, promotion or replay.

1. Sign in at share.streamlit.io with the GitHub account that owns the repository.
2. *Create app* → *Deploy a public app from GitHub* → repository `Hammamelsh/energy-reconciliation`,
   branch `main`, main file path `streamlit_app.py`.
3. *Advanced settings* → Python version **3.12**. No secrets are needed.
4. Deploy. The first start downloads the 210 MB snapshot; the page shows *Preparing the
   published snapshot (one-time download)* until it has verified.
5. Record what you observe: time to first render, whether the memory indicator stays under the
   allowance, and the exact deployed revision shown in the app's *Manage app* panel.

Dependencies come from `uv.lock` (the platform's documented precedence includes it); the
project itself is not installed as a package, which is why the entrypoint puts `src` on the
path. Apps on the free tier sleep after inactivity; a sleeping app takes tens of seconds to
wake, so a public link should say so and the README keeps a screenshot beside it.

Local rehearsal of exactly what the host runs:

```bash
ENERGY_RECONCILIATION_SERVING_SNAPSHOT=data/serving uv run streamlit run streamlit_app.py
```

## 7. If the free tier is unsuitable

Document the measured reason (memory, cold start, or sleep behaviour), then fall back to the
lowest-complexity option: the README's screenshots and the exported findings already stand
without a runtime. A container host (Cloud Run or similar) would run the same entrypoint but
adds billing and operations that this project has not taken on.

## 8. Launch images

Two captures of the real render, unretouched, are committed for launch use:

- [`images/dashboard-landing.png`](images/dashboard-landing.png) — the landing view at
  1440 px, sidebar collapsed: every household bar labelled, the partially covered household
  marked. Right for the README and for a desktop reader; in a phone feed its chart labels are
  too small to read, so it should not be the only image in a post.
- [`images/social-landing.png`](images/social-landing.png) — the same page rendered at
  760 px and cropped (a rectangular crop only) from the title to the first bars: the scope
  line, the four values, the outcome sentence and the two households that went the other way,
  at a size that reads on a phone. This is the one to attach to a social post; the desktop
  image can follow in a comment or the README link.

Neither shows a map. The data contains no coordinates, and no household location is known
or invented; a map is reserved for verified regional carbon data in a later phase
([`roadmap-next-phase.md`](roadmap-next-phase.md)).

## 8. What a deployment must never do

- Weaken validation to make hosting work: no fallback to the copied `main` facts, no skipped
  seal or record checks, no legacy warehouse mode standing in for a published version.
- Build in the request path. If the snapshot is missing or fails verification, the page says
  so and shows nothing in its place.
- Serve a snapshot that was not exported from a publication that validated in place.
