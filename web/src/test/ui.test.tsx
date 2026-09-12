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
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Same electricity use, priced two ways. A £484.83 difference.");
    const chart = screen.getByRole("group", { name: /Each household's difference/ });
    const bars = within(chart).getAllByRole("button");
    expect(bars).toHaveLength(27);
    expect(bars.filter((b) => b.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(bars.some((b) => /MAC000186.*higher under the dynamic tariff/.test(b.getAttribute("aria-label") ?? ""))).toBe(true);
  });

  it("opens with the answer, the two totals and one mark per household, all from the bundle", async () => {
    const bundle = await verifyBundle(manifest, bytes);
    const c = bundle.comparison;
    render(<Page loaded={{ bundle, manifest, digest: manifest.content_digest }} />);
    const opening = screen.getByRole("heading", { level: 1 }).closest("header")!;
    // the result in plain words, every figure from the bundle, and the qualification in the opening
    expect(opening.querySelector(".eyebrow")).toHaveTextContent("2013 Low Carbon London trial");
    expect(opening.querySelector(".lede")).toHaveTextContent(
      "We kept 456,096 readings from 27 households unchanged and calculated the total twice: once using the trial's published Low, Normal and High prices, and once using its flat price of 14.228p per kWh throughout. The readings and their timestamp labels stayed the same.",
    );
    expect(opening.querySelector(".answer-line")).toHaveTextContent(`Dynamic pricing came out ${c.pct_of_flat.display?.toFixed(1)}% lower overall.`);
    expect(opening.querySelector(".answer-sub")).toHaveTextContent(
      `${money(c.dynamic_charge.display)} compared with ${money(c.flat_charge.display)}. It came out lower for ${c.outcomes_under_dynamic.lower} households and higher for ${c.outcomes_under_dynamic.higher}.`,
    );
    expect(opening.querySelector(".qualifier")).toHaveTextContent("Historical comparison, not a current tariff recommendation or a complete bill.");
    // how the pricing worked: the explanation, the four prices and the closing statement, before the exact figures
    expect(within(opening).getByRole("heading", { name: "How the pricing worked" })).toBeInTheDocument();
    const prices = within(opening).getByRole("list", { name: "The four prices, in pence per kWh" });
    expect(within(prices).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Low3.99p per kWh",
      "Normal11.76p per kWh",
      "High67.20p per kWh",
      "Flat comparison14.228p per kWh",
    ]);
    expect(prices.closest(".ladder")).toHaveTextContent(
      "Each meter reading covers one half-hour. The published schedule labelled its timestamp Low, Normal or High. Different half-hours could receive different prices, but the price did not necessarily change after every half-hour.",
    );
    expect(prices.closest(".ladder")).toHaveTextContent("Low and Normal were below the flat price. High was far above it. The final result depended on when each household's electricity was recorded.");
    expect(prices.closest(".ladder")!.compareDocumentPosition(opening.querySelector("details.exact")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(opening.textContent).not.toMatch(/—|–|every 30 minutes|savings|paid/);
    expect(
      within(opening).getByRole("img", { name: `Dynamic tariff ${money(c.dynamic_charge.display)} against flat price ${money(c.flat_charge.display)} for the same recorded electricity.` }),
    ).toBeInTheDocument();
    const marks = within(opening).getByRole("group", { name: /27 households: 25 lower/ });
    const buttons = within(marks).getAllByRole("button");
    expect(buttons).toHaveLength(27);
    expect(buttons.filter((b) => b.className.includes("lower"))).toHaveLength(25);
    expect(buttons.filter((b) => b.className.includes("higher"))).toHaveLength(2);
    expect(buttons.filter((b) => b.getAttribute("tabindex") === "0")).toHaveLength(1);
    // the last mark is an exception; choosing it selects that household on the page
    await userEvent.click(buttons[26]);
    expect(buttons[26]).toHaveAttribute("aria-pressed", "true");
    expect(window.location.search).toMatch(/household=MAC000186/);
    await userEvent.click(within(opening).getByRole("button", { name: /Why did 2 come out higher/ }));
    expect(await screen.findByText("MAC000186", { selector: ".detail .id" })).toBeInTheDocument();
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

  it("refuses a tampered bundle and shows the integrity-check error state", async () => {
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
    expect(await screen.findByRole("alert")).toHaveTextContent(/did not match its pinned digest/);
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
