import type { Bundle } from "../lib/bundle";
import { integer, money, signedMoney, signedPct } from "../lib/format";
import { useCountUp } from "../hooks";
import { PriceLadder } from "./PriceLadder";
import { DayShape } from "./DayShape";

function Stat({
  label,
  value,
  tone,
  note,
}: {
  label: string;
  value: string;
  tone?: "volt" | "ember";
  note: string;
}) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className={`value ${tone ?? ""}`}>{value}</div>
      <div className="note">{note}</div>
    </div>
  );
}

export function Hero({ bundle, onTour }: { bundle: Bundle; onTour: () => void }) {
  const c = bundle.comparison;
  const w = bundle.source.warehouse;
  const year = bundle.schedule.first_date?.slice(0, 4) ?? "2013";
  const dyn = useCountUp(c.dynamic_charge.display, 1100);
  const flat = useCountUp(c.flat_charge.display, 1100);
  const diff = useCountUp(c.flat_minus_dynamic.display, 1300);
  const pctv = useCountUp(c.pct_of_flat.display ?? 0, 1300);
  const o = c.outcomes_under_dynamic;
  const direction =
    c.flat_minus_dynamic.display > 0 ? "lower" : c.flat_minus_dynamic.display < 0 ? "higher" : "the same";
  return (
    <header className="hero wrap" id="top">
      <DayShape hourBands={bundle.hour_bands} />
      <div className="eyebrow">Low Carbon London trial · {year} · historical scenario</div>
      <h1>
        The same electricity,{" "}
        <br />
        priced two ways.
      </h1>
      <p className="lede">
        <strong>{c.households} households</strong> on a dynamic tariff recorded{" "}
        <strong>{integer(c.charged_readings)}</strong> half-hourly readings in {year}. We priced
        exactly those readings under the tariff they were on and, hypothetically, at the trial's
        documented flat price of <strong>{c.flat_price.pence_per_kwh.replace(/0+$/, "")}p per kWh</strong>.
        Same electricity, two prices. Not a bill, a saving or advice.
      </p>

      <div className="stats" aria-live="off">
        <Stat label="Dynamic tariff (A1)" value={money(dyn)} note={`exact £${c.dynamic_charge.exact}`} />
        <Stat label="Flat price (A2)" value={money(flat)} note={`exact £${c.flat_charge.exact}`} />
        <Stat
          label="Flat minus dynamic"
          value={signedMoney(diff)}
          tone={c.flat_minus_dynamic.display > 0 ? "volt" : "ember"}
          note="positive: the dynamic tariff was lower"
        />
        <Stat
          label="As % of the flat-price charge"
          value={signedPct(c.pct_of_flat.display === null ? null : pctv)}
          tone={c.flat_minus_dynamic.display > 0 ? "volt" : "ember"}
          note={`denominator: flat-price charge · exact ${c.pct_of_flat.exact ? c.pct_of_flat.exact.slice(0, c.pct_of_flat.exact.indexOf('.') + 4) + '…' : '—'}%`}
        />
      </div>

      <p className="verdict">
        For this recorded consumption the dynamic tariff came out <strong>{direction}</strong>.{" "}
        <strong>{o.lower} households</strong> were lower under it, <strong>{o.higher}</strong> higher
        {o.equal ? ` and ${o.equal} equal` : ""}.
        {o.higher > 0 ? " The ones that went the other way are the interesting part." : ""}
      </p>
      <a className="cta" href="#households">
        See every household <span aria-hidden="true">↓</span>
      </a>
      <button type="button" className="tour-start" onClick={onTour}>
        Walk me through it <span aria-hidden="true">·</span> 2 min
      </button>

      <PriceLadder bundle={bundle} />
      <p className="hint">
        {integer(w.readings_loaded)} readings from {w.source_files.length} of the dataset's{" "}
        {w.source_files_in_dataset} source files were loaded; the {c.households} time-of-use
        households among the {w.households} loaded are the ones the dynamic tariff applied to.
      </p>
    </header>
  );
}
