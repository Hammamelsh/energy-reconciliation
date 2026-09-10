import { useState } from "react";
import type { Household } from "../lib/bundle";
import { COLOUR, highShare } from "../lib/households";
import { money, outcomeWord, signedPct } from "../lib/format";
import { useMediaQuery } from "../hooks";
import { DIM, GRID, INK, MUTED, TEXT } from "../lib/palette";

/**
 * Why did two go the other way? One picture: the share of a household's electricity that
 * fell in the High band against its outcome. Both values come from the bundle; the page
 * plots them and says what is visible.
 */
export function Insight({ households, selected, onSelect }: { households: Household[]; selected: string | null; onSelect: (id: string) => void }) {
  const compact = useMediaQuery("(max-width: 700px)");
  const [hover, setHover] = useState<string | null>(null);
  const W = compact ? 380 : 620;
  const H = compact ? 300 : 340;
  const L = compact ? 44 : 56;
  const R = 18;
  const T = 18;
  const B = compact ? 46 : 44;
  const xs = households.map(highShare);
  const ys = households.map((h) => h.pct_of_flat.display ?? 0);
  const xMax = Math.ceil(Math.max(...xs) + 1);
  const yMin = Math.floor(Math.min(0, ...ys) - 1);
  const yMax = Math.ceil(Math.max(...ys) + 1);
  const x = (v: number) => L + (v / xMax) * (W - L - R);
  const y = (v: number) => T + (1 - (v - yMin) / (yMax - yMin)) * (H - T - B);
  const ticksX = Array.from({ length: xMax + 1 }, (_, i) => i).filter((v) => v % (xMax > 8 ? 2 : 1) === 0);
  const ticksY = [] as number[];
  for (let v = yMin; v <= yMax; v += yMax - yMin > 10 ? 4 : 2) ticksY.push(v);
  const highest = [...households].sort((a, b) => highShare(b) - highShare(a));
  const flippers = households.filter((h) => h.outcome_under_dynamic === "higher");
  const active = hover ?? selected;
  const fs = compact ? 10 : 11;
  return (
    <div className="card">
      <h3>Why did two go the other way?</h3>
      <p className="sub" style={{ marginBottom: 6 }}>
        Each dot is a household: how much of its electricity fell in High-price half hours, against how it came out.
        The two ember dots used the largest High shares of all {households.length}:{" "}
        {flippers.map((h) => `${h.household_id} (${highShare(h).toFixed(1)}%)`).join(" and ")}. The household
        that gained most, {highest.at(-1)?.household_id}, used the least ({highShare(highest.at(-1)!).toFixed(1)}%).
        Same prices for everyone; the timing of their electricity decided the outcome.
      </p>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="chart"
        role="img"
        aria-label={`Scatter of ${households.length} households: share of electricity in the High band (0 to ${xMax}%) against the difference as a percentage of the flat-price charge. Households with a larger High share sit lower; the two that came out higher under the dynamic tariff have the largest High shares.`}
      >
        {ticksX.map((v) => (
          <g key={`x${v}`}>
            <line x1={x(v)} x2={x(v)} y1={T} y2={H - B} stroke={GRID} />
            <text x={x(v)} y={H - B + 14} textAnchor="middle" fontSize={fs} fill={DIM}>{v}%</text>
          </g>
        ))}
        {ticksY.map((v) => (
          <g key={`y${v}`}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={v === 0 ? TEXT : GRID} strokeWidth={v === 0 ? 1.2 : 1} />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize={fs} fill={DIM}>{v > 0 ? `+${v}` : v}%</text>
          </g>
        ))}
        <text x={(L + W - R) / 2} y={H - 4} textAnchor="middle" fontSize={fs} fill={MUTED}>share of electricity in High-price half hours</text>
        <text transform={`translate(12 ${(T + H - B) / 2}) rotate(-90)`} textAnchor="middle" fontSize={fs} fill={MUTED}>difference, % of flat-price charge</text>
        {households.map((h) => {
          const isActive = h.household_id === active;
          return (
            <g
              key={h.household_id}
              onMouseEnter={() => setHover(h.household_id)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect(h.household_id)}
              style={{ cursor: "pointer" }}
            >
              <circle cx={x(highShare(h))} cy={y(h.pct_of_flat.display ?? 0)} r={isActive ? 8 : 5.5} fill={COLOUR[h.outcome_under_dynamic]} stroke={isActive ? "#fff" : INK} strokeWidth={isActive ? 2 : 1} className="dot" />
              {(isActive || h.outcome_under_dynamic === "higher") && (
                <text x={x(highShare(h)) + 10} y={y(h.pct_of_flat.display ?? 0) + 4} fontSize={fs} fill={TEXT} fontFamily="ui-monospace, Menlo, monospace">
                  {h.household_id}
                </text>
              )}
              <title>{`${h.household_id}: ${highShare(h).toFixed(1)}% of electricity in High; ${signedPct(h.pct_of_flat.display)} (${money(h.flat_minus_dynamic.display)}), ${outcomeWord(h.outcome_under_dynamic)}`}</title>
            </g>
          );
        })}
      </svg>
      <p className="hint">
        Hover or click a dot; the selected household is highlighted here and in the bar chart. This describes
        where each household's electricity fell in time, not whether anyone chose that timing.
      </p>
    </div>
  );
}
