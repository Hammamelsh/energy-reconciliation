# The front door

A static page that presents the flat-price comparison from a small data file that the browser
checks against its pinned digest. It is the public entry point; the Streamlit explorer
(`src/energy_reconciliation/explorer/`) remains the deep view over the full published database.

## Where the numbers come from

Every figure on the page comes from `public/data/bundle.json`, written by
`uv run export-presentation` (`src/energy_reconciliation/presentation.py`, contract
`presentation-bundle-2`) from a validated publication: a serving snapshot or a publication
root. The same export writes `public/data/terrain.json` (contract `energy-terrain-1`,
`src/energy_reconciliation/terrain.py`): every half hour of the year as one cell, pooled
across the households in the comparison, reconciled to the comparison's exact totals before
it is written and pinned by the manifest like the bundle. The export is deterministic: the same publication produces the same bytes. The bundle
carries the pooled totals, all 27 household outcomes with coverage and band shares, the
hour-of-day band distributions, the accounting ladder, data-quality and forecast summaries,
both assumptions, the attribution and the publication's identity. It carries nothing
row-level: no reading, no per-reading timestamp, no path, no credential
(`tests/test_presentation.py`).

Money and energy travel as exact decimal strings with a unit, beside a display value rounded
once in Python. The page formats; it never recalculates the tariff. Its one interactive
calculation (how many households would have come out ahead at another flat price) compares
the slider against each household's precomputed exact break-even price.

Before a number is shown, the browser hashes the bundle it received (SubtleCrypto SHA-256)
and checks definition, size, digest and dbt run id against `public/data/manifest.json`. The
terrain file is checked the same way before a cell is drawn, and refused with a visible
message otherwise.
A changed byte, a stale manifest or a bundle from another run is refused with a visible error.
This is an integrity check on the exported payload with provenance traceable to the sealed
build; the browser does not rebuild the result from the raw archive or rerun the build.

## Commands

    npm ci            # install exactly what package-lock.json pins (Node 22; see .node-version)
    npm run dev       # development server
    npm run check     # lint (oxlint), typecheck (tsc -b), tests (vitest), production build
    npm run build     # production build into dist/

Re-exporting the data after a new publication:

    uv run export-presentation --serving-dir data/serving \
      --profile data/profiles/lcl-june2015v2-0-profile.json \
      --forecast-report data/forecasts/<report>.json --into web/public/data

Commit the bundle and the manifest together. The Python suite checks that the committed bundle
verifies against its manifest; the web tests check the same from the browser side and render
the page with the committed data.

## Design choices

- **No charting library.** A Recharts prototype built to 562 kB (167.8 kB gzipped) against
  220 kB (68.6 kB) for the same charts drawn as React SVG. Drawing the SVG directly also made
  keyboard navigation, text labels and the table view straightforward. The first view is
  283.3 kB (86.6 kB gzipped) of JavaScript and 22.3 kB (5.6 kB) of CSS.
- **The year section loads in stages.** Its body (`src/components/terrain/`) is a 5.5 kB
  (gzipped) chunk fetched when the section comes near, with the 65 kB terrain file; the 3D
  view and Three.js (135 kB gzipped) load only when a visitor asks for them. The flat map is
  the view on every device; the 3D terrain is an option. See
  `docs/prototypes/energy-terrain.md` for the design record and measurements.
- **Accessibility.** Bars are focusable and moved with the arrow, Home and End keys; the
  household chart has a table view; outcomes are marked with ▲/▼ as well as colour;
  `prefers-reduced-motion` turns off count-ups, reveals and the flow animation. axe-core
  reports no violations (WCAG 2 A/AA and best-practice rules) at 1440 px and 390 px.
- **State in the URL.** `?household=MAC000186&flat=13.661` restores a selection and a slider
  position, so a view can be shared.
- **Site address at build time.** The canonical link and the Open Graph image need the site's
  public origin: set `VITE_SITE_URL` (no trailing slash) when building. Without it the build
  omits those tags rather than shipping a placeholder.

## Licence

Original project code is licensed under the [MIT License](../LICENSE). The figures this page
shows are derived from *SmartMeter Energy Consumption Data in London Households*, which remains
subject to its publisher's [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) terms and
is attributed on the page and in the root README; the exported bundle carries that attribution,
not the MIT licence. Third-party dependencies retain their respective licences.

## Deployment

`render.yaml` at the repository root configures a Render static site (root `web`, build
`npm ci && npm run build`, publish `dist`) with security and cache headers. The site is
deployed at https://energy-reconciliation.onrender.com/ (commit `46ed791`); owner steps, the
measured sizes and what was observed on the platform are in `docs/deployment.md`.
