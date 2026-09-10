import { useMemo, useState, type KeyboardEvent } from "react";
import type { Household } from "../lib/bundle";
import { integer, money, outcomeGlyph, outcomeWord, pct, signedMoney, signedPct } from "../lib/format";
import { COLOUR, describe, sortHouseholds, type SortKey } from "../lib/households";
import { useInView, useMediaQuery } from "../hooks";
import { DIM, GRID, MUTED, TEXT } from "../lib/palette";

export type { SortKey } from "../lib/households";

export function HouseholdChart({
  households,
  selected,
  onSelect,
  sortKey,
}: {
  households: Household[];
  selected: string | null;
  onSelect: (id: string) => void;
  sortKey: SortKey;
}) {
  const compact = useMediaQuery("(max-width: 700px)");
  const [wrapRef, seen] = useInView<HTMLDivElement>("0px 0px -15% 0px");
  const rows = useMemo(() => sortHouseholds(households, sortKey), [households, sortKey]);
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);

  const values = rows.map((h) => (sortKey === "gbp" ? h.flat_minus_dynamic.display : (h.pct_of_flat.display ?? 0)));
  const minV = Math.min(0, ...values);
  const maxV = Math.max(0, ...values);
  const W = compact ? 380 : 760;
  const rowH = compact ? 26 : 24;
  const top = 26;
  const left = compact ? 96 : 172;
  const right = compact ? 58 : 60;
  const fs = compact ? 10.5 : 12;
  const H = top + rows.length * rowH + 30;
  const plotW = W - left - right;
  const scale = (v: number) => left + ((v - minV) / (maxV - minV || 1)) * plotW;
  const zero = scale(0);
  const unit = sortKey === "gbp" ? "£" : "%";

  const move = (e: KeyboardEvent<SVGGElement>, index: number) => {
    const keys: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, Home: -index, End: rows.length - 1 - index };
    if (e.key in keys) {
      e.preventDefault();
      const next = rows[Math.max(0, Math.min(rows.length - 1, index + keys[e.key]))];
      onSelect(next.household_id);
      const el = (e.currentTarget.parentElement as SVGElement | null)?.querySelector<SVGGElement>(
        `[data-id="${next.household_id}"]`,
      );
      el?.focus();
    }
  };

  const ticks = useMemo(() => {
    const span = maxV - minV;
    const step = span > 40 ? 10 : span > 16 ? 4 : span > 8 ? 2 : 1;
    const out: number[] = [];
    for (let v = Math.ceil(minV / step) * step; v <= maxV; v += step) out.push(Number(v.toFixed(2)));
    return out;
  }, [minV, maxV]);

  const hovered = hover ? rows.find((h) => h.household_id === hover.id) : undefined;

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg
        className="chart"
        viewBox={`0 0 ${W} ${H}`}
        role="group"
        aria-label={`Each household's difference between the flat-price charge and the dynamic charge, sorted. ${rows.length} households. Use the arrow keys to move between households.`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={scale(t)} x2={scale(t)} y1={top - 6} y2={H - 26} stroke={GRID} strokeWidth={1} />
            <text x={scale(t)} y={H - 10} textAnchor="middle" fontSize={compact ? 10 : 11} fill={DIM}>
              {sortKey === "gbp" ? `${t < 0 ? "−" : ""}£${Math.abs(t)}` : `${t}%`}
            </text>
          </g>
        ))}
        <line x1={zero} x2={zero} y1={top - 8} y2={H - 26} stroke={TEXT} strokeWidth={1.5} />
        <text x={zero + 6} y={top - 10} fontSize={11} fill={MUTED}>
          dynamic lower →
        </text>
        <text x={zero - 6} y={top - 10} fontSize={11} fill={MUTED} textAnchor="end">
          ← flat lower
        </text>
        {rows.map((h, i) => {
          const v = sortKey === "gbp" ? h.flat_minus_dynamic.display : (h.pct_of_flat.display ?? 0);
          const y = top + i * rowH;
          const x0 = seen ? Math.min(zero, scale(v)) : zero;
          const w = seen ? Math.max(1, Math.abs(scale(v) - zero)) : 1;
          const isSel = h.household_id === selected;
          const partial = (h.coverage.display ?? 100) < 99;
          const label = `${outcomeGlyph(h.outcome_under_dynamic)} ${sortKey === "gbp" ? signedMoney(v) : signedPct(v)}`;
          // a negative bar grows leftwards into the id gutter, so its label goes to the right of zero
          const labelX = v >= 0 ? scale(v) + 6 : zero + 6;
          return (
            <g
              key={h.household_id}
              data-id={h.household_id}
              className={`row ${isSel ? "selected" : ""}`}
              role="button"
              tabIndex={isSel || (!selected && i === rows.length - 1) ? 0 : -1}
              aria-label={describe(h)}
              aria-pressed={isSel}
              onClick={() => onSelect(h.household_id)}
              onFocus={() => onSelect(h.household_id)}
              onKeyDown={(e) => move(e, i)}
              onMouseEnter={(e) => setHover({ id: h.household_id, x: e.clientX, y: e.clientY })}
              onMouseMove={(e) => setHover({ id: h.household_id, x: e.clientX, y: e.clientY })}
              onMouseLeave={() => setHover(null)}
            >
              <rect className="halo" x={0} y={y - 1} width={W} height={rowH} fill="rgba(198,244,58,0.08)" rx={4} />
              <text x={left - 8} y={y + rowH / 2 + 4} textAnchor="end" fontSize={fs} fill={isSel ? "#fff" : TEXT} fontFamily="ui-monospace, Menlo, monospace">
                {h.household_id}
              </text>
              <rect className="bar" x={x0} y={y + 4} width={w} height={rowH - 8} rx={3} fill={COLOUR[h.outcome_under_dynamic]} stroke={isSel ? "#fff" : "none"} strokeWidth={1.5} />
              <text x={labelX} y={y + rowH / 2 + 4} textAnchor="start" fontSize={compact ? 10 : 11} fill={TEXT}>
                {label}
                {partial && (
                  <tspan fill="#ffb27a" dx={6}>
                    {compact ? `· ${pct(h.coverage.display, 1)} cov.` : `· ${pct(h.coverage.display)} coverage`}
                  </tspan>
                )}
              </text>
            </g>
          );
        })}
        <text x={W / 2} y={H - 0.5} textAnchor="middle" fontSize={11} fill={MUTED} fontStyle="italic">
          {sortKey === "gbp" ? "flat-price charge minus dynamic charge" : "difference as % of the household's flat-price charge"}
        </text>
      </svg>
      {hovered && hover && (
        <div
          className="tooltip"
          role="presentation"
          style={{ left: `min(calc(100% - 270px), ${hover.x + 14}px)`, top: hover.y + 14, position: "fixed" }}
        >
          <b>{hovered.household_id}</b>: {outcomeWord(hovered.outcome_under_dynamic)}
          <br />
          dynamic {money(hovered.dynamic_charge.display)} · flat {money(hovered.flat_charge.display)}
          <br />
          difference {signedMoney(hovered.flat_minus_dynamic.display)} ({signedPct(hovered.pct_of_flat.display)})
          <br />
          {integer(hovered.charged_readings)} of {integer(hovered.schedule_slots)} half hours ·{" "}
          {pct(hovered.coverage.display)} coverage
        </div>
      )}
      <p className="hint">
        Sorted {sortKey === "gbp" ? "by pounds" : sortKey === "coverage" ? "by coverage" : "by percentage"}. Volt-green ▲ means the
        dynamic tariff was lower for that household; ember ▼ means higher. Click or Tab into a bar and use the arrow keys.{" "}
        Unit: {unit}.
      </p>
    </div>
  );
}
