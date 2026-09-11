# Next-phase roadmap: a public viewer, then live context

A technical roadmap for what follows the first public release. Phases are ordered by
dependency; each has the evidence that closes it. Later phases are recorded here so the
requirements are not lost, not as commitments to a date.

## Phase A — a public viewer of the completed comparison

**A1. Data delivery (done 2026-09-10).** The serving-snapshot contract carries a published
version to another machine with its integrity and provenance intact; see
[`deployment.md`](deployment.md) §1–2 for the contract and the measurements. Closed by:
relocation succeeds; wrong digest, changed byte, partial file, missing file, foreign origin and
foreign run are each refused by name; the candidate path binding is unchanged; memory and
render time measured (265 MB, 1.6 s for a complete first render).

**A2. Public experience (done 2026-09-10).** A landing view, *The same electricity, priced
two ways*, shown whenever the dashboard reads a published version or a serving snapshot:
scope line, the four headline values, the 25/2/0 outcome line with the sign in words, a sorted
per-household percentage chart with a zero rule and coverage marked in text, a household
inspection carried in the URL (`?household=`), and a methods expander. Closed by: values
reconcile to `compare-flat-price`; desktop and phone renders inspected in a real browser;
keyboard reachability checked; the explorer's other views unchanged beneath it.

**A3. Front door (built and deployed 2026-09-10 at <https://energy-reconciliation.onrender.com/>,
commit `46ed791`; the deployment as observed is recorded in [`deployment.md`](deployment.md)
§12).** The public entry point is a static
React + TypeScript page ([`web/`](../web/)) over a presentation bundle exported deterministically
from the published version (`export-presentation`, contract `presentation-bundle-1`, `-2` on the `prototype/energy-terrain` branch; 59,550
bytes; verified by sha256 in the browser before anything is shown; exact decimals as text; no
tariff arithmetic in JavaScript). The Python engine — DuckDB, dbt, the sealed publication, the
Streamlit explorer — is unchanged; the page is a view over its output, and Phase B's grid will
be rendered the same way. Closed so far by: the bundle reconciles to `compare-flat-price` and
the accounting ladder in tests; byte-determinism, refusal of corrupt, stale and foreign bundles,
and the absence of row-level data are tested; lint, typecheck, tests and build pass; desktop
and phone renders inspected; axe-core clean at both widths; keyboard navigation checked; the
built page cannot ship a site-URL placeholder. Remaining: the owner's Render deploy from
[`render.yaml`](../render.yaml) and the observed link-preview check
([`deployment.md`](deployment.md) §9–10). Once live this is the primary public link; the
explorer is the deep view behind it.

**A4. Explorer hosting (owner action pending).** Upload the snapshot as a pinned release asset,
commit the pin, and deploy `streamlit_app.py` to Streamlit Community Cloud; record cold start,
memory and the deployed revision as observed on the platform. Fallback if unsuitable: the front
door alone, with the README's screenshots. Steps in [`deployment.md`](deployment.md) §5–6.

## Phase B — a current retail-price explorer (separate from the 2013 data)

**Question.** For a chosen product and region, which published half-hour periods have lower
unit prices, over the horizon the supplier has actually published?

**Source.** Octopus Energy's public product and tariff-rate endpoints, which need no account
for product discovery and unit rates. Discover a current import product and its regional
tariff at run time; never hard-code a product from an example.

**Requirements, fixed now so they survive until the work starts.**

- Show product, region, units and VAT treatment on the page.
- Keep UTC internally; render one named local timezone; handle clock changes by elapsed
  intervals. Never assume a local day has 48 half-hours.
- Distinguish *retrieved at* from *applies to*; show the horizon actually published; never
  invent prices for periods the supplier has not published.
- Handle pagination, overlapping or conflicting intervals, gaps, negative prices, HTTP errors
  and rate limits. Missing data must never become a zero price.
- Keep this feed visibly separate from the 2013 comparison: not the same households, not the
  same tariff, not every UK customer's rate.
- Review the provider's terms before mirroring or republishing any response.
- Freshness: a bounded cached fetch with a visible *retrieved at*; a stale last-known
  response may be shown as stale context but must never drive a "cheapest now" statement.

**Visual design for this phase.** A live **48-half-hour price grid** — one cell per
published half hour, price as number and shade, the current interval marked, unpublished
intervals left visibly empty — and, on top of it, the **cheapest complete time-window**
view: the chosen duration drawn as a band over the grid with its cost, greyed out wherever
the horizon cannot cover it. Both show *retrieved at* and the horizon end. No map: retail
prices are regional, not geographic points, and the data holds no coordinates.

**Optional second step.** The lowest-cost contiguous window of a chosen duration within the
published horizon, under an explicitly stated consumption profile (a labelled constant-power
illustration is acceptable). Interval-overlap energy × unit price; keep negative rates; reject
windows the horizon does not fully cover; state tie handling. This estimates the energy
component under one tariff, not a bill or an appliance's actual consumption.

## Phase C — regional carbon intensity (a different question)

**Question.** When is the grid forecast to be less carbon-intensive in a region?

**Source.** NESO's Carbon Intensity API (national and regional). Implement against the horizon
the API actually returns, not the website's description. The series starts after the 2013
trial, so it never describes the historical households.

**Visual design for this phase.** This is where a **geographic map** earns its place: NESO
publishes carbon intensity by DNO region, so a regional choropleth of the forecast is a
truthful view of real regional data. It is reserved for this phase and this data only —
the 2013 households have no coordinates and must never be placed on it.

**Requirements.** Forecast, estimate and measured values labelled as such; freshness shown
(an HTTP 200 for an interval that has already ended is not "now"); region mapping verified
rather than assumed if ever placed beside retail prices; and no equivalence drawn between low
carbon intensity and low retail price.

## Refresh and retention, for either live feed

Start with cached fetches and visible freshness. If durable snapshots are added, record the
source URL, request parameters, retrieval time, source intervals, payload digest and
transformation version; keep failure tests offline and deterministic; and do not commit
frequent snapshots to `main` or run the full test suite on every refresh. Scheduled GitHub
Actions can be delayed or disabled after inactivity: acceptable for a demonstration, not a
real-time guarantee.

Transient HTTP failures may be retried within a bound. A native crash of the build process is
a different matter and stays visible: retrying it would change the evidence.

## Standing items

- The intermittent `dbt build` crash remains open; see the ANL-003 ticket for the evidence and
  the next diagnostic step. Build-time containment and serving stability are different claims.
- I-20 (the unselected conflict model) is recorded and unscheduled.
- The code licence was chosen on 2026-09-10: MIT for the original code ([`LICENSE`](../LICENSE)).
  The dataset and the data-derived artefacts in the repository stay under the publisher's
  CC BY 4.0 terms; third-party dependencies keep their own licences.
