import type { Comparison } from "../lib/bundle";
import { countAt } from "../lib/breakeven";
import { EMBER, LINE, NEUTRAL, VOLT } from "../lib/palette";
import { pence } from "../lib/format";

export function BreakEven({
  comparison,
  value,
  onChange,
}: {
  comparison: Comparison;
  value: number;
  onChange: (v: number) => void;
}) {
  const hh = comparison.per_household;
  const flat = Number(comparison.flat_price.pence_per_kwh);
  const pooled = comparison.breakeven_flat_price.display ?? flat;
  const counts = countAt(hh, value);
  const evens = hh.map((h) => h.breakeven_flat_price.display).filter((v): v is number => v !== null);
  const lo = Math.floor(Math.min(...evens, flat) - 1);
  const hi = Math.ceil(Math.max(...evens, flat) + 1);
  const W = 800;
  const x = (p: number) => 10 + ((p - lo) / (hi - lo)) * (W - 20);
  return (
    <div className="card" id="what-if">
      <h3>What if the flat price had been different?</h3>
      <p className="sub" style={{ marginBottom: 8 }}>
        Each household has a break-even flat price — the price at which its recorded consumption would have
        cost exactly what it did on the dynamic tariff. Slide to compare a flat price with all 27 of them.
      </p>
      <label htmlFor="flat-slider" className="big">
        At a flat price of <span className="ember">{value.toFixed(3)}p</span> per kWh,{" "}
        <span className="volt">{counts.lower}</span> of {hh.length} households would have paid less on the
        dynamic tariff, {counts.higher} more{counts.equal ? `, ${counts.equal} the same` : ""}.
      </label>
      <input
        id="flat-slider"
        className="slider"
        type="range"
        min={lo}
        max={hi}
        step={0.001}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={`${value.toFixed(3)} pence per kWh: ${counts.lower} lower, ${counts.higher} higher`}
      />
      <div className="ticks" aria-hidden="true">
        <svg viewBox={`0 0 ${W} 46`}>
          <line x1={10} x2={W - 10} y1={20} y2={20} stroke={LINE} strokeWidth={2} />
          {evens.map((p, i) => (
            <line key={i} x1={x(p)} x2={x(p)} y1={12} y2={28} stroke={p < value ? VOLT : p > value ? EMBER : NEUTRAL} strokeWidth={2} />
          ))}
          <line x1={x(value)} x2={x(value)} y1={4} y2={36} stroke="#fff" strokeWidth={2} />
          <text x={x(value)} y={45} fontSize={11} fill="#fff" textAnchor="middle">
            {value.toFixed(3)}p
          </text>
          <circle cx={x(flat)} cy={34} r={4} fill="none" stroke={EMBER} strokeWidth={2} />
          <circle cx={x(pooled)} cy={34} r={4} fill="none" stroke={NEUTRAL} strokeWidth={2} />
        </svg>
      </div>
      <div className="toolbar">
        <span>
          Each tick is one household's break-even price. ○ ember: documented flat price {flat.toFixed(3)}p · ○ grey:
          pooled break-even {pence(pooled)}
        </span>
        <span className="seg">
          <button type="button" onClick={() => onChange(flat)} aria-pressed={value === flat}>
            documented {flat.toFixed(3)}p
          </button>
          <button type="button" onClick={() => onChange(pooled)} aria-pressed={value === pooled}>
            break-even {pooled.toFixed(3)}p
          </button>
        </span>
      </div>
      <p className="hint">
        Hypothetical and fixed-consumption: it compares prices against consumption that was recorded on the dynamic
        tariff. It does not say what anyone would have paid, or done, on a flat one.
      </p>
    </div>
  );
}
