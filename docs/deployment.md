# Deploying the public viewer: front door and explorer

How a published version is carried to a hosting machine without weakening what
"published" means, what was measured, and the exact steps to host it.

Two things can be hosted. The **front door** (§9–10) is a static page over a small data
file exported from the published version and checked against its pinned digest in the
browser; it is the link to give a visitor. The **explorer** (§1–7) is the Streamlit app over the full serving snapshot; it is
the deep view, and needs the 210 MB snapshot published first. The front door is deployed at
<https://energy-reconciliation.onrender.com/> (§12); the explorer is not.

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

A third capture, [`images/front-door-landing.png`](images/front-door-landing.png), is the
front door's opening view at 1440 px (§9): the same four values, the price ladder and the
outcome line. It is the launch image once the front door is live, because it is the page the
link opens.

## 9. The front door: a static page over a digest-checked bundle

The public entry point is a React + TypeScript page under [`web/`](../web/) (its own
[README](../web/README.md)). It never reads the database. A deterministic export,
`uv run export-presentation` ([`presentation.py`](../src/energy_reconciliation/presentation.py),
contract `presentation-bundle-1`), reads a validated publication — a serving snapshot or a
publication root — and writes two files that are committed beside the page:

| File | Size | Holds |
|---|---:|---|
| `web/public/data/bundle.json` | 59,550 bytes (11,358 gzipped) | Pooled totals; all 27 household outcomes with coverage, band shares and exact break-even prices; hour-of-day band distributions; the accounting ladder; data-quality and forecast summaries; both assumptions; the attribution; the publication's identity. Exact decimals as strings with units, beside display values rounded once in Python. |
| `web/public/data/manifest.json` | 359 bytes | The bundle's sha256, size and definition, and the source publication (version, run id, version-file sha256). |

What the bundle must not contain is enforced by
[`tests/test_presentation.py`](../tests/test_presentation.py): no individual reading, no
per-reading timestamp, no file path, no credential, no host name; the only time of day in it
is the publication's promotion timestamp. The same tests prove the export is byte-for-byte
deterministic, that its figures reconcile to `compare-flat-price`, `band_summary` and the
accounting ladder, and that a corrupt, stale, foreign or wrongly-defined bundle is refused.

In the browser, the page hashes the bundle it received (SHA-256) and compares it with the
manifest before showing a number. That is an integrity check on the exported payload, whose
provenance is traceable to the sealed build through the manifest's run id and version-file
digest; the browser does not ingest the archive, rerun dbt or recompute the result, and the
check certifies nothing about the source calculation beyond that traceability. The tariff is
never recalculated in JavaScript: the page formats exact strings and display values. Its one interactive calculation — how many
households would have come out ahead at another flat price — compares the slider against each
household's precomputed exact break-even price, a comparison rather than a recalculation.

Measured on 2026-09-10 (production build; headless Chromium; local servers, so not the host's
figures):

| Measurement | Result |
|---|---|
| Page weight | JavaScript 274,554 bytes (84.9 kB gzipped); CSS 15,008 (4.2 kB); HTML 2,862 (1.1 kB); data 59,909 (11.7 kB). Everything a first view fetches: **100.4 kB gzipped**. The Open Graph image (254 kB) is fetched only by link previews. |
| Time to first heading | 0.56–0.59 s including the data fetch and hash, at 1440 px and at 390 px. |
| Accessibility | axe-core: 0 violations under the WCAG 2 A, AA and best-practice rules at both widths. Keyboard: bars reachable with Tab, moved with the arrow keys, the selection carried into the URL (`?household=`). `prefers-reduced-motion` disables count-ups, reveals and the flow animation. |
| Charting dependency | None. A Recharts prototype measured 562 kB (167.8 kB gzipped) against 220 kB (68.6 kB) for the same charts drawn as SVG, before the page was complete. |
| Headers | `dist/` served locally with exactly the headers `render.yaml` declares (content-security policy allowing only the site's own origin, no sniffing, no framing, cache rules): page rendered, URL state restored, **no content-security-policy violation and no console error**. |
| Checks | `npm run check`: oxlint, `tsc -b`, 15 vitest tests (bundle verification and refusal of a changed byte, a stale manifest and a foreign definition; formatting; rendering with the committed data; URL state; the High-band label-hour statement derived from the schedule counts), production build. The CI workflow runs the same steps in a `web` job in parallel with the Python job, and fails if the built page still carries the site-URL placeholder. |

Against the Streamlit landing view (§2): the same figures from the same publication, but the
front door fetches 100 kB and shows its first heading in about half a second, where the
explorer needs the 210 MB snapshot per process and 1.6 s to a complete first render before any
host sleep or cold start is counted. **The front door is the link to publish**; the explorer is
the deep view, linked from the front door's footer once it is hosted.

## 10. Hosting the front door on Render — owner steps

[`render.yaml`](../render.yaml) describes a static site: root directory `web`, build
`npm ci && npm run build`, publish `dist`, Node 22.23.2 from `web/.node-version`, headers
(content-type sniffing off, referrer policy, framing denied, a content-security policy that
allows only the site's own origin) and cache rules (hashed assets immutable for a year;
`index.html`, the bundle and the manifest always revalidated). No secret is needed.

1. Sign in to Render with the GitHub account that owns the repository.
2. *New* → *Blueprint* → connect `Hammamelsh/energy-reconciliation`, branch `main`. Render reads
   `render.yaml` and proposes the `energy-reconciliation` static site; apply it.
3. After the first deploy, open the site's *Environment*, set `VITE_SITE_URL` to the site's
   public address without a trailing slash (the `onrender.com` address, or a custom domain once
   attached), and trigger a deploy. Until then the canonical link and Open Graph image tags are
   omitted — by design, so no placeholder ships — and link previews show no image.
4. Record what you observe: the deployed commit, the build time, the response headers on `/`
   and `/data/bundle.json`, and a link-preview check (paste the address somewhere that unfurls
   links) once step 3 is done.
5. Auto-deploy on push to `main` is Render's default. Either leave it on — every push has run
   the `web` CI job — or turn it off and deploy by hand after each release.

When this section was written nothing had been observed on Render; what had been verified
locally was the artifact and the headers (§9). The owner then carried out steps 1–3; what was
observed on the platform is recorded in §12.

## 11. What a deployment must never do

- Weaken validation to make hosting work: no fallback to the copied `main` facts, no skipped
  seal or record checks, no legacy warehouse mode standing in for a published version.
- Build in the request path. If the snapshot is missing or fails verification, the page says
  so and shows nothing in its place.
- Serve a snapshot that was not exported from a publication that validated in place.
- Ship a front-door bundle that was not exported from a validated publication, or a manifest
  that does not match it; the page refuses such a pair, and so must the release.
- Recreate the tariff arithmetic in the browser. The page formats what the export computed
  exactly; a second implementation in floating point would be a second source of truth.

## 12. Observed deployment (2026-09-10)

Public address: **<https://energy-reconciliation.onrender.com/>** — a Render static site built
from [`render.yaml`](../render.yaml) at commit `46ed791`, with `VITE_SITE_URL` set by the owner.
Verified anonymously from a UK client with `curl` and headless Chromium (no Render or GitHub
session), the same day the site went live. Observations of this deployment and environment,
not guarantees.

| Check | Observed |
|---|---|
| Served commit | `/assets/index-DE0KCDeN.js` and the stylesheet are byte-identical to a local build of `46ed791`; `/data/bundle.json` is byte-identical to the committed file (59,550 bytes, sha256 `3296b55f…`) and `/data/manifest.json` pins publication v0001, run `dbtcand-fbd1f2566700@…`. |
| Transport | `http://` → 301 to `https://`; HSTS (`max-age=315360000; includeSubdomains; preload`); HTTP/2 via Cloudflare. |
| Headers | Every header `render.yaml` declares is present on `/`, the assets and the data files: the content-security policy, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`. Hashed assets: `public, max-age=31536000, immutable`. Data files: `no-cache` — on a repeat load the browser revalidated both and received 304s (~300 bytes each). `/` itself carries Render's default `public, max-age=0, s-maxage=300` rather than the `/index.html` rule (the rule's path does not match `/`): browsers revalidate every time, the CDN may hold a page for up to five minutes. A page and a bundle from different deploys can therefore meet only briefly; the page refuses the mismatch and a reload resolves it. |
| MIME types | `text/html`, `application/javascript`, `text/css`, `application/json`, `image/png`, `image/svg+xml`, `text/plain` as expected; `/nonexistent` and `/data/` return 404. |
| Transfer (compressed) | HTML 1.1 kB, JS 86.8 kB, CSS 4.5 kB, bundle 11.5 kB, manifest 0.5 kB — about 104 kB for a first view. |
| Timing | Time to first byte 60–90 ms per resource; first uncached load to the first heading 0.8 s, repeat load 0.6 s (JS and CSS from cache, data revalidated). No cold-start delay was observed: a static site on a CDN has no process to wake. |
| Figures | The page shows £11,675.43, £12,160.26, +£484.83, +4.0% (exact 3.987…%), 27 households, 456,096 readings, 25 lower / 2 higher, the reconciled ladder 3,000,000 − 2,038 = 2,997,962 = 456,096 + 2,541,866, 408 of 788 High-labelled half-hours in labels 17:00–22:59, and 38 of 52 bounded zero-day runs — each matching the committed bundle. |
| Integrity behaviour | The loading state ("checking its digest") shows no figure; a payload with one flipped byte, injected in the browser, is refused with the digest mismatch named and nothing rendered. |
| Routing and state | `?household=` selects the named household; an unknown or malformed id falls back to the default household and the URL is rewritten; `?flat=` outside 0–100 or non-numeric falls back to the documented price; state survives a hard refresh; back and forward keep the selection coherent. No URL carries anything but `household` and `flat`. |
| Browser checks | Desktop 1440×900 and phone 390×844: no horizontal overflow; six tour steps; all sections; keyboard order into the chart and a visible focus halo; reduced motion honoured; no console errors and no failed requests; every footer and provenance link returns 200. axe-core: no violations at either width under the WCAG 2 A/AA and best-practice rules — an automated check, not a screen-reader evaluation. |
| Metadata | Title, description, canonical, `og:*` and `twitter:*` tags present with absolute `https://` URLs and no placeholder; crawler user agents (Facebook, LinkedIn, Twitter) receive the same HTML. The Open Graph image is served recompressed by the CDN (`cf-polished`, 233,546 → 146,118 bytes, same 1200×630 pixels). LinkedIn's own cached preview was not observed: that needs a post or a signed-in inspector. |

Not observed here: any period of high traffic, Render's behaviour on a failed build, or the
site under assistive technology.
