# Prototype: "One year, 17,520 half-hours" (energy terrain)

**Status: local prototype on branch `prototype/energy-terrain`. Not pushed, not deployed, no
hosted CI run. The public site is unchanged.** Starting point `f5d3477` (HEAD = origin/main,
clean tree). Date: 2026-09-12.

Labels follow the project's convention: **MEASURED** (read from a build, a test or a browser
here), **ESTIMATED** (reasoned, not observed), **UNKNOWN**.

## 1. The hypothesis

The released front door is technically sound and understandable, but its visual language
(dark ground, lime accent, large sans type, gradients, rounded cards) is the vocabulary of a
generic technology landing page. Hypothesis: one truthful, data-derived visual, every half
hour of 2013 as one surface, could give the project a recognisable identity **and** make the
tariff finding easier to grasp. It was treated as a hypothesis: the smallest useful 3D
prototype was built beside a flat (top-down) version and the two were compared.

## 2. Design diagnosis of the released site (from `web/src/styles.css` and captures)

What makes it read as a template, none of it in the data:

- two fixed radial gradient glows behind the body (lime, blue);
- text glows on the headline figures (`text-shadow` on the £484.83 and the stat values);
- stat cards with a vertical gradient, 14 px radius and a drop shadow; pill buttons with a
  glow on hover; a glowing progress line;
- a decorative "electric" dashed flow animation on the price ladder and a drop-shadowed day
  curve behind the hero;
- a lightning-bolt logo.

What is already good and was kept: the question-first opening, the exact figures beside
rounded ones, one palette, tabular numerals, keyboard access, the digest check.

The new section uses none of the template vocabulary: square corners, one thin line, no
shadow, no gradient, no glow; small-capital control labels; a monospace readout; tick marks
and axis labels; annotations that name a cell. Lime appears only for "lower under the dynamic
tariff" and orange for High-price or "higher" states; the Normal band moved from a lime-deep
tone to slate page-wide so that lime keeps one meaning.

## 3. The analytical contract: `energy-terrain-1`

Produced by `src/energy_reconciliation/terrain.py` from the **same validated read context**
as the comparison (a serving snapshot or a publication root), read through
`context.relations` from `scenario_build.fact_interval_charge_scenario` and
`scenario_build.dim_tariff_band_schedule`. Nothing is computed in the browser.

| Element | Definition |
|---|---|
| Cell | one (date label, half-hour label) pair; labels are `observed_at_naive` as written in the source, no timezone or interval convention applied (A1). Slot = hour × 2 + minute ÷ 30; a charged reading not on a half-hour label is a refusal, never coerced. |
| Grid | every date the schedule dimension covers (2013-01-01 to 2013-12-31, 365) × 48 slots = 17,520 cells, date-major. |
| Band | from the schedule dimension for every cell (present even where no reading exists), cross-checked against the facts' `band_label`; a disagreement refuses. |
| Per cell | `readings` and `households` (exact integers), `kwh` (3 dp) and `charge` (GBP, 2 dp) rounded **once** in `Decimal`, half up. A cell with no charged reading is `null`, never zero; a cell whose readings sum to zero is `0`. |
| Totals | exact strings for the grid, each band and each month (36 month × band rows), computed from the unrounded sums, never from the rounded cells. |
| Coverage | households per cell min/max, cells with and without readings; the file states that a pooled height moves with coverage as well as with usage. |
| Peaks | the cell with the largest exact kWh and the cell with the largest exact charge. |
| Reconciliation | before the payload is returned: Σ readings, Σ kWh (exact), Σ charge (exact) and the household count must equal `flat_comparison.compare`'s totals, and every band's readings, kWh and charge must equal `band_summary`'s exact strings. Any mismatch raises `TerrainError`; nothing is written. |
| Pinning | `manifest.json` gains `terrain` (file, definition, sha256, size). The bundle moves to `presentation-bundle-2`, adding a `terrain` summary (grid, totals, coverage, peaks, scale, reconciliation) and the file name. `load_terrain` (Python) and `verifyTerrain` (browser) refuse a missing pin, a wrong size, a changed byte, malformed JSON, a foreign definition, another run and arrays that do not match the grid. |
| Not in the file | any household id, any per-reading value, any timestamp with seconds, any path. Enforced by `tests/test_terrain.py`. |

**What the browser digest check establishes:** that the bytes it received are the bytes the
manifest pins, and that the manifest names the same run as the bundle. It does not
authenticate the publisher and it does not rerun the analysis; provenance to the sealed
build is through the manifest's run id and version-file digest, as for the bundle.

## 4. Files changed

Python and data: `src/energy_reconciliation/terrain.py` (new), `presentation.py`
(bundle-2, terrain summary, `write_bundle` writes and pins the terrain, `load_terrain`),
`tests/test_terrain.py` (new, 17 tests on two synthetic publications), `tests/test_presentation.py`
(fixture), `web/public/data/{bundle,manifest,terrain}.json` (regenerated from serving snapshot
v0001, run `dbtcand-fbd1f2566700@20260909T093452754963`).

Web: `web/src/lib/terrain.ts` (types, verification, cell helpers), `web/src/components/terrain/`
(`flat.ts` colour rules, `TerrainFlat.tsx` the flat map, `YearSection.tsx` the section,
`Terrain3D.tsx` and `scene.ts` the 3D view), `web/src/lib/bundle.ts` (manifest pin, bundle-2),
`web/src/lib/palette.ts` and `PriceLadder.tsx` (Normal band to slate), `App.tsx` (section after
the households block, nav link, tour step, lazy body), `styles.css` (instrument styles),
`web/src/test/{setup.ts, terrain.test.ts, year.test.tsx}`, `package.json` (`three` 0.186.0,
`@types/three`).

Docs: this record, `docs/images/prototype-energy-terrain/`, `web/README.md`,
`docs/deployment.md` §9, `docs/roadmap-next-phase.md`, `PROJECT_CONTEXT.md`.

## 5. Reconciliation evidence (MEASURED)

On the sealed serving snapshot (the publication the live bundle came from):

| Check | Terrain | Comparison / band summary | Equal |
|---|---:|---:|---|
| charged readings | 456,096 | 456,096 | yes |
| households | 27 | 27 | yes |
| kWh, exact | 85467.1329968000 | 85467.1329968000 | yes |
| dynamic charge, exact | 11675.4339216532500000 | 11675.4339216532500000 | yes |
| Low / Normal / High readings | 43,081 / 392,515 / 20,500 | same | yes |
| Low / Normal / High kWh and charge, exact | equal string for string | | yes |

Cells: 17,520 of 17,520 hold readings (20 to 27 households each: 5 cells at 20, 5 at 24,
245 at 25, 16,404 at 26, 861 at 27); no cell pools to zero; cell kWh 1.798 to 14.353; cell
charge £0.08 to £7.43. Peak kWh: 2013-01-20, 13:00 label, Low band, 26 households. Peak
charge: 2013-03-17, 19:30 label, High band, 26 households. Every band per cell is unique.
Regenerating the bundle left **every pre-existing section byte-identical**; only
`definition` changed and `terrain` was added (deep comparison against `git show HEAD:…`).
Two exports produced identical bytes. The synthetic fixtures prove the empty-versus-zero
rule (46 `null` cells beside one `0` cell) and every refusal.

## 6. What was built

- **Section** "One year, 17,520 half-hours", after the households and break-even block and
  before the hours section; nav link and a tour step. Its body is a lazy chunk fetched when
  the section comes within 800 px; the terrain file is fetched and verified when within 600 px.
- **Flat map (default on every device):** two carpets side by side, X = 48 half-hour labels,
  Y = 365 date labels, one canvas pixel per cell scaled with pixelated rendering (nothing
  smoothed); brightness = value on a zero-based scale per carpet, hue = band; each carpet's
  scale stated in its own unit; month gutter and hour ticks; the tallest cell of each carpet
  marked and labelled before any interaction; an optional third carpet for households per
  cell. Hover, tap, or the arrow keys (one half hour, one date, Page keys a week, Home and End)
  drive a monospace readout that states date label, half-hour label, kWh, households of 27,
  band and price, and dynamic charge.
- **3D terrain (on request, "3D terrain (loads 135 kB)"):** one instanced mesh of 17,520
  boxes with a gap between cells, orthographic camera (no perspective distortion), presets
  Default, Top-down and Side, zoom 1×/2×/4× on the selected cell, drag to orbit with a mouse
  or pen only (touch scrolls the page), no auto-rotation, rendered only when something changed.
  Height = value over the mode's maximum × one constant; the same value also sets brightness so
  the top-down preset still reads. Switching kWh to £ animates 600 ms, or jumps under
  `prefers-reduced-motion`; the scale bar relabels in the new unit at once and an annotation
  names the tallest cell. High tops are striped and Low tops dotted (visible when zoomed); a
  "Highlight" control dims the other bands for a colour-independent route. Keyboard cursor on
  the focusable canvas (`role="application"`, full accessible name); `WebGL` absent, a
  creation failure or a lost context all fall back to the flat map with a stated reason.
- **Textual equivalent:** the readout, a month × band table (12 rows plus the year, exact
  year totals from the export) and the caveats list from the file.
- **Copy:** no em or en dashes; labels, not clock time; coverage stated; cells are rounded
  display values, totals exact; not a bill, not a behavioural claim.

Chosen library: **Three.js directly**, lazy-loaded. MEASURED with esbuild (minified, gzip):
the classes this scene needs cost 133 kB; React Three Fiber plus the same classes cost 241 kB
on top of React (its namespace import defeats tree shaking) for a declarative layer one
instanced mesh does not use. A hand-written WebGL2 renderer was ESTIMATED at 6 to 8 kB but
means owning matrix and picking code; noted as the optimisation route if 3D ever ships.

## 7. Measurements (MEASURED; local; software-rendered)

Environment: headless Chromium (Playwright, Chrome for Testing 151) under WSL2 with **no GPU**.
WebGL ran on ANGLE over Mesa llvmpipe (`--use-angle=vulkan`), the faster of the two software
paths available; the default SwiftShader path was 3.5× slower and logged "GPU stall due to
ReadPixels" driver warnings even with no page code involved. Frame rates below are therefore
a floor set by software rasterisation, not what a laptop GPU would do; CPU-side costs
(picking, matrix updates, hashing) are representative. Served locally with exactly the
headers `render.yaml` declares.

Transfer (gzip of the built files):

| | Before (`f5d3477`) | After | Delta |
|---|---:|---:|---:|
| First view (HTML, CSS, JS, manifest, bundle) | 102,851 B | 105,235 B | +2,384 B (+2.3%) |
| of which main JS | 85,557 | 86,577 | +1,020 |
| of which CSS | 4,688 | 5,578 | +890 |
| of which bundle.json | 11,338 | 11,732 | +394 |
| Deferred when the section nears | 0 | 5,534 (section) + 64,970 (terrain.json) | |
| Deferred on request (3D) | 0 | 134,668 (Three.js + scene) | |

Timing, memory, frames, at four widths (llvmpipe, mean of the two passes):

| | 1440 before / after | 430 | 390 | 320 |
|---|---|---|---|---|
| time to first heading | 0.15 / 0.10 s | 0.13 / 0.10 | 0.11 / 0.09 | 0.12 / 0.09 |
| JS heap after load | 5.7 / 5.7 MB | 5.6 / 5.7 | 5.6 / 5.7 | 5.6 / 5.7 |
| JS heap after a full scroll | 5.9 / 6.5 MB | 6.2 / 5.9 | 6.5 / 5.9 | 6.0 / 6.0 |
| JS heap with the 3D view open, after interaction | n/a / 9.4 then 10.6 to 11.6 MB | not offered by default | | |
| scroll frame rate (2 s programmatic scroll) | 36 / 44 to 48 fps | 49 / 60 | 60 / 60 | 60 / 60 |
| console errors or warnings, CSP enforced | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| horizontal overflow | 0 / 0 px | 0 / 0 | 0 / 0 | 0 / 0 |

3D interaction (1440 px, llvmpipe): pointer move to readout update 2.3 to 2.6 ms mean, 5.6 ms
max (in-page, MutationObserver); raycast pick 1.7 to 2.3 ms; orbit drag 40 to 46 rAF frames/s
with 22 scene renders/s (each software render of 17,520 boxes at 1080 × 380 px took about 45
ms; on a GPU the draw is one instanced call of 210k triangles, ESTIMATED well under a frame,
UNKNOWN here); mode transition rendered 14 frames in 750 ms (software), 1 frame under reduced
motion.

## 8. Accessibility (MEASURED with axe-core 4.13, WCAG 2.x A/AA and best-practice rules)

0 violations at 1440, 430, 390 and 320 px, before and after. "Incomplete" items: colour
contrast on 173 to 260 nodes (elements over the page's gradients and canvases, which axe
cannot evaluate; present before the change as well), plus one `aria-prohibited-attr` in the
first pass, fixed by giving the legend a role. Real-browser checks: the flat map and the 3D
canvas are reached by Tab (six presses from the toolbar to the canvas), the arrow, Page, Home
and End keys move the cursor and the live readout follows; reduced motion renders one frame
for a mode change; WebGL disabled at the browser (`--disable-3d-apis`) and a lost context both
show the flat map with the reason and disable the 3D button.

**Still needs a human:** screen-reader announcement order of the readout while moving with
the keyboard; the usefulness of `role="application"` on the canvas with real assistive
technology; colour-vision checks of slate versus blue at 3 px cells (the Highlight control is
the colour-independent route); touch use of the flat map on a real phone (3 px cells at 320
px; the readout and keyboard route exist); the visual weight of the section for a
non-technical reader. Automated checks are not proof of accessibility.

## 9. Corrections made on the way

- The site shows the Normal band's charge share as **72.9%** (README, dashboard captures,
  bundle `bands`). The exact ratio is 72.8497%, which rounds to **72.8%** in a single
  rounding; the 72.9 comes from rounding twice (a 4 dp share, then 1 dp). Other shares are
  unaffected (Low 3.0606 to 3.1; High 24.0897 to 24.1; kWh shares 10.4787, 84.6242, 4.8971).
  Not changed on this branch: it is a displayed figure on main; recommended fix is a single
  half-up rounding from the exact ratio in `presentation._share`, with README and captures
  updated. The terrain file carries no share fields, so the page has one definition of a share.
- The legend first said High cells were "striped in 3D"; at whole-year zoom a cell is about
  3 px and no pattern is visible. Copy corrected to "striped in 3D when zoomed", and the
  Highlight control is the guaranteed non-colour route.
- The first measurement pass reported a contrast violation at 1440 px and a 60 to 44 fps scroll
  drop; both were artefacts (a fade-in section mid-transition when axe ran; SwiftShader
  versus llvmpipe). The corrected script and a like-for-like GL path removed both.
- "Every cell has a reading" is a fact of this publication, not a property of the contract;
  the contract and the tests carry empty cells as `null`.

## 10. Comparison and decision

**What a visitor learns from the flat map, without touching anything:** the kWh carpet is a
year of days with evenings brighter than mornings and winter brighter than summer; the £
carpet is almost dark except for orange streaks between the 17:00 and 23:00 labels in
January to April and October to December, plus the marked tallest cells (14.353 kWh at a
Low-band lunchtime in January; £7.43 at a High-band evening in March). That is the finding,
"4.9% of the electricity, 24.1% of the charge", made visible: the cost of this year lived in
a few winter-evening half hours priced at 67.20p.

**What the 3D terrain adds:** the same pattern as spikes standing up from a low plain, which
is more memorable, and a kWh-to-£ switch that turns unremarkable evening cells into spikes,
which is the clearest single demonstration that price, not usage, made those cells prominent.
It costs a 135 kB dependency on request, WebGL and a fallback path, orbit and occlusion
concerns (mild: the tall cells sit at the far edge in the default view), and its top-down
preset is a weaker version of the flat map.

Against the gate:

| Criterion | Flat map | 3D terrain (on request) |
|---|---|---|
| 1 easier or more memorable | easier: static, both units side by side | more memorable, not easier |
| 2 derived entirely from verified data | yes, one file, pinned and reconciled | same file |
| 3 first screen unchanged | yes (hero untouched; captures identical) | yes |
| 4 mobile usability | yes, no WebGL, no drag, tap or keys | not offered by default on phones |
| 5 non-3D route with equal values | it is the route; plus readout and table | falls back to it |
| 6 initial performance | +2.3% first view, first heading unchanged | nothing until requested |
| 7 visibly more distinctive | yes: an instrument, not a card | yes, more so |

**Recommendation: keep 2D.** Ship the section with the flat map pair as the view on every
device. Keep the 3D terrain only as the opt-in view it now is, if the identity it gives is
judged worth 135 kB of deferred dependency and a WebGL fallback path; the finding does not
need it, and everything the 3D view certifies (data, accessibility, performance) it inherits
from the flat map beneath it. If one answer is required: the flat map is the feature; the
3D terrain is an option. Not kept because effort was spent: the 3D code is the part that
would be removed first.

Live-price and regional-carbon ideas stay where they are recorded
(`docs/roadmap-next-phase.md`, phases B and C) and nothing of them enters this historical
comparison.

## 11. Viewing it locally

```bash
git switch prototype/energy-terrain
cd web && npm ci && npm run build && npm run preview     # http://localhost:4173/
# or, with hot reload: npm run dev
```

Regenerating the three data files from the sealed snapshot (deterministic):

```bash
uv run export-presentation --serving-dir data/serving \
  --profile data/profiles/lcl-june2015v2-0-profile.json \
  --forecast-report data/forecasts/fore-001-718d8b1f4a56.json --into web/public/data
```

Checks run for this record: `uv run pytest tests/test_terrain.py tests/test_presentation.py`
(30 passed), `npm run check` (oxlint, `tsc -b`, 30 vitest tests, production build). The full
Python suite was deliberately not run, as instructed, until the prototype is judged worth
keeping.

## 12. Confirmation

Nothing was pushed, deployed or run in hosted CI. `main` is untouched at `f5d3477`; the
prototype lives only on `prototype/energy-terrain` in this working copy. The published
analytical result is unchanged: the regenerated bundle's pre-existing sections are
byte-identical to the committed ones.
