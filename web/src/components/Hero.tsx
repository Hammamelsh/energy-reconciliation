import { useRef, useState, type KeyboardEvent } from "react";
import type { Bundle, Household } from "../lib/bundle";
import { integer, money, outcomeGlyph, outcomeWord, signedMoney, signedPct } from "../lib/format";
import { describe, sortHouseholds } from "../lib/households";
import { useCountUp, useInView, useMediaQuery } from "../hooks";
import { PriceLadder } from "./PriceLadder";
import { DayShape } from "./DayShape";

function Stat({ label, value, tone, note }: { label: string; value: string; tone?: "volt" | "ember"; note: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className={`value ${tone ?? ""}`}>{value}</div>
      <div className="note">{note}</div>
    </div>
  );
}

/** The two totals side by side. Widths are display values scaled to the larger total; the
 * gap between them is drawn on the larger bar. Layout only: nothing is recalculated. */
function Totals({ bundle }: { bundle: Bundle }) {
  const c = bundle.comparison;
  const [ref, seen] = useInView<HTMLDivElement>("0px");
  const dyn = c.dynamic_charge.display;
  const flat = c.flat_charge.display;
  const base = Math.max(dyn, flat, 0.01);
  const rows: { key: string; label: string; value: number; tone: "dyn" | "flat" }[] = [
    { key: "dyn", label: "Dynamic tariff", value: dyn, tone: "dyn" },
    { key: "flat", label: "Flat price", value: flat, tone: "flat" },
  ];
  const smaller = Math.min(dyn, flat);
  return (
    <div
      ref={ref}
      className="totals"
      role="img"
      aria-label={`Dynamic tariff ${money(dyn)} against flat price ${money(flat)} for the same recorded electricity.`}
    >
      {rows.map((r) => (
        <div className="total" key={r.key}>
          <span>{r.label}</span>
          <div className="track">
            <div className={`fill ${r.tone}`} style={{ width: seen ? `${(r.value / base) * 100}%` : "0%" }} />
            {r.value === base && r.value !== smaller && (
              <div className="tail" style={{ left: `${(smaller / base) * 100}%`, width: seen ? `${((r.value - smaller) / base) * 100}%` : "0%" }} />
            )}
          </div>
          <b>{money(r.value)}</b>
        </div>
      ))}
    </div>
  );
}

/** One mark per household, lower first and the exceptions last. Each is a button: choosing
 * one selects that household further down the page. Arrow keys move between marks. */
function Marks({ households, selected, onPick }: { households: Household[]; selected: string | null; onPick: (id: string) => void }) {
  const ordered = [...sortHouseholds(households, "pct")].reverse();
  const [focusIdx, setFocusIdx] = useState(0);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const lower = ordered.filter((h) => h.outcome_under_dynamic === "lower").length;
  const higher = ordered.filter((h) => h.outcome_under_dynamic === "higher").length;
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const keys: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, Home: -i, End: ordered.length - 1 - i };
    if (e.key in keys) {
      e.preventDefault();
      const next = Math.max(0, Math.min(ordered.length - 1, i + keys[e.key]));
      setFocusIdx(next);
      refs.current[next]?.focus();
    }
  };
  return (
    <div
      className="marks"
      role="group"
      aria-label={`${ordered.length} households: ${lower} lower under the dynamic tariff, ${higher} higher. Choose one to see its detail; the arrow keys move between them.`}
    >
      {ordered.map((h, i) => (
        <button
          key={h.household_id}
          type="button"
          className={`mark ${h.outcome_under_dynamic}`}
          tabIndex={i === focusIdx ? 0 : -1}
          aria-pressed={selected === h.household_id}
          aria-label={describe(h)}
          title={`${h.household_id}: ${outcomeWord(h.outcome_under_dynamic)} by ${signedPct(h.pct_of_flat.display)}`}
          onClick={() => onPick(h.household_id)}
          onKeyDown={(e) => onKey(e, i)}
          ref={(el) => {
            refs.current[i] = el;
          }}
        >
          <span aria-hidden="true">{outcomeGlyph(h.outcome_under_dynamic)}</span>
        </button>
      ))}
    </div>
  );
}

export function Hero({
  bundle,
  selected,
  onPick,
  onTour,
}: {
  bundle: Bundle;
  selected: string | null;
  onPick: (id: string) => void;
  onTour: () => void;
}) {
  const c = bundle.comparison;
  const w = bundle.source.warehouse;
  const compact = useMediaQuery("(max-width: 899px)");
  const year = bundle.schedule.first_date?.slice(0, 4) ?? "2013";
  const diff = useCountUp(Math.abs(c.flat_minus_dynamic.display), 1300);
  const dynStat = useCountUp(c.dynamic_charge.display, 1100);
  const flatStat = useCountUp(c.flat_charge.display, 1100);
  const pctStat = useCountUp(c.pct_of_flat.display ?? 0, 1300);
  const o = c.outcomes_under_dynamic;
  const direction = c.flat_minus_dynamic.display > 0 ? "lower" : c.flat_minus_dynamic.display < 0 ? "higher" : "the same";
  const exception = [...sortHouseholds(c.per_household, "pct")].find((h) => h.outcome_under_dynamic === "higher");
  const flatPence = c.flat_price.pence_per_kwh.replace(/0+$/, "");
  return (
    <header className="hero wrap" id="top">
      <DayShape hourBands={bundle.hour_bands} />
      <div className="eyebrow">The same electricity, priced two ways</div>
      <h1>Would the same electricity cost less if its price could change every 30 minutes?</h1>
      <p className="lede">
        In {year}, <strong>{c.households} households</strong> on the Low Carbon London trial recorded{" "}
        <strong>{integer(c.charged_readings)}</strong> half-hourly readings on a tariff whose price could change every
        half hour. We priced exactly those readings two ways: under that tariff, and at the trial's flat price of{" "}
        <strong>{flatPence}p per kWh</strong>.
      </p>

      <div className="opening">
        <div className="answer">
          <div className="answer-label">Under the dynamic tariff, the same electricity came out</div>
          <div className="answer-value" aria-live="off">
            <span className={`big ${direction === "lower" ? "volt" : "ember"}`}>{money(diff)}</span>
            <span className="word">{direction}</span>
          </div>
          <div className="answer-sub">
            {c.pct_of_flat.display === null ? "share of the flat-price charge undefined" : `${c.pct_of_flat.display.toFixed(1)}% of the flat-price charge`}
          </div>
          <Totals bundle={bundle} />
        </div>

        <div className="households-at-a-glance">
          <p className="outcomes">
            <b>{o.lower} households</b> came out lower. <b>{o.higher}</b> came out higher.
            {o.equal ? ` ${o.equal} came out the same.` : ""}
          </p>
          <Marks households={c.per_household} selected={selected} onPick={onPick} />
          <div className="marks-legend" aria-hidden="true">
            <span><i className="lower" />▲ lower under dynamic</span>
            <span><i className="higher" />▼ higher under dynamic</span>
          </div>
          <div className="actions">
            {exception ? (
              <button type="button" className="cta" onClick={() => onPick(exception.household_id)}>
                Why did {o.higher} go the other way? <span aria-hidden="true">↓</span>
              </button>
            ) : (
              <a className="cta" href="#households">
                See every household <span aria-hidden="true">↓</span>
              </a>
            )}
            <button type="button" className="tour-start" onClick={onTour}>
              Walk me through it <span aria-hidden="true">·</span> 2 min
            </button>
          </div>
        </div>
      </div>

      <p className="qualifier">
        Historical fixed-consumption comparison, not a bill or a savings claim. Assumptions A1 and A2 apply; the exact
        figures and both assumptions are below.
      </p>

      <details className="exact" open={!compact}>
        <summary>The exact figures, A1 and A2</summary>
        <div className="body">
        <div className="stats">
          <Stat label="Dynamic tariff (A1)" value={money(dynStat)} note={`exact £${c.dynamic_charge.exact}`} />
          <Stat label="Flat price (A2)" value={money(flatStat)} note={`exact £${c.flat_charge.exact}`} />
          <Stat
            label="Flat minus dynamic"
            value={signedMoney(c.flat_minus_dynamic.display)}
            tone={c.flat_minus_dynamic.display > 0 ? "volt" : "ember"}
            note="positive: the dynamic tariff was lower"
          />
          <Stat
            label="As % of the flat-price charge"
            value={signedPct(c.pct_of_flat.display === null ? null : pctStat)}
            tone={c.flat_minus_dynamic.display > 0 ? "volt" : "ember"}
            note={`denominator: flat-price charge · exact ${c.pct_of_flat.exact ? c.pct_of_flat.exact.slice(0, c.pct_of_flat.exact.indexOf(".") + 4) + "…" : "n/a"}%`}
          />
        </div>
        <p className="hint">
          A1: a reading's timestamp label and the schedule label denote the same half hour (assumed, not established).
          A2: the documented flat price of {flatPence}p applies to the whole year (its effective dates are unknown).{" "}
          {integer(w.readings_loaded)} readings from {w.source_files.length} of the dataset's {w.source_files_in_dataset}{" "}
          source files were loaded; the {c.households} time-of-use households among the {w.households} loaded are the
          ones the dynamic tariff applied to.
        </p>
        </div>
      </details>

      <PriceLadder bundle={bundle} />
    </header>
  );
}
