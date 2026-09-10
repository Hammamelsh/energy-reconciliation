import { describe, expect, it, vi, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App, { Page } from "../App";
import { verifyBundle, type Manifest } from "../lib/bundle";
import { countAt } from "../lib/breakeven";
import { integer, money, signedMoney, signedPct } from "../lib/format";
import { readState, writeState } from "../lib/url";

const bytes = new Uint8Array(readFileSync(join(process.cwd(), "public/data/bundle.json")));
const manifest = JSON.parse(readFileSync(join(process.cwd(), "public/data/manifest.json"), "utf8")) as Manifest;

describe("formatting never recomputes", () => {
  it("formats display values only", () => {
    expect(money(484.83)).toBe("£484.83");
    expect(signedMoney(484.83)).toBe("+£484.83");
    expect(signedMoney(-2.37)).toBe("−£2.37");
    expect(signedPct(4.0)).toBe("+4.0%");
    expect(signedPct(null)).toBe("undefined");
    expect(integer(456096)).toBe("456,096");
  });
});

describe("shareable url state", () => {
  it("reads and writes household and flat price", () => {
    expect(readState("?household=MAC000186&flat=13.5")).toEqual({ household: "MAC000186", flat: 13.5 });
    expect(readState("?household=<script>")).toEqual({ household: null, flat: null });
    expect(readState("?flat=abc")).toEqual({ household: null, flat: null });
    expect(writeState({ household: "MAC000193", flat: null }, "")).toBe("?household=MAC000193");
    expect(writeState({ household: null, flat: 13.66 }, "?household=x")).toBe("?flat=13.660");
  });
});

describe("break-even counts compare, they do not calculate", () => {
  it("counts households below and above a candidate price", async () => {
    const bundle = await verifyBundle(manifest, bytes);
    const hh = bundle.comparison.per_household;
    const flat = Number(bundle.comparison.flat_price.pence_per_kwh);
    expect(countAt(hh, flat)).toEqual(bundle.comparison.outcomes_under_dynamic);
    expect(countAt(hh, 0).lower).toBe(0);
    expect(countAt(hh, 100).lower).toBe(hh.length);
  });
});

describe("the page", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("renders the hero figures and every household as a keyboard-reachable button", async () => {
    const bundle = await verifyBundle(manifest, bytes);
    render(<Page loaded={{ bundle, manifest, digest: manifest.content_digest }} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("The same electricity, priced two ways.");
    const chart = screen.getByRole("group", { name: /Each household's difference/ });
    const bars = within(chart).getAllByRole("button");
    expect(bars).toHaveLength(27);
    expect(bars.filter((b) => b.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(bars.some((b) => /MAC000186.*higher under the dynamic tariff/.test(b.getAttribute("aria-label") ?? ""))).toBe(true);
  });

  it("selects a household from the url and moves the selection with the keyboard", async () => {
    window.history.replaceState(null, "", "/?household=MAC000186");
    const bundle = await verifyBundle(manifest, bytes);
    render(<Page loaded={{ bundle, manifest, digest: manifest.content_digest }} />);
    const detail = await screen.findByText("MAC000186", { selector: ".detail .id" });
    expect(detail).toBeInTheDocument();
    const chart = screen.getByRole("group", { name: /Each household's difference/ });
    const current = within(chart).getByRole("button", { pressed: true });
    current.focus();
    await userEvent.keyboard("{ArrowDown}");
    await waitFor(() => expect(within(chart).getByRole("button", { pressed: true })).not.toBe(current));
    expect(window.location.search).toMatch(/household=MAC/);
  });

  it("shows a verified error state when the data cannot be trusted", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("manifest.json")) return new Response(JSON.stringify(manifest));
        const bad = new Uint8Array(bytes);
        bad[10] ^= 0x01;
        return new Response(bad);
      }),
    );
    render(<App base="data/" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be verified/);
    vi.unstubAllGlobals();
  });

  it("renders the verified page from fetched data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("manifest.json") ? new Response(JSON.stringify(manifest)) : new Response(bytes),
      ),
    );
    render(<App base="data/" />);
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/sha256 matched/)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
