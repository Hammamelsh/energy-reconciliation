import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { loadBundle, type Bundle, type Loaded } from "./lib/bundle";
import { prefersReducedMotion, pushState, readState } from "./lib/url";
import { Hero } from "./components/Hero";
import { HouseholdChart } from "./components/HouseholdChart";
import { sortHouseholds, type SortKey } from "./lib/households";
import { HouseholdDetail } from "./components/HouseholdDetail";
import { BreakEven } from "./components/BreakEven";
import { HourRibbon } from "./components/HourRibbon";
import { Pipeline } from "./components/Pipeline";
import { Quality } from "./components/Quality";
import { Provenance } from "./components/Provenance";
import { Footer } from "./components/Footer";
import { Tour, type TourStep } from "./components/Tour";
import { useInView, useScrollProgress } from "./hooks";
import { Insight } from "./components/Insight";
// The year section's body (the flat map, the terrain file's verification and the 3D
// scene's loader) is its own chunk, fetched when the section comes near; the initial
// page carries only this introduction.
const YearSection = lazy(() => import("./components/terrain/YearSection").then((m) => ({ default: m.YearSection })));

function YearLoading({ bundle }: { bundle: Bundle }) {
  const t = bundle.terrain;
  return (
    <div className="instrument year">
      <p className="hint" role="status">
        Loading the terrain: {integer(t.grid.cells)} half-hour cells of {t.grid.first_date.slice(0, 4)}, pooled across {t.totals.households} households,
        together holding exactly £{t.totals.charge.exact} ({money(t.totals.charge.display)}), the comparison's dynamic total.
      </p>
    </div>
  );
}

function Year({ bundle, loaded }: { bundle: Bundle; loaded: Loaded }) {
  const [ref, near] = useInView<HTMLDivElement>("800px 0px");
  return (
    <div ref={ref}>
      {near ? (
        <Suspense fallback={<YearLoading bundle={bundle} />}>
          <YearSection bundle={bundle} manifest={loaded.manifest} />
        </Suspense>
      ) : (
        <YearLoading bundle={bundle} />
      )}
    </div>
  );
}
import { highRank, highShare } from "./lib/households";
import { highConcentration, labelRange } from "./lib/hours";
import { integer, money } from "./lib/format";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; loaded: Loaded };

function Logo() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <rect x="2" y="2" width="28" height="28" rx="8" fill="#131824" stroke="#262e40" />
      <path d="M17.5 5 9 18h6l-1.5 9L23 14h-6z" fill="#c6f43a" />
    </svg>
  );
}

function Reveal({ children, id, title, sub }: { children: React.ReactNode; id: string; title: string; sub?: string }) {
  const [ref, seen] = useInView<HTMLElement>();
  return (
    <section className={`block reveal ${seen ? "in" : ""}`} id={id} ref={ref}>
      <div className="wrap">
        <h2>{title}</h2>
        {sub && <p className="sub">{sub}</p>}
        {children}
      </div>
    </section>
  );
}

function Progress() {
  const p = useScrollProgress();
  return <div className="progress" aria-hidden="true" style={{ transform: `scaleX(${p})` }} />;
}

export function Page({ loaded }: { loaded: Loaded }) {
  const bundle: Bundle = loaded.bundle;
  const c = bundle.comparison;
  const initial = useMemo(() => readState(window.location.search), []);
  const ids = useMemo(() => new Set(c.per_household.map((h) => h.household_id)), [c.per_household]);
  const defaultId = useMemo(() => sortHouseholds(c.per_household, "pct").at(-1)?.household_id ?? null, [c.per_household]);
  const [selected, setSelected] = useState<string | null>(
    initial.household && ids.has(initial.household) ? initial.household : defaultId,
  );
  const [sortKey, setSortKey] = useState<SortKey>("pct");
  const flatDefault = Number(c.flat_price.pence_per_kwh);
  const [flat, setFlat] = useState<number>(initial.flat ?? flatDefault);

  useEffect(() => {
    pushState({ household: selected, flat: flat === flatDefault ? null : flat });
  }, [selected, flat, flatDefault]);

  const household = c.per_household.find((h) => h.household_id === selected) ?? null;
  const o = c.outcomes_under_dynamic;
  const [tour, setTour] = useState(false);
  const [tourRun, setTourRun] = useState(0);
  // Where the schedule put its High band, by hour of the timestamp label as written. The
  // sentence is built from the counts, so it can only say what the bundle holds.
  const hc = highConcentration(bundle.hour_bands);
  const year = bundle.schedule.first_date?.slice(0, 4) ?? "2013";
  const highHours = hc
    ? `Across ${year}, High-labelled half-hours ${hc.everyHour ? "appeared in every clock-hour label" : "did not appear in every clock-hour label"}. Of the schedule's ${hc.total} High-labelled half-hours, ${hc.slots} (${hc.sharePct}%) were labelled from ${labelRange(hc)}.`
    : "The schedule's High-labelled half-hours are not summarised here.";
  const steps: TourStep[] = [
    { id: "top", title: "The question", text: `${c.households} households, one year of recorded readings, two prices. On the same recorded consumption the dynamic scenario came out ${money(Math.abs(c.flat_minus_dynamic.display))} (${c.pct_of_flat.display?.toFixed(1) ?? "n/a"}%) ${c.flat_minus_dynamic.display > 0 ? "lower" : "higher"} than the flat price.` },
    { id: "households", title: "Every household", text: `${o.lower} were lower under the dynamic tariff and ${o.higher} higher. Click any bar, or use the arrow keys, to see where that household's electricity fell.` },
    { id: "what-if", title: "What if", text: "Each household has a break-even flat price. Slide to see how many would have come out ahead at any other flat price: a comparison, not a recalculation." },
    { id: "year", title: "One year", text: `When were the calculated charges highest? Every half hour of ${year} as one map, each cell pooling 20 to 27 of the ${c.households} households. Compare the electricity map with the charge map and the High-price half hours light up: a small share of the electricity, a large share of the charge.` },
    { id: "hours", title: "The hours", text: `${highHours} No timezone or interval convention is applied. The largest hourly totals of charged kWh also occurred among those label hours. That is timing, not proof of a response.` },
    { id: "pipeline", title: "How it's made", text: "Three million readings, every one charged or excluded with a reason, a ladder that must add up, a sealed build, and this page checking its exported data against a pinned digest before showing it." },
    { id: "provenance", title: "The small print", text: "Two assumptions, the identity of the build behind every number, the licences, and what this does not show." },
  ];

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <div className="top">
        <Progress />
        <div className="wrap">
          <a className="brand" href="#top">
            <Logo /> Energy Reconciliation
          </a>
          <nav className="nav" aria-label="Sections">
            <a href="#households">Households</a>
            <a href="#what-if">What if</a>
            <a href="#year">One year</a>
            <a href="#hours">Hours</a>
            <a href="#pipeline">How it's made</a>
            <a href="#quality">Data quality</a>
            <a href="#provenance">Provenance</a>
          </nav>
        </div>
      </div>
      <main id="main">
        <Hero
          bundle={bundle}
          selected={selected}
          onPick={(id) => {
            setSelected(id);
            // On one column the detail card (which holds the "why") sits below the 27-row
            // chart, so go straight to it; on two columns the section shows both.
            const oneColumn = typeof window !== "undefined" && window.matchMedia?.("(max-width: 899px)").matches;
            const target = (oneColumn && document.querySelector(".detail")) || document.getElementById("households");
            target?.scrollIntoView?.({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
          }}
          onTour={() => {
            setTourRun((n) => n + 1);
            setTour(true);
          }}
        />

        <Reveal
          id="households"
          title={`${o.lower} lower, ${o.higher} higher: every household, no averaging`}
          sub={`Each bar is one household's difference between its flat-price charge and its dynamic charge, as a percentage of the flat-price charge. ${o.lower} of ${c.households} sit to the right of zero; the two on the left used more of their electricity in the expensive band. Pick a household to see why.`}
        >
          <div className="two-col">
            <div className="card">
              <div className="toolbar">
                <span>Sort</span>
                <span className="seg" role="group" aria-label="Sort households">
                  {(["pct", "gbp", "coverage"] as SortKey[]).map((k) => (
                    <button key={k} type="button" aria-pressed={sortKey === k} onClick={() => setSortKey(k)}>
                      {k === "pct" ? "by %" : k === "gbp" ? "by £" : "by coverage"}
                    </button>
                  ))}
                </span>
                <span className="legend" style={{ marginLeft: "auto" }}>
                  <span><i style={{ background: "var(--volt)" }} />▲ lower under dynamic</span>
                  <span><i style={{ background: "var(--ember)" }} />▼ higher under dynamic</span>
                </span>
              </div>
              <HouseholdChart households={c.per_household} selected={selected} onSelect={setSelected} sortKey={sortKey} />
              <details>
                <summary>Table view of the same figures</summary>
                <div className="body scroll-x">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Household</th>
                        <th>Charged readings</th>
                        <th>Coverage</th>
                        <th>Dynamic</th>
                        <th>Flat price</th>
                        <th>Flat − dynamic</th>
                        <th>% of flat</th>
                        <th>High share</th>
                        <th>Under dynamic</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortHouseholds(c.per_household, sortKey).map((h) => (
                        <tr key={h.household_id}>
                          <td>{h.household_id}</td>
                          <td>{integer(h.charged_readings)}</td>
                          <td>{h.coverage.display?.toFixed(1)}%</td>
                          <td>{money(h.dynamic_charge.display)}</td>
                          <td>{money(h.flat_charge.display)}</td>
                          <td>{money(h.flat_minus_dynamic.display)}</td>
                          <td>{h.pct_of_flat.display?.toFixed(1)}%</td>
                          <td>{highShare(h).toFixed(1)}%</td>
                          <td>{h.outcome_under_dynamic}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </div>
            <div>
              {household ? (
                <HouseholdDetail
                  household={household}
                  flatPence={c.flat_price.pence_per_kwh}
                  highRank={highRank(c.per_household, household.household_id)}
                  total={c.households}
                />
              ) : (
                <div className="card">Pick a household.</div>
              )}
            </div>
          </div>
          <div className="two-col" style={{ marginTop: 22 }}>
            <Insight households={c.per_household} selected={selected} onSelect={setSelected} />
            <div className="card flip">
              <h3>The two that went the other way</h3>
              {c.per_household
                .filter((h) => h.outcome_under_dynamic === "higher")
                .map((h) => (
                  <button key={h.household_id} type="button" className={`flip-row ${selected === h.household_id ? "on" : ""}`} onClick={() => setSelected(h.household_id)} aria-pressed={selected === h.household_id}>
                    <span className="id">{h.household_id}</span>
                    <span>
                      <b>{money(h.flat_minus_dynamic.display)}</b> · {h.pct_of_flat.display?.toFixed(1)}%
                    </span>
                    <span className="hint">
                      {highShare(h).toFixed(1)}% of its electricity in High, rank {highRank(c.per_household, h.household_id)} of {c.households}
                    </span>
                  </button>
                ))}
              <p className="hint">
                Small in pounds, but real in the comparison: both came out slightly higher under the dynamic scenario
                because more of their electricity fell in the 67.2p half hours. The dynamic tariff was not lower for
                every household.
              </p>
            </div>
          </div>
          <div style={{ marginTop: 22 }}>
            <BreakEven comparison={c} value={flat} onChange={setFlat} />
          </div>
        </Reveal>

        <Reveal
          id="year"
          title="When were the calculated energy charges highest?"
          sub={`Each cell pools the charged readings available for one half-hour timestamp label in ${bundle.terrain.grid.first_date.slice(0, 4)}, from ${bundle.terrain.coverage.households_per_cell_min} to ${bundle.terrain.coverage.households_per_cell_max} of the ${bundle.terrain.totals.households} households on the dynamic tariff. A historical scenario under assumptions A1 and A2, not a bill. Hover, tap or use the arrow keys to read any cell.`}
        >
          <Year bundle={bundle} loaded={loaded} />
        </Reveal>

        <Reveal
          id="hours"
          title="Where the expensive half hours were"
          sub={`The dynamic schedule announced each day's bands a day ahead. ${highHours} No timezone or interval convention is applied, so this is not a claim about clock time. The largest hourly totals of charged kWh also occurred among those label hours: a coincidence of timing in this data. No behavioural response is measured.`}
        >
          <HourRibbon hourBands={bundle.hour_bands} />
        </Reveal>

        <Reveal
          id="pipeline"
          title="How three million readings become one reproducible number"
          sub="Every reading is either charged or excluded for a stated reason, the ladder has to add up, the build is sealed only when all of its models and tests pass, and this page checks the exported data against its pinned digest before showing it."
        >
          <Pipeline bundle={bundle} digest={loaded.digest} />
        </Reveal>

        <Reveal
          id="quality"
          title="What was found on the way"
          sub="Getting a tariff number right meant counting the source-data conditions the calculation handles explicitly, and a few things that turned out to be findings in their own right."
        >
          <Quality bundle={bundle} />
        </Reveal>

        <Reveal id="provenance" title="Assumptions, provenance and limits" sub="Everything the numbers depend on, and what they do not establish.">
          <Provenance bundle={bundle} digest={loaded.digest} />
        </Reveal>
      </main>
      <Footer notice={bundle.source.attribution.notice} />
      <Tour key={tourRun} steps={steps} active={tour} onClose={() => setTour(false)} />
    </>
  );
}

export default function App({ base }: { base?: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  useEffect(() => {
    let cancelled = false;
    loadBundle(base)
      .then((loaded) => !cancelled && setState({ kind: "ready", loaded }))
      .catch((error: unknown) => {
        if (!cancelled) setState({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [base]);

  if (state.kind === "loading") {
    return (
      <div className="state wrap" role="status" aria-live="polite">
        <div>
          <div className="spinner" aria-hidden="true" />
          <p>Loading the data and checking its digest…</p>
        </div>
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="state wrap" role="alert">
        <div className="card">
          <h2 style={{ marginTop: 0 }}>The data did not match its pinned digest</h2>
          <p className="warn">{state.message}</p>
          <p className="hint">
            Nothing is shown in its place: a figure whose data failed the integrity check is not shown. The published
            figures are in the <a href="https://github.com/Hammamelsh/energy-reconciliation">repository</a>.
          </p>
        </div>
      </div>
    );
  }
  return <Page loaded={state.loaded} />;
}
