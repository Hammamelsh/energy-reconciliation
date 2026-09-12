import { describe, expect, it, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Page } from "../App";
import { verifyBundle, type Manifest } from "../lib/bundle";
import { placeLabel } from "../components/terrain/label";
import { touchIntent, TOUCH_SLOP } from "../components/terrain/gesture";

const bytes = new Uint8Array(readFileSync(join(process.cwd(), "public/data/bundle.json")));
const manifest = JSON.parse(readFileSync(join(process.cwd(), "public/data/manifest.json"), "utf8")) as Manifest;

describe("the phone header", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("offers the same seven sections as a menu that closes after a choice", async () => {
    const bundle = await verifyBundle(manifest, bytes);
    render(<Page loaded={{ bundle, manifest, digest: manifest.content_digest }} />);
    const wide = screen.getByRole("navigation", { name: "Sections" });
    const menu = screen.getByRole("navigation", { name: "Sections menu" });
    const wideLinks = within(wide).getAllByRole("link").map((a) => [a.getAttribute("href"), a.textContent]);
    const menuLinks = within(menu).getAllByRole("link").map((a) => [a.getAttribute("href"), a.textContent]);
    expect(menuLinks).toEqual(wideLinks);
    expect(menuLinks).toHaveLength(7);
    expect(menuLinks[0]).toEqual(["#households", "Households"]);

    const details = menu.closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    const user = userEvent.setup();
    await user.click(screen.getByText("Sections", { selector: "summary" }));
    expect(details.open).toBe(true);
    await user.click(within(menu).getByRole("link", { name: "One year" }));
    expect(details.open).toBe(false);

    await user.click(screen.getByText("Sections", { selector: "summary" }));
    expect(details.open).toBe(true);
    await user.keyboard("{Escape}");
    expect(details.open).toBe(false);
  });
});

describe("the 3D peak annotation", () => {
  const detail = "2013-03-17, 19:30 label, High band, 26 households";
  it("goes to the right of the peak when there is room", () => {
    const l = placeLabel(100, 200, detail, 1100, 500);
    expect(l.anchor).toBe("start");
    expect(l.tx).toBe(130);
  });
  it("flips to the left near the right edge", () => {
    const l = placeLabel(1000, 200, detail, 1100, 500);
    expect(l.anchor).toBe("end");
    expect(l.tx).toBe(970);
    expect(l.tx - (detail.length * 6.6 + 12)).toBeGreaterThanOrEqual(4);
  });
  it("stays inside a phone-width canvas where neither side has room", () => {
    const l = placeLabel(200, 260, detail, 324, 466);
    expect(l.anchor).toBe("start");
    expect(l.tx).toBeGreaterThanOrEqual(4);
    expect(l.ty).toBeGreaterThanOrEqual(18);
    expect(l.ty).toBeLessThanOrEqual(466 - 22);
    expect(l.lx).toBeGreaterThan(l.tx);
    expect(l.lx).toBeLessThan(324);
    expect(l.pinned).toBe(true);
    expect(l.ty + 28).toBeLessThan(466);
  });
  it("is not pinned where a side fits", () => {
    expect(placeLabel(100, 200, detail, 1100, 500).pinned).toBe(false);
  });
  it("pins to the corner away from the scale bar, and meets a one-line block just below it", () => {
    const right = placeLabel(200, 260, detail, 324, 466, { preferRight: true, lines: 3 });
    expect(right.anchor).toBe("end");
    expect(right.tx).toBe(316);
    expect(right.lx).toBeLessThan(right.tx);
    expect(right.ly).toBe(52);
    const one = placeLabel(200, 260, detail, 324, 466, { lines: 1 });
    expect(one.ly).toBe(22);
  });
});

describe("a finger on the 3D view", () => {
  it("waits for a clear movement, so a tap still selects", () => {
    expect(touchIntent(0, 0)).toBe("undecided");
    expect(touchIntent(5, -5)).toBe("undecided");
    expect(Math.hypot(5, -5)).toBeLessThan(TOUCH_SLOP);
  });
  it("turns the terrain on a mainly sideways drag, in either direction", () => {
    expect(touchIntent(12, 3)).toBe("turn");
    expect(touchIntent(-30, 10)).toBe("turn");
  });
  it("leaves a mainly vertical drag to the page's scroll", () => {
    expect(touchIntent(2, 14)).toBe("scroll");
    expect(touchIntent(-9, -40)).toBe("scroll");
    expect(touchIntent(10, 10)).toBe("scroll");
  });
});
