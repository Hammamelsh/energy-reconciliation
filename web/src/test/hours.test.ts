import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Bundle } from "../lib/bundle";
import { highConcentration, labelRange } from "../lib/hours";

const bundle = JSON.parse(readFileSync(join(process.cwd(), "public/data/bundle.json"), "utf8")) as Bundle;

describe("the High-band label-hour statement", () => {
  it("is derived from the schedule counts in the committed bundle", () => {
    const c = highConcentration(bundle.hour_bands);
    expect(c).not.toBeNull();
    expect(c!.from).toBe(17);
    expect(c!.to).toBe(22);
    expect(c!.contiguous).toBe(true);
    expect(c!.everyHour).toBe(true);
    expect(c!.slots).toBe(408);
    expect(c!.total).toBe(788);
    expect(c!.sharePct).toBe(51.8);
    expect(labelRange(c!)).toBe("17:00 to 22:59");
  });

  it("returns null when the schedule has no High band", () => {
    expect(highConcentration({ ...bundle.hour_bands, schedule_slots_by_band_and_hour: { High: [] } })).toBeNull();
  });
});
