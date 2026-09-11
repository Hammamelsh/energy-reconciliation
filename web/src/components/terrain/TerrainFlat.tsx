import { useEffect, useRef, type KeyboardEvent, type PointerEvent } from "react";
import type { Terrain } from "../../lib/terrain";
import { cellAt, indexOf, monthStarts, moveCursor } from "../../lib/terrain";
import { money } from "../../lib/format";
import { cellFromFraction, paint, type Carpet, type Highlight } from "./flat";

/**
 * The flat map: two carpets side by side (charged kWh, dynamic charge) and, on request, a
 * third for coverage. One canvas pixel per cell, X = half-hour label, Y = date label,
 * brightness = value on a zero-based scale, hue = band. Nothing is smoothed: the canvas
 * is exactly slots × dates pixels and is scaled with pixelated rendering.
 */

const SLOT_TICKS = [0, 12, 24, 36];

function CarpetView({
  terrain,
  carpet,
  highlight,
  cursor,
  hover,
  onHover,
  onSelect,
  title,
  scale,
}: {
  terrain: Terrain;
  carpet: Carpet;
  highlight: Highlight;
  cursor: number | null;
  hover: number | null;
  onHover: (i: number | null) => void;
  onSelect: (i: number) => void;
  title: string;
  scale: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    canvas.width = terrain.grid.slots;
    canvas.height = terrain.grid.dates;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // no canvas: the values stay available through the readout and table
    const img = ctx.createImageData(terrain.grid.slots, terrain.grid.dates);
    paint(terrain, carpet, highlight, img.data);
    ctx.putImageData(img, 0, 0);
  }, [terrain, carpet, highlight]);

  const locate = (e: PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return null;
    return cellFromFraction(terrain, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
  };
  const marker = (i: number | null, kind: "cursor" | "hover") => {
    if (i === null) return null;
    const c = cellAt(terrain, i);
    return (
      <div
        className={`cell-marker ${kind}`}
        aria-hidden="true"
        style={{
          left: `${(c.slot / terrain.grid.slots) * 100}%`,
          top: `${(c.dateIndex / terrain.grid.dates) * 100}%`,
          width: `${100 / terrain.grid.slots}%`,
          height: `${100 / terrain.grid.dates}%`,
        }}
      />
    );
  };
  const months = monthStarts(terrain.grid.date_labels);
  const pk = carpet === "kwh" ? terrain.peaks.kwh : carpet === "charge" ? terrain.peaks.charge : null;
  const peak = pk
    ? { dateIndex: terrain.grid.date_labels.indexOf(pk.date), slot: pk.slot, label: carpet === "kwh" ? `${pk.kwh.display} kWh` : money(pk.charge.display) }
    : null;
  return (
    <figure className="carpet">
      <figcaption>{title}</figcaption>
      <div className="carpet-body">
        <div className="month-gutter" aria-hidden="true">
          {months.map((m) => (
            <span key={m.month} style={{ top: `${(m.dateIndex / terrain.grid.dates) * 100}%` }}>
              {m.label}
            </span>
          ))}
        </div>
        <div className="carpet-frame">
          <canvas
            ref={ref}
            aria-hidden="true"
            onPointerMove={(e) => onHover(locate(e))}
            onPointerLeave={() => onHover(null)}
            onPointerDown={(e) => {
              const i = locate(e);
              if (i !== null) onSelect(i);
            }}
          />
          {marker(hover, "hover")}
          {marker(cursor, "cursor")}
          {peak && peak.dateIndex >= 0 && (
            <div
              className="peak-marker"
              aria-hidden="true"
              style={{
                left: `${(peak.slot / terrain.grid.slots) * 100}%`,
                top: `${(peak.dateIndex / terrain.grid.dates) * 100}%`,
                width: `${100 / terrain.grid.slots}%`,
                height: `${100 / terrain.grid.dates}%`,
              }}
            >
              <span style={{ [peak.slot > terrain.grid.slots / 2 ? "right" : "left"]: "calc(100% + 6px)" }}>{peak.label} in one half hour</span>
            </div>
          )}
        </div>
        <div className="slot-axis" aria-hidden="true">
          {SLOT_TICKS.map((s) => (
            <span key={s} style={{ left: `${(s / terrain.grid.slots) * 100}%` }}>
              {terrain.grid.slot_labels[s]}
            </span>
          ))}
          <span style={{ left: "100%" }}>24:00</span>
        </div>
      </div>
      <div className="carpet-scale">{scale}</div>
    </figure>
  );
}

export function TerrainFlat({
  terrain,
  highlight,
  cursor,
  hover,
  onHover,
  onSelect,
  onCursor,
  showCoverage,
}: {
  terrain: Terrain;
  highlight: Highlight;
  cursor: number | null;
  hover: number | null;
  onHover: (i: number | null) => void;
  onSelect: (i: number) => void;
  onCursor: (i: number) => void;
  showCoverage: boolean;
}) {
  const g = terrain.grid;
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const from = cursor ?? indexOf(terrain, 0, 0);
    const moves: Record<string, [number, number]> = {
      ArrowRight: [0, 1],
      ArrowLeft: [0, -1],
      ArrowDown: [1, 0],
      ArrowUp: [-1, 0],
      PageDown: [7, 0],
      PageUp: [-7, 0],
    };
    let next: number | null = null;
    if (e.key in moves) next = moveCursor(terrain, from, ...moves[e.key]);
    else if (e.key === "Home") next = e.shiftKey ? indexOf(terrain, 0, cellAt(terrain, from).slot) : indexOf(terrain, cellAt(terrain, from).dateIndex, 0);
    else if (e.key === "End") next = e.shiftKey ? indexOf(terrain, g.dates - 1, cellAt(terrain, from).slot) : indexOf(terrain, cellAt(terrain, from).dateIndex, g.slots - 1);
    if (next !== null) {
      e.preventDefault();
      onCursor(next);
    }
  };
  const common = { terrain, highlight, cursor, hover, onHover, onSelect };
  return (
    <div
      className="carpets"
      role="application"
      tabIndex={0}
      aria-label={`Flat map of ${g.dates} date labels by ${g.slots} half-hour labels, ${g.cells} cells. Left and Right arrows move one half hour, Up and Down move one date, Page Up and Page Down move a week, Home and End reach the first and last half hour of the day. The readout below states the selected cell.`}
      aria-describedby="year-readout"
      onKeyDown={onKey}
      onFocus={() => {
        if (cursor === null) onCursor(indexOf(terrain, 0, 0));
      }}
    >
      <CarpetView {...common} carpet="kwh" title="Charged electricity, kWh" scale={`0 to ${terrain.scale.kwh.max} kWh per half hour, pooled`} />
      <CarpetView {...common} carpet="charge" title="Dynamic scenario charge, £" scale={`£0 to £${terrain.scale.charge.max.toFixed(2)} per half hour, pooled`} />
      {showCoverage && (
        <CarpetView
          {...common}
          carpet="coverage"
          title="Households contributing"
          scale={`${terrain.coverage.households_per_cell_min} (dark) to ${terrain.coverage.households_per_cell_max} (light) of ${terrain.totals.households}`}
        />
      )}
    </div>
  );
}
