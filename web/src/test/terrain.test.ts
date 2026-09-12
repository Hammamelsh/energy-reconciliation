import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Manifest } from "../lib/bundle";
import {
  cellAt,
  describeCell,
  heightNorm,
  indexOf,
  monthStarts,
  moveCursor,
  scaleTicks,
  verifyTerrain,
  type Terrain,
} from "../lib/terrain";
import { brightness, cellFromFraction, coverageRgb, paint, rgbOf } from "../components/terrain/flat";

const bytes = new Uint8Array(readFileSync(join(process.cwd(), "public/data/terrain.json")));
const manifest = JSON.parse(readFileSync(join(process.cwd(), "public/data/manifest.json"), "utf8")) as Manifest;
const bundle = JSON.parse(readFileSync(join(process.cwd(), "public/data/bundle.json"), "utf8"));

async function committed(): Promise<Terrain> {
  return verifyTerrain(manifest, bytes);
}

describe("terrain verification", () => {
  it("accepts the committed terrain and it reconciles with the committed bundle", async () => {
    const t = await committed();
    expect(t.definition).toBe("energy-terrain-1");
    expect(t.grid.cells).toBe(t.grid.dates * t.grid.slots);
    expect(t.totals.charge.exact).toBe(bundle.comparison.dynamic_charge.exact);
    expect(t.totals.kwh.exact).toBe(bundle.comparison.kwh.exact);
    expect(t.totals.charged_readings).toBe(bundle.comparison.charged_readings);
    expect(t.cells.readings.reduce((a, b) => a + b, 0)).toBe(bundle.comparison.charged_readings);
    expect(bundle.terrain.totals).toEqual(t.totals);
    expect(t.reconciliation.all_hold).toBe(true);
  });

  it("refuses a changed byte, a wrong size, a foreign definition, another run, a missing pin and malformed JSON", async () => {
    const changed = new Uint8Array(bytes);
    changed[20] ^= 0x01;
    await expect(verifyTerrain(manifest, changed)).rejects.toThrow(/does not match the manifest/);
    await expect(verifyTerrain(manifest, bytes.slice(0, -1))).rejects.toThrow(/pins/);
    const foreign = { ...manifest, terrain: { ...manifest.terrain!, definition: "energy-terrain-0" } };
    await expect(verifyTerrain(foreign, bytes)).rejects.toThrow(/definition/);
    const otherRun = { ...manifest, source: { ...manifest.source, run_id: "dbtcand-ffffffffffff@20200101T000000000000" } };
    await expect(verifyTerrain(otherRun, bytes)).rejects.toThrow(/different runs/);
    const unpinned = { ...manifest };
    delete unpinned.terrain;
    await expect(verifyTerrain(unpinned, bytes)).rejects.toThrow(/pins no terrain/);
    const junk = new TextEncoder().encode("{not json");
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", junk)), (b) => b.toString(16).padStart(2, "0")).join("");
    const pinnedJunk = { ...manifest, terrain: { ...manifest.terrain!, size_bytes: junk.byteLength, content_digest: digest } };
    await expect(verifyTerrain(pinnedJunk, junk)).rejects.toThrow(/not JSON/);
  });

  it("refuses a terrain whose arrays do not match its grid, even when correctly pinned", async () => {
    const t = await committed();
    const broken = { ...t, cells: { ...t.cells, kwh: t.cells.kwh.slice(1) } };
    const body = new TextEncoder().encode(JSON.stringify(broken));
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", body)), (b) => b.toString(16).padStart(2, "0")).join("");
    const pinned = { ...manifest, terrain: { ...manifest.terrain!, size_bytes: body.byteLength, content_digest: digest } };
    await expect(verifyTerrain(pinned, body)).rejects.toThrow(/do not match its grid/);
  });
});

describe("assumption metadata", () => {
  it("names A1 as the assumption its cells carry, leaves A2 with the comparison, and refuses an edited list", async () => {
    const terrain = await verifyTerrain(manifest, bytes);
    expect(terrain.assumption_ids).toEqual(["A1"]);
    expect(terrain.reconciliation.compared_with_assumption_ids).toContain("A2");
    expect(bundle.comparison.assumption_ids).toEqual(["A1", "A2"]);
    expect(bundle.terrain.reconciliation.compared_with_assumption_ids).toEqual(["A1", "A2"]);
    for (const edit of [
      (t: { assumption_ids: string[] }) => t.assumption_ids.push("A2"),
      (t: { assumption_ids?: string[] }) => delete t.assumption_ids,
      (t: { assumption_ids: string[] }) => (t.assumption_ids = ["A9"]),
    ]) {
      const edited = JSON.parse(new TextDecoder().decode(bytes));
      edit(edited);
      const reencoded = new TextEncoder().encode(JSON.stringify(edited));
      await expect(verifyTerrain(manifest, reencoded)).rejects.toThrow(/bytes|digest/);
    }
  });
});

describe("reading cells", () => {
  it("indexes date-major and clamps the cursor to the grid", async () => {
    const t = await committed();
    expect(indexOf(t, 0, 0)).toBe(0);
    expect(indexOf(t, 1, 0)).toBe(48);
    const c = cellAt(t, 48 * 75 + 39);
    expect(c.date).toBe(t.grid.date_labels[75]);
    expect(c.slotLabel).toBe("19:30");
    expect(moveCursor(t, 0, -1, -1)).toBe(0);
    expect(moveCursor(t, 0, 0, 47)).toBe(47);
    expect(moveCursor(t, 0, 0, 48)).toBe(47);
    expect(moveCursor(t, t.grid.cells - 1, 1, 1)).toBe(t.grid.cells - 1);
    expect(moveCursor(t, 0, 7, 0)).toBe(7 * 48);
  });

  it("finds the twelve month starts of 2013 at the right indices", async () => {
    const t = await committed();
    const m = monthStarts(t.grid.date_labels);
    expect(m.map((x) => x.label)).toEqual(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]);
    expect(m.map((x) => x.dateIndex)).toEqual([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]);
  });

  it("describes a cell with every value the visual encodes, and an empty cell as empty", async () => {
    const t = await committed();
    const peak = t.peaks.charge!;
    const i = indexOf(t, t.grid.date_labels.indexOf(peak.date), peak.slot);
    const text = describeCell(t, i);
    expect(text).toContain(`${peak.date}, ${peak.slot_label} label`);
    expect(text).toContain("kWh charged across");
    expect(text).toContain(`${peak.households} of 27 households`);
    expect(text).toContain("High band at 67.20p per kWh");
    expect(text).toContain("dynamic charge £7.43");
    const empty: Terrain = { ...t, cells: { ...t.cells, readings: t.cells.readings.map((v, k) => (k === 5 ? 0 : v)), kwh: t.cells.kwh.map((v, k) => (k === 5 ? null : v)), charge: t.cells.charge.map((v, k) => (k === 5 ? null : v)) } };
    expect(describeCell(empty, 5)).toMatch(/no charged reading .* Empty, not zero/);
  });

  it("uses zero-based scales and nice ticks", () => {
    expect(heightNorm(null, 10)).toBe(0);
    expect(heightNorm(5, 10)).toBe(0.5);
    expect(heightNorm(12, 10)).toBe(1);
    expect(scaleTicks(7.43)).toEqual([0, 2, 4, 6]);
    expect(scaleTicks(14.353)).toEqual([0, 5, 10]);
    expect(scaleTicks(0)).toEqual([0]);
  });
});

describe("the flat map's colour rules", () => {
  it("paints empty cells as the floor, keeps low values visible, dims bands outside the highlight", async () => {
    const t = await committed();
    const i = 0;
    expect(brightness(t, i, "kwh")).toBeGreaterThan(0.1);
    const lit = rgbOf(t, i, "kwh", "all");
    const dimmed = rgbOf(t, i, "kwh", t.cells.band[i] === "H" ? "Low" : "High");
    expect(dimmed[0] + dimmed[1] + dimmed[2]).toBeLessThan(lit[0] + lit[1] + lit[2]);
    const empty: Terrain = { ...t, cells: { ...t.cells, kwh: t.cells.kwh.map((v, k) => (k === i ? null : v)) } };
    expect(rgbOf(empty, i, "kwh", "all")).toEqual([15, 19, 27]);
    expect(brightness(empty, i, "kwh")).toBeNull();
    const cov = coverageRgb(t, i);
    expect(cov[0]).toBeGreaterThan(15);
    const out = new Uint8ClampedArray(t.grid.cells * 4);
    paint(t, "charge", "all", out);
    expect(out[3]).toBe(255);
    expect(out.length).toBe(t.grid.cells * 4);
  });

  it("maps a pointer fraction to a cell and nothing outside", async () => {
    const t = await committed();
    expect(cellFromFraction(t, 0, 0)).toBe(0);
    expect(cellFromFraction(t, 0.999, 0.999)).toBe(t.grid.cells - 1);
    expect(cellFromFraction(t, 0.5, 0)).toBe(24);
    expect(cellFromFraction(t, 1.0, 0.5)).toBeNull();
    expect(cellFromFraction(t, -0.01, 0.5)).toBeNull();
  });
});
