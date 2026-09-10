import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { BundleError, DEFINITION, sha256Hex, verifyBundle, type Manifest } from "../lib/bundle";

const bytes = new Uint8Array(readFileSync(join(process.cwd(), "public/data/bundle.json")));
const manifest = JSON.parse(readFileSync(join(process.cwd(), "public/data/manifest.json"), "utf8")) as Manifest;

describe("the committed bundle", () => {
  it("verifies against its manifest and carries the headline figures", async () => {
    const bundle = await verifyBundle(manifest, bytes);
    expect(bundle.definition).toBe(DEFINITION);
    const c = bundle.comparison;
    expect(c.households).toBe(27);
    expect(c.per_household).toHaveLength(27);
    expect(c.outcomes_under_dynamic).toEqual({ lower: 25, higher: 2, equal: 0 });
    expect(c.charged_readings).toBe(456096);
    expect(c.dynamic_charge.exact).toBe("11675.4339216532500000");
    expect(c.flat_charge.exact).toBe("12160.2636827847040000");
    expect(c.flat_minus_dynamic.exact).toBe("484.8297611314540000");
    expect(c.flat_minus_dynamic.display).toBe(484.83);
    expect(c.pct_of_flat.display).toBe(4.0);
    expect(c.pct_of_flat.denominator).toBe("flat_charge");
  });

  it("holds exact values as strings with units and display values as numbers", async () => {
    const bundle = await verifyBundle(manifest, bytes);
    for (const h of bundle.comparison.per_household) {
      expect(typeof h.dynamic_charge.exact).toBe("string");
      expect(h.dynamic_charge.unit).toBe("GBP");
      expect(typeof h.dynamic_charge.display).toBe("number");
      expect(h.kwh.unit).toBe("kWh");
      expect(h.first_charged_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it("refuses a changed byte", async () => {
    const tampered = new Uint8Array(bytes);
    tampered[tampered.length - 2] ^= 0x01;
    await expect(verifyBundle(manifest, tampered)).rejects.toBeInstanceOf(BundleError);
  });

  it("refuses a truncated file by size before hashing", async () => {
    await expect(verifyBundle(manifest, bytes.slice(0, 100))).rejects.toThrow(/bytes/);
  });

  it("refuses a manifest with another definition or run", async () => {
    await expect(verifyBundle({ ...manifest, definition: "presentation-bundle-0" }, bytes)).rejects.toThrow(/definition/);
    await expect(
      verifyBundle({ ...manifest, source: { ...manifest.source, run_id: "other" } }, bytes),
    ).rejects.toThrow(/different runs/);
  });

  it("hashes bytes the same way the manifest was written", async () => {
    expect(await sha256Hex(bytes)).toBe(manifest.content_digest);
  });
});
