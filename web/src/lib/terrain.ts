/**
 * The terrain file (`energy-terrain-1`): types, verification against the manifest, and
 * pure helpers for reading cells.
 *
 * Cells carry display values rounded once in Python (kWh to 3 dp, charge to 2 dp). The
 * browser converts them to numbers for heights and colours only; it never adds them, and
 * every total it shows is an exact string from the export.
 */
import { BundleError, sha256Hex, type Energy, type Manifest, type Money } from "./bundle";
import { energy, integer, money } from "./format";

export const TERRAIN_DEFINITION = "energy-terrain-1";

export type BandName = "Low" | "Normal" | "High";
export type CellBand = BandName | "none";

export type TerrainPeak = {
  date: string;
  slot: number;
  slot_label: string;
  band: BandName;
  kwh: Energy;
  charge: Money;
  charged_readings: number;
  households: number;
};

export type TerrainBand = {
  band: BandName;
  price_pence_per_kwh: string | null;
  cells: number;
  cells_with_readings: number;
  charged_readings: number;
  kwh: Energy;
  charge: Money;
};

export type TerrainMonth = {
  month: string;
  index: number;
  cells: number;
  cells_with_readings: number;
  charged_readings: number;
  households_min: number;
  households_max: number;
  kwh: Energy;
  charge: Money;
  bands: Record<BandName, { cells: number; charged_readings: number; kwh: Energy; charge: Money }>;
};

export type Terrain = {
  definition: string;
  title: string;
  source: {
    run_id: string;
    version: string | null;
    file_sha256: string;
    tariff_group: string;
    schedule_source: string | null;
    comparison_definition: string;
  };
  assumption_ids: string[];
  grid: {
    dates: number;
    slots: number;
    cells: number;
    order: string;
    first_date: string;
    last_date: string;
    date_labels: string[];
    slot_labels: string[];
    label_meaning: string;
    schedule_labels_off_grid: number;
  };
  cells: {
    band: string;
    band_codes: Record<string, BandName>;
    readings: number[];
    households: number[];
    kwh: (number | null)[];
    charge: (number | null)[];
  };
  cell_values: {
    kwh: { unit: "kWh"; decimals: number };
    charge: { unit: "GBP"; decimals: number };
    rounding: string;
    null_means: string;
    not_additive: string;
  };
  scale: {
    kwh: { min: number; max: number; unit: "kWh" };
    charge: { min: number; max: number; unit: "GBP" };
    zero_based: boolean;
  };
  coverage: {
    households_in_comparison: number;
    cells_with_readings: number;
    cells_without_readings: number;
    households_per_cell_min: number;
    households_per_cell_max: number;
    readings_per_cell_min: number;
    readings_per_cell_max: number;
  };
  totals: { charged_readings: number; households: number; kwh: Energy; charge: Money };
  by_band: TerrainBand[];
  by_month: TerrainMonth[];
  peaks: { kwh: TerrainPeak | null; charge: TerrainPeak | null };
  reconciliation: { compared_with: string; checks: Record<string, boolean>; all_hold: boolean };
  caveats: string[];
};

/** The bundle's summary of the terrain: enough to introduce the section before the file loads. */
export type TerrainSummary = {
  definition: string;
  file: string;
  title: string;
  grid: { dates: number; slots: number; cells: number; first_date: string; last_date: string };
  coverage: Terrain["coverage"];
  totals: Terrain["totals"];
  scale: Terrain["scale"];
  peaks: Terrain["peaks"];
  reconciliation: Terrain["reconciliation"];
};

export type Mode = "kwh" | "charge";

/** Verify the terrain's bytes against the manifest's pin before reading a single cell. */
export async function verifyTerrain(manifest: Manifest, bytes: Uint8Array): Promise<Terrain> {
  const pin = manifest.terrain;
  if (!pin) throw new BundleError("the manifest pins no terrain file");
  if (pin.definition !== TERRAIN_DEFINITION) {
    throw new BundleError(`terrain definition ${pin.definition} is not ${TERRAIN_DEFINITION}`);
  }
  if (bytes.byteLength !== pin.size_bytes) {
    throw new BundleError(`terrain is ${bytes.byteLength} bytes; the manifest pins ${pin.size_bytes}`);
  }
  const digest = await sha256Hex(bytes);
  if (digest !== pin.content_digest) {
    throw new BundleError(
      `terrain digest ${digest.slice(0, 12)}… does not match the manifest's ${pin.content_digest.slice(0, 12)}…`,
    );
  }
  let parsed: Terrain;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes)) as Terrain;
  } catch {
    throw new BundleError("the terrain file is not JSON");
  }
  if (parsed.definition !== TERRAIN_DEFINITION) throw new BundleError("terrain definition does not match");
  if (parsed.source.run_id !== manifest.source.run_id) {
    throw new BundleError("the terrain and its manifest name different runs");
  }
  if (!parsed.reconciliation?.all_hold) throw new BundleError("the terrain does not record a reconciliation that holds");
  const n = parsed.grid.cells;
  const c = parsed.cells;
  if (
    n !== parsed.grid.dates * parsed.grid.slots ||
    c.band.length !== n ||
    c.readings.length !== n ||
    c.households.length !== n ||
    c.kwh.length !== n ||
    c.charge.length !== n ||
    parsed.grid.date_labels.length !== parsed.grid.dates ||
    parsed.grid.slot_labels.length !== parsed.grid.slots
  ) {
    throw new BundleError("the terrain's cell arrays do not match its grid");
  }
  return parsed;
}

export async function loadTerrain(manifest: Manifest, base = "data/"): Promise<Terrain> {
  if (!manifest.terrain) throw new BundleError("the manifest pins no terrain file");
  const response = await fetch(`${base}${manifest.terrain.file}`, { cache: "no-cache" });
  if (!response.ok) throw new BundleError(`terrain: HTTP ${response.status}`);
  return verifyTerrain(manifest, new Uint8Array(await response.arrayBuffer()));
}

// ------------------------------------------------------------------ reading cells

export type Cell = {
  index: number;
  dateIndex: number;
  slot: number;
  date: string;
  slotLabel: string;
  band: CellBand;
  readings: number;
  households: number;
  kwh: number | null;
  charge: number | null;
};

export function bandAt(t: Terrain, index: number): CellBand {
  const code = t.cells.band[index];
  return code === "-" ? "none" : (t.cells.band_codes[code] ?? "none");
}

export function cellAt(t: Terrain, index: number): Cell {
  const slots = t.grid.slots;
  const dateIndex = Math.floor(index / slots);
  const slot = index - dateIndex * slots;
  return {
    index,
    dateIndex,
    slot,
    date: t.grid.date_labels[dateIndex],
    slotLabel: t.grid.slot_labels[slot],
    band: bandAt(t, index),
    readings: t.cells.readings[index],
    households: t.cells.households[index],
    kwh: t.cells.kwh[index],
    charge: t.cells.charge[index],
  };
}

export function indexOf(t: Terrain, dateIndex: number, slot: number): number {
  return dateIndex * t.grid.slots + slot;
}

/** Move a cell cursor by whole cells, clamped to the grid. */
export function moveCursor(t: Terrain, index: number, dDate: number, dSlot: number): number {
  const c = cellAt(t, index);
  const dateIndex = Math.max(0, Math.min(t.grid.dates - 1, c.dateIndex + dDate));
  const slot = Math.max(0, Math.min(t.grid.slots - 1, c.slot + dSlot));
  return indexOf(t, dateIndex, slot);
}

export function priceOf(t: Terrain, band: CellBand): string | null {
  return t.by_band.find((b) => b.band === band)?.price_pence_per_kwh ?? null;
}

/** The readout sentence for one cell: everything the visual encodes, as text. */
export function describeCell(t: Terrain, index: number): string {
  const c = cellAt(t, index);
  const label = `${c.date}, ${c.slotLabel} label`;
  if (c.readings === 0) {
    return `${label}: no charged reading in this half hour${c.band !== "none" ? ` (${c.band} band in the schedule)` : ""}. Empty, not zero.`;
  }
  const price = priceOf(t, c.band);
  const bandText = c.band === "none" ? "no band" : `${c.band} band${price ? ` at ${Number(price).toFixed(2)}p per kWh` : ""}`;
  return (
    `${label}: ${energy(c.kwh ?? 0)} charged across ${integer(c.households)} of ${integer(t.totals.households)} households, ` +
    `${bandText}, dynamic charge ${money(c.charge ?? 0)}.`
  );
}

/** First cell index of every month, with its label: ticks along the date axis. */
export function monthStarts(dateLabels: string[]): { dateIndex: number; label: string; month: string }[] {
  const out: { dateIndex: number; label: string; month: string }[] = [];
  let last = "";
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  dateLabels.forEach((d, i) => {
    const month = d.slice(0, 7);
    if (month !== last) {
      const m = Number(d.slice(5, 7));
      out.push({ dateIndex: i, month, label: names[m - 1] ?? month });
      last = month;
    }
  });
  return out;
}

/** 0..1 for a visual coordinate: value over the mode's zero-based maximum. Visual only. */
export function heightNorm(value: number | null, max: number): number {
  if (value === null || max <= 0) return 0;
  return Math.max(0, Math.min(1, value / max));
}

export function valueOf(t: Terrain, index: number, mode: Mode): number | null {
  return mode === "kwh" ? t.cells.kwh[index] : t.cells.charge[index];
}

export function maxOf(t: Terrain, mode: Mode): number {
  return mode === "kwh" ? t.scale.kwh.max : t.scale.charge.max;
}

export function unitOf(mode: Mode): string {
  return mode === "kwh" ? "kWh" : "£";
}

/** Nice zero-based axis ticks for a scale bar: 0 to max in 4 or 5 steps. */
export function scaleTicks(max: number): number[] {
  if (max <= 0) return [0];
  const raw = max / 4;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = 0; v <= max + 1e-9; v += step) ticks.push(Number(v.toFixed(6)));
  return ticks;
}
