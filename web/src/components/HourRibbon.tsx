import type { HourBands } from "../lib/bundle";
import { useMediaQuery } from "../hooks";
import { BAND, DIM, EMBER, INK, MUTED, TEXT } from "../lib/palette";

const BANDS = ["Low", "Normal", "High"] as const;
const FILL = BAND;

/** Two 24-hour strips: when the schedule placed its High band, and when the charged
 * electricity was used — aggregates only, hour of the label as written. */
export function HourRibbon({ hourBands }: { hourBands: HourBands }) {
  const compact = useMediaQuery("(max-width: 700px)");
  const high = hourBands.schedule_slots_by_band_and_hour.High ?? new Array(24).fill(0);
  const maxHigh = Math.max(...high, 1);
  const kwh = BANDS.map((b) => (hourBands.charged_kwh_by_band_and_hour[b] ?? []).map((c) => c?.kwh.display ?? 0));
  const totals = Array.from({ length: 24 }, (_, h) => kwh.reduce((s, arr) => s + (arr[h] ?? 0), 0));
  const maxTotal = Math.max(...totals, 1);
  const W = compact ? 390 : 960;
  const left = compact ? 8 : 50;
  const colW = (W - left - 10) / 24;
  const fs = compact ? 9 : 12;
  const peakHours = high.map((v, i) => ({ v, i })).filter((x) => x.v === maxHigh).map((x) => x.i);
  return (
    <div className="card ribbon">
      <h3>When the expensive band fell — and when the electricity was used</h3>
      <p className="sub" style={{ marginBottom: 10 }}>
        Top: how many of the year's High-price half hours the schedule placed in each hour of the day. Bottom: charged
        kWh by hour across all 27 households, coloured by the band it was priced in.
      </p>
      <svg
        viewBox={`0 0 ${W} 250`}
        role="img"
        aria-label={`Schedule High-band slots by hour of day, peaking at ${maxHigh} in hours ${peakHours.join(", ")}; and charged kWh by hour and band.`}
      >
        <text x={compact ? 8 : 0} y={16} fontSize={fs} fill={MUTED}>
          High-price half hours in the schedule
        </text>
        {high.map((v, i) => (
          <g key={`h${i}`}>
            <rect x={left + i * colW} y={24} width={colW - 3} height={22} rx={3} fill={EMBER} opacity={0.15 + 0.85 * (v / maxHigh)} />
            {!compact && (
              <text x={left + i * colW + (colW - 3) / 2} y={39} fontSize={9.5} textAnchor="middle" fill={v / maxHigh > 0.55 ? INK : TEXT}>
                {v}
              </text>
            )}
          </g>
        ))}
        <text x={compact ? 8 : 0} y={76} fontSize={fs} fill={MUTED}>
          Charged kWh by hour
        </text>
        {totals.map((t, i) => {
          let yTop = 210;
          return (
            <g key={`k${i}`}>
              {BANDS.map((b, bi) => {
                const v = kwh[bi][i] ?? 0;
                const hgt = (v / maxTotal) * 120;
                yTop -= hgt;
                return <rect key={b} x={left + i * colW} y={yTop} width={colW - 3} height={hgt} fill={FILL[b]} />;
              })}
              {(!compact || i % 3 === 0) && (
                <text x={left + i * colW + (colW - 3) / 2} y={226} fontSize={compact ? 9 : 10} textAnchor="middle" fill={DIM}>
                  {i}
                </text>
              )}
              <title>{`Hour ${i}: ${t.toFixed(0)} kWh`}</title>
            </g>
          );
        })}
        <text x={W / 2} y={244} fontSize={compact ? 9 : 11} textAnchor="middle" fill={DIM}>
          hour of the timestamp label as written (no timezone applied)
        </text>
      </svg>
      <div className="legend" style={{ marginTop: 8 }}>
        {BANDS.map((b) => (
          <span key={b}>
            <i style={{ background: FILL[b] }} />
            {b}
          </span>
        ))}
      </div>
      <p className="hint">{hourBands.caveat}</p>
    </div>
  );
}
