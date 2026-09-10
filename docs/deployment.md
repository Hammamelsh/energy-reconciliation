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

## 3. Publishing the snapshot (one-time, per version)

```bash
# 1. export from a validated publication root
uv run serving-snapshot export --root <publication root> --into data/serving

# 2. inspect the export before uploading: no credentials, no raw archive; the only
#    machine-specific strings are the build-origin paths in the attempt record
strings -n 12 data/serving/*.duckdb | grep -E "/home/|password|token" | sort -u

# 3. upload the two files as assets of a GitHub release tagged for the version
gh release create serving-v0001 data/serving/<file>.duckdb data/serving/<file>.duckdb.validated.json \
   --title "Serving snapshot v0001" --notes "Published version v0001, run <run id>, sha256 <digest>."

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

## 4. Hosting on Streamlit Community Cloud (free tier) — owner steps

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

## 5. If the free tier is unsuitable

Document the measured reason (memory, cold start, or sleep behaviour), then fall back to the
lowest-complexity option: the README's screenshots and the exported findings already stand
without a runtime. A container host (Cloud Run or similar) would run the same entrypoint but
adds billing and operations that this project has not taken on.

## 6. What a deployment must never do

- Weaken validation to make hosting work: no fallback to the copied `main` facts, no skipped
  seal or record checks, no legacy warehouse mode standing in for a published version.
- Build in the request path. If the snapshot is missing or fails verification, the page says
  so and shows nothing in its place.
- Serve a snapshot that was not exported from a publication that validated in place.
