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

**A3. Deployment (owner action pending).** Upload the snapshot as a pinned release asset,
commit the pin, and deploy `streamlit_app.py` to Streamlit Community Cloud; record cold start,
memory and the deployed revision as observed on the platform. Fallback if unsuitable: the
README's screenshots and exported findings. Steps in [`deployment.md`](deployment.md) §3–4.

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
- The code licence is unchosen; public visibility and reuse rights are separate.
