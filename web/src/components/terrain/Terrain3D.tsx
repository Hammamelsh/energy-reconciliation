import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { Mode, Terrain } from "../../lib/terrain";
import { cellAt, indexOf, maxOf, monthStarts, moveCursor, scaleTicks } from "../../lib/terrain";
import type { Highlight } from "./flat";
import { createScene, webglAvailable, HMAX, type Handle, type ViewPreset } from "./scene";
import { placeLabel } from "./label";
import { touchIntent, type TouchIntent } from "./gesture";

type Overlay = {
  months: { x: number; y: number; label: string }[];
  slots: { x: number; y: number; label: string }[];
  bar: { x0: number; y0: number; x1: number; y1: number; ticks: { x: number; y: number; label: string }[]; unit: boolean } | null;
  peak: { x: number; y: number; label: string; detail: string; when: string; what: string } | null;
  /** The selected cell's top, when it is in view: a neutral marker the colours cannot be confused with. */
  sel: { x: number; y: number } | null;
  size: { w: number; h: number };
  /** Looking straight down: heights are invisible, so a pinned annotation keeps one line. */
  topDown: boolean;
};

const SLOT_TICKS = [0, 12, 24, 36, 48];
const VIEWS: { key: ViewPreset; label: string }[] = [
  { key: "default", label: "Default" },
  { key: "top", label: "Top-down" },
  { key: "side", label: "Side" },
];

/**
 * The 3D view: a focusable canvas with an accessible name, keyboard cursor, pointer orbit
 * (mouse or pen only; touch scrolls the page), and an SVG overlay for the axes and the
 * scale bar so labels stay crisp text. Values never live only in the canvas: the readout in
 * the section and the flat map carry the same cells.
 */
export default function Terrain3D({
  terrain,
  mode,
  highlight,
  cursor,
  hover,
  reducedMotion,
  onHover,
  onSelect,
  onCursor,
  onUnavailable,
}: {
  terrain: Terrain;
  mode: Mode;
  highlight: Highlight;
  cursor: number | null;
  hover: number | null;
  reducedMotion: boolean;
  onHover: (i: number | null) => void;
  onSelect: (i: number) => void;
  onCursor: (i: number) => void;
  onUnavailable: (why: string) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const handle = useRef<Handle | null>(null);
  const drag = useRef<{ x: number; y: number; x0: number; y0: number; moved: boolean; id: number; touch: boolean; intent: TouchIntent } | null>(null);
  const [view, setView] = useState<ViewPreset>("default");
  // A drag leaves the preset the camera started from; no preset shows as pressed until one
  // is chosen again. The request counter re-applies a preset even when it is already chosen.
  const [turned, setTurned] = useState(false);
  const [viewRequest, setViewRequest] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [dragging, setDragging] = useState(false);
  const modeRef = useRef(mode);
  const cursorRef = useRef(cursor);
  const computeRef = useRef<(() => void) | null>(null);
  const unavailable = useRef(onUnavailable);
  useEffect(() => {
    modeRef.current = mode;
    cursorRef.current = cursor;
    unavailable.current = onUnavailable;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (!webglAvailable()) {
      unavailable.current("this browser provides no WebGL context");
      return;
    }
    let h: Handle;
    try {
      h = createScene(canvas, terrain, { onContextLost: (why) => unavailable.current(why) });
    } catch (error) {
      unavailable.current(error instanceof Error ? error.message : String(error));
      return;
    }
    handle.current = h;
    // measurements read the scene's own counters when the page is opened with ?measure
    if (new URLSearchParams(window.location.search).has("measure")) {
      (window as Window & { __terrainStats?: () => Handle["stats"] }).__terrainStats = () => ({ ...h.stats });
    }
    const W = h.width;
    const D = h.depth;
    const xOf = (s: number) => s - W / 2;
    const zOf = (j: number) => j - D / 2;
    const compute = () => {
      const mode = modeRef.current;
      const months = monthStarts(terrain.grid.date_labels).map((m) => {
        const p = h.project(xOf(0) - 1.4, 0, zOf(m.dateIndex) + 0.5);
        return { x: p.x, y: p.y, label: m.label };
      });
      let slots = SLOT_TICKS.map((s) => {
        const p = h.project(xOf(s), 0, zOf(D) + 1.4);
        return { x: p.x, y: p.y, label: s === 48 ? "24:00" : terrain.grid.slot_labels[s] };
      });
      // hour ticks that would overprint (a low elevation, or the short axis of a phone) are
      // thinned to every other one, or dropped altogether, rather than drawn as a stack
      const gapOf = (s: typeof slots) => (s.length > 1 ? Math.hypot(s[1].x - s[0].x, s[1].y - s[0].y) : Infinity);
      if (gapOf(slots) < 11) slots = [];
      while (slots.length > 2 && gapOf(slots) < 36) slots = slots.filter((_, i) => i % 2 === 0);
      if (slots.length === 2 && gapOf(slots) < 36) slots = [];
      const max = maxOf(terrain, mode);
      // on a narrow canvas (a phone) the unit rides on the top tick, where a separate unit
      // label would run into the peak annotation pinned to the left edge
      const narrow = (canvas.clientWidth || 800) < 480;
      const bx = xOf(0) - 1;
      const bz = zOf(0) - 4;
      const base = h.project(bx, 0, bz);
      const top = h.project(bx, HMAX, bz);
      const bar =
        h.elevation > 80 || Math.abs(top.y - base.y) < 30
          ? null
          : {
              x0: base.x,
              y0: base.y,
              x1: top.x,
              y1: top.y,
              ticks: scaleTicks(max).map((v, i, all) => {
                const p = h.project(bx, (v / max) * HMAX, bz);
                const topmost = narrow && i === all.length - 1;
                return { x: p.x, y: p.y, label: mode === "kwh" ? `${v}${topmost ? " kWh" : ""}` : `£${v}` };
              }),
              unit: !narrow,
            };
      const pk = mode === "kwh" ? terrain.peaks.kwh : terrain.peaks.charge;
      let peak: Overlay["peak"] = null;
      if (pk) {
        const di = terrain.grid.date_labels.indexOf(pk.date);
        const v = mode === "kwh" ? pk.kwh.display : pk.charge.display;
        const p = h.project(xOf(pk.slot) + 0.5, (v / max) * HMAX, zOf(di) + 0.5);
        const value = mode === "kwh" ? `${pk.kwh.display} kWh` : `£${pk.charge.display.toFixed(2)}`;
        // when the peak is outside the view (a zoom on another cell), no annotation floats off it
        if (p.visible) peak = {
          x: p.x,
          y: p.y,
          label: `${value} in one half hour`,
          detail: `${pk.date}, ${pk.slot_label} label, ${pk.band} band, ${pk.households} households`,
          when: `${pk.date}, ${pk.slot_label} label`,
          what: `${pk.band} band, ${pk.households} households`,
        };
      }
      let sel: Overlay["sel"] = null;
      const ci = cursorRef.current;
      if (ci !== null) {
        const c = cellAt(terrain, ci);
        const v = (mode === "kwh" ? c.kwh : c.charge) ?? 0;
        const p = h.project(xOf(c.slot) + 0.5, (v / max) * HMAX, zOf(c.dateIndex) + 0.5);
        if (p.visible) sel = { x: p.x, y: p.y };
      }
      setOverlay({ months, slots, bar, peak, sel, size: { w: canvas.clientWidth || 800, h: canvas.clientHeight || 400 }, topDown: h.elevation > 80 });
    };
    computeRef.current = compute;
    h.onCamera(compute);
    const ro = new ResizeObserver(() => h.resize());
    ro.observe(canvas);
    return () => {
      ro.disconnect();
      h.dispose();
      handle.current = null;
    };
    // the scene is built once per terrain; everything else is applied through the handle
  }, [terrain]);

  useEffect(() => {
    handle.current?.setMode(mode, !reducedMotion);
    // the scale bar labels the new unit at once; the geometry follows
    handle.current?.resize();
  }, [mode, reducedMotion]);
  useEffect(() => handle.current?.setHighlight(highlight), [highlight]);
  useEffect(() => {
    handle.current?.setCursor(cursor);
    computeRef.current?.();
  }, [cursor]);
  useEffect(() => handle.current?.setHover(hover), [hover]);
  useEffect(() => handle.current?.setView(view, !reducedMotion), [view, viewRequest, reducedMotion]);
  useEffect(() => handle.current?.setZoom(zoom), [zoom]);

  const local = (e: PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const onPointerDown = (e: PointerEvent<HTMLCanvasElement>) => {
    const touch = e.pointerType === "touch";
    // a second finger belongs to the browser (pinch-zoom of the page), not to the terrain
    if (touch && drag.current) return;
    drag.current = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, moved: false, id: e.pointerId, touch, intent: touch ? "undecided" : "turn" };
    // a touch pointer is captured by the canvas already; a mouse needs asking
    if (!touch) e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    if (d && e.pointerId === d.id && (d.touch || e.buttons > 0)) {
      if (d.intent !== "turn") {
        // touch only: wait for a clear direction; a vertical drag is the page's scroll
        if (d.intent === "undecided") d.intent = touchIntent(e.clientX - d.x0, e.clientY - d.y0);
        if (d.intent !== "turn") return;
        // start turning from here, so the slop does not arrive as a jump
        d.x = e.clientX;
        d.y = e.clientY;
        d.moved = true;
        setDragging(true);
        return;
      }
      const dx = e.clientX - d.x;
      const dy = e.clientY - d.y;
      if (!d.moved && Math.hypot(dx, dy) < 4) return;
      d.moved = true;
      setDragging(true);
      setTurned(true);
      // a finger covers a narrower canvas than a mouse does, so it turns a little further per pixel
      const k = d.touch ? 0.45 : 0.35;
      handle.current?.orbit(-dx * k, dy * k);
      d.x = e.clientX;
      d.y = e.clientY;
      return;
    }
    if (d?.touch) return;
    const p = local(e);
    onHover(handle.current?.pick(p.x, p.y) ?? null);
  };
  const onPointerUp = (e: PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    if (d && e.pointerId !== d.id) return;
    drag.current = null;
    setDragging(false);
    if (d?.moved || d?.intent === "scroll") return;
    const p = local(e);
    const i = handle.current?.pick(p.x, p.y) ?? null;
    if (i !== null) onSelect(i);
  };
  const onKey = (e: KeyboardEvent<HTMLCanvasElement>) => {
    const g = terrain.grid;
    const from = cursor ?? indexOf(terrain, 0, 0);
    const moves: Record<string, [number, number]> = {
      ArrowRight: [1, 0],
      ArrowLeft: [-1, 0],
      ArrowUp: [0, 1],
      ArrowDown: [0, -1],
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
  const max = maxOf(terrain, mode);
  const range = mode === "kwh" ? `charged kWh from 0 to ${max} kWh` : `dynamic charge from £0 to £${max.toFixed(2)}`;
  return (
    <div className="terrain-3d" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        className={dragging ? "dragging" : ""}
        tabIndex={0}
        role="application"
        aria-roledescription="3D chart"
        aria-label={`Energy terrain: ${terrain.grid.dates} date labels by ${terrain.grid.slots} half-hour labels, height showing ${range} per half hour, colour showing the tariff band. Left and Right arrows move one date, Up and Down move one half hour, Page Up and Page Down move a week, Home and End reach the first and last half hour of the day; the readout below states the selected cell. Drag with a mouse, or drag sideways with a finger, to turn the view; an up-or-down drag scrolls the page. The buttons choose a preset view or zoom on the selected cell.`}
        aria-describedby="year-readout"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => {
          drag.current = null;
          setDragging(false);
        }}
        onPointerLeave={() => onHover(null)}
        onKeyDown={onKey}
        onFocus={() => {
          if (cursor === null) onCursor(indexOf(terrain, 0, 0));
        }}
      />
      {overlay && (
        <svg className="overlay" aria-hidden="true">
          {overlay.months.map((m) => (
            <text key={m.label} x={m.x} y={m.y + 12} textAnchor="middle">
              {m.label}
            </text>
          ))}
          {overlay.slots.map((s) => (
            <text key={s.label} x={s.x + 6} y={s.y + 4} textAnchor="start">
              {s.label}
            </text>
          ))}
          {overlay.peak &&
            (() => {
              const l = placeLabel(overlay.peak.x, overlay.peak.y, overlay.peak.detail, overlay.size.w, overlay.size.h, {
                preferRight: overlay.bar !== null && overlay.bar.x1 < overlay.size.w / 2,
                lines: overlay.topDown ? 1 : 3,
              });
              return (
                <g className="peak">
                  <line x1={overlay.peak.x} y1={overlay.peak.y} x2={l.lx} y2={l.ly} />
                  <text x={l.tx} y={l.ty} textAnchor={l.anchor} className="peak-value">
                    {overlay.peak.label}
                  </text>
                  {l.pinned && overlay.topDown ? null : l.pinned ? (
                    <>
                      <text x={l.tx} y={l.ty + 14} textAnchor={l.anchor}>
                        {overlay.peak.when}
                      </text>
                      <text x={l.tx} y={l.ty + 28} textAnchor={l.anchor}>
                        {overlay.peak.what}
                      </text>
                    </>
                  ) : (
                    <text x={l.tx} y={l.ty + 14} textAnchor={l.anchor}>
                      {overlay.peak.detail}
                    </text>
                  )}
                </g>
              );
            })()}
          {overlay.sel && (
            <g className="sel">
              <circle cx={overlay.sel.x} cy={overlay.sel.y} r={6} />
              <line x1={overlay.sel.x} y1={overlay.sel.y + 6} x2={overlay.sel.x} y2={overlay.sel.y + 20} />
              <text x={overlay.sel.x} y={overlay.sel.y + 32} textAnchor="middle">
                selected
              </text>
            </g>
          )}
          {overlay.bar && (
            <g>
              <line x1={overlay.bar.x0} y1={overlay.bar.y0} x2={overlay.bar.x1} y2={overlay.bar.y1} />
              {overlay.bar.ticks.map((t) => (
                <g key={t.label}>
                  <line x1={t.x - 5} y1={t.y} x2={t.x} y2={t.y} />
                  <text x={t.x - 8} y={t.y + 4} textAnchor="end">
                    {t.label}
                  </text>
                </g>
              ))}
              {overlay.bar.unit && (
                <text x={overlay.bar.x1} y={overlay.bar.y1 - 10} textAnchor={overlay.bar.x1 > overlay.size.w / 2 ? "end" : "start"} className="unit">
                  {mode === "kwh" ? "kWh" : "£"} per half hour, pooled
                </text>
              )}
            </g>
          )}
        </svg>
      )}
      <div className="views" role="group" aria-label="View and zoom">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            type="button"
            aria-pressed={view === v.key && !turned}
            onClick={() => {
              setView(v.key);
              setTurned(false);
              setViewRequest((n) => n + 1);
            }}
          >
            {v.label}
          </button>
        ))}
        {[1, 2, 4].map((z) => (
          <button key={z} type="button" aria-pressed={zoom === z} onClick={() => setZoom(z)} title={z === 1 ? "whole year" : `zoom ${z}× on the selected cell`}>
            {z}×
          </button>
        ))}
      </div>
    </div>
  );
}
