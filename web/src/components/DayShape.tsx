import type { HourBands } from "../lib/bundle";
import { EMBER, VOLT } from "../lib/palette";

/**
 * The shape of the day, drawn from the sample's charged kWh by hour: a faint, real curve
 * behind the hero instead of decoration. Aggregates only; no household. Presentation only.
 */
export function DayShape({ hourBands }: { hourBands: HourBands }) {
  const bands = ["Low", "Normal", "High"] as const;
  const totals = Array.from({ length: 24 }, (_, h) =>
    bands.reduce((s, b) => s + (hourBands.charged_kwh_by_band_and_hour[b]?.[h]?.kwh.display ?? 0), 0),
  );
  const max = Math.max(...totals, 1);
  const W = 1000;
  const H = 220;
  const x = (i: number) => (i / 23) * W;
  const y = (v: number) => H - 20 - (v / max) * (H - 40);
  const pts = totals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const line = `M ${pts.join(" L ")}`;
  const area = `${line} L ${W},${H} L 0,${H} Z`;
  const peak = totals.indexOf(max);
  return (
    <svg className="dayshape" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="ds" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={VOLT} stopOpacity="0.18" />
          <stop offset="1" stopColor={VOLT} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#ds)" />
      <path d={line} fill="none" stroke={VOLT} strokeOpacity="0.7" strokeWidth={2} className="dayline" />
      <circle cx={x(peak)} cy={y(max)} r={4} fill={EMBER} opacity={0.95} />
    </svg>
  );
}
