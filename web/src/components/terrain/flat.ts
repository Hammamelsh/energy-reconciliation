/**
 * The flat (top-down) carpet: one pixel per cell, X = half-hour label, Y = date label,
 * band as hue, value as brightness on a zero-based scale. Pure functions over the terrain
 * so the colour rules are testable without a canvas.
 */
import { bandAt, heightNorm, maxOf, valueOf, type CellBand, type Mode, type Terrain } from "../../lib/terrain";

export const BAND_RGB: Record<CellBand, [number, number, number]> = {
  Low: [76, 139, 245], // current blue
  Normal: [143, 160, 190], // slate: not the lime of "dynamic lower"
  High: [255, 138, 61], // ember
  none: [0, 0, 0],
};
export const BAND_HEX: Record<CellBand, string> = {
  Low: "#4c8bf5",
  Normal: "#8fa0be",
  High: "#ff8a3d",
  none: "#0f131b",
};
const BASE: [number, number, number] = [15, 19, 27]; // --bg-2: the floor of the scale
const FLOOR = 0.14; // the dimmest a cell with a value can be, so a low cell stays visible
const DIMMED = 0.3; // brightness of bands outside the highlight

export type Highlight = "all" | CellBand;

/** Brightness 0..1 for a cell in a mode: zero-based, never rescaled per date or band. */
export function brightness(t: Terrain, index: number, mode: Mode): number | null {
  const v = valueOf(t, index, mode);
  if (v === null) return null;
  return FLOOR + (1 - FLOOR) * heightNorm(v, maxOf(t, mode));
}

export function rgbOf(t: Terrain, index: number, mode: Mode, highlight: Highlight): [number, number, number] {
  const band = bandAt(t, index);
  const b = brightness(t, index, mode);
  if (b === null) return BASE; // empty: the floor colour, nothing drawn on it
  const dim = highlight !== "all" && highlight !== band ? DIMMED : 1;
  const [r, g, bl] = BAND_RGB[band];
  return [
    Math.round(BASE[0] + (r - BASE[0]) * b * dim),
    Math.round(BASE[1] + (g - BASE[1]) * b * dim),
    Math.round(BASE[2] + (bl - BASE[2]) * b * dim),
  ];
}

/** Coverage carpet: households per cell, grey, from the minimum to the maximum present. */
export function coverageRgb(t: Terrain, index: number): [number, number, number] {
  const n = t.cells.households[index];
  if (n === 0) return BASE;
  const lo = t.coverage.households_per_cell_min;
  const hi = t.coverage.households_per_cell_max;
  const f = hi > lo ? (n - lo) / (hi - lo) : 1;
  const v = 0.25 + 0.75 * f;
  return [Math.round(BASE[0] + (238 - BASE[0]) * v), Math.round(BASE[1] + (242 - BASE[1]) * v), Math.round(BASE[2] + (247 - BASE[2]) * v)];
}

export type Carpet = "kwh" | "charge" | "coverage";

/** Fill an RGBA buffer, width = slots, height = dates, one pixel per cell. */
export function paint(t: Terrain, carpet: Carpet, highlight: Highlight, out: Uint8ClampedArray): void {
  const n = t.grid.cells;
  for (let i = 0; i < n; i++) {
    const [r, g, b] = carpet === "coverage" ? coverageRgb(t, i) : rgbOf(t, i, carpet, highlight);
    const o = i * 4;
    out[o] = r;
    out[o + 1] = g;
    out[o + 2] = b;
    out[o + 3] = 255;
  }
}

/** The cell under a pointer, from its position inside the carpet as fractions 0..1. */
export function cellFromFraction(t: Terrain, fx: number, fy: number): number | null {
  if (fx < 0 || fx >= 1 || fy < 0 || fy >= 1) return null;
  const slot = Math.min(t.grid.slots - 1, Math.floor(fx * t.grid.slots));
  const dateIndex = Math.min(t.grid.dates - 1, Math.floor(fy * t.grid.dates));
  return dateIndex * t.grid.slots + slot;
}
