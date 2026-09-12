import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Page } from "../App";
import { verifyBundle, type Manifest } from "../lib/bundle";

const bytes = new Uint8Array(readFileSync(join(process.cwd(), "public/data/bundle.json")));
const terrainBytes = new Uint8Array(readFileSync(join(process.cwd(), "public/data/terrain.json")));
const manifest = JSON.parse(readFileSync(join(process.cwd(), "public/data/manifest.json"), "utf8")) as Manifest;

function stubFetch(terrain: Uint8Array | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("terrain.json")) return terrain ? new Response(terrain as unknown as BodyInit) : new Response("", { status: 404 });
      if (url.endsWith("manifest.json")) return new Response(JSON.stringify(manifest));
      return new Response(bytes);
    }),
  );
}

function mediaMatching(...queries: string[]) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: queries.some((q) => query.includes(q)),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

async function renderPage() {
  const bundle = await verifyBundle(manifest, bytes);
  render(<Page loaded={{ bundle, manifest, digest: manifest.content_digest }} />);
  return bundle;
}

describe("the year section", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    mediaMatching();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("introduces the terrain from the verified bundle and, without WebGL, shows the flat map with every cell readable by keyboard", async () => {
    stubFetch(terrainBytes);
    const bundle = await renderPage();
    expect(screen.getByRole("heading", { name: "When did the calculated energy charge peak?" })).toBeInTheDocument();
    // the answer is the export's charge peak, stated as a timestamp label; the maps are under A1 alone
    const sub = document.querySelector("#year .sub")!;
    expect(sub).toHaveTextContent("The highest single timestamp label was 17 March at 19:30: £7.43 across 26 of the 27 households.");
    expect(sub).toHaveTextContent("under assumption A1, not a bill");
    expect(sub.textContent).not.toMatch(/A2/);
    const map = await screen.findByRole("application", { name: /Flat map of 365 date labels by 48 half-hour labels/ }, { timeout: 8000 });
    // the takeaway names both denominators; the coverage range stays visible; totals move into the disclosure
    expect(screen.getByRole("img", { name: "High-price half-hours: 4.9% of included electricity, 24.1% of calculated energy charge." })).toBeInTheDocument();
    const lead = document.querySelector(".year-lead")!;
    expect(lead).toHaveTextContent(`${bundle.terrain.coverage.households_per_cell_min} to ${bundle.terrain.coverage.households_per_cell_max} of the ${bundle.terrain.totals.households} households`);
    expect(lead.textContent).not.toMatch(/exactly/);
    const how = screen.getByText("How to read this map").closest("details")!;
    expect(how).toHaveTextContent("Assumption A2, the documented flat price, belongs only to the dynamic-versus-flat comparison");
    expect(how).toHaveTextContent(`${bundle.terrain.totals.kwh.display.toLocaleString("en-GB", { minimumFractionDigits: 3 })} kWh`);
    expect(how).toHaveTextContent("differ from the lime and ember");
    expect(screen.getByText("Brightness shows amount. Colour shows tariff band.")).toBeInTheDocument();
    // the readout opens on the tallest cell of the charge view, from the file's own peaks
    const readout = document.getElementById("year-readout")!;
    await waitFor(() => expect(readout).toHaveTextContent(/Tallest half hour in this view: 2013-03-17, 19:30 label/));
    expect(readout).toHaveTextContent(/dynamic charge £7\.43/);
    // the flat map is the default view everywhere; 3D is loaded only on request
    const views = screen.getByRole("group", { name: "View" });
    const flat = within(views).getByRole("button", { name: "Flat map" });
    expect(flat).toHaveAttribute("aria-pressed", "true");
    // the flat map marks the tallest cell of each carpet before any interaction
    expect(screen.getAllByText(/£7\.43|14\.353 kWh/, { selector: ".peak-marker span" })).toHaveLength(2);
    // keyboard: focus lands on the first cell, the arrow keys move the cursor
    map.focus();
    await waitFor(() => expect(readout).toHaveTextContent(/2013-01-01, 00:00 label/));
    await userEvent.keyboard("{ArrowRight}");
    expect(readout).toHaveTextContent(/2013-01-01, 00:30 label/);
    await userEvent.keyboard("{PageDown}");
    expect(readout).toHaveTextContent(/2013-01-08, 00:30 label/);
    await userEvent.keyboard("{End}");
    expect(readout).toHaveTextContent(/2013-01-08, 23:30 label/);
    await userEvent.keyboard("{Shift>}{End}{/Shift}");
    expect(readout).toHaveTextContent(/2013-12-31, 23:30 label/);
    // every band is distinguishable by the highlight control, not only by colour
    const high = within(screen.getByRole("group", { name: "Highlight one band" })).getByRole("button", { name: "High" });
    await userEvent.click(high);
    expect(high).toHaveAttribute("aria-pressed", "true");
    // the textual equivalent: twelve months and the exact year totals
    const summary = screen.getByText("The same cells as a table: month by band");
    await userEvent.click(summary);
    expect(within(summary.closest("details")!).getAllByRole("row")).toHaveLength(1 + 12 + 1); // header, months, year
    expect(screen.getByText(/Full-precision year totals from the export: 85467\.1329968000 kWh and £11675\.4339216532500000/)).toBeInTheDocument();
  });

  it("asks for WebGL only on request and reports when it is unavailable", async () => {
    stubFetch(terrainBytes);
    await renderPage();
    await screen.findByRole("application", { name: /Flat map/ }, { timeout: 8000 });
    const views = screen.getByRole("group", { name: "View" });
    await userEvent.click(within(views).getByRole("button", { name: "Explore in 3D" }));
    // the 3D chunk (Three.js) is imported on demand; give the import time to resolve
    expect(await screen.findByText(/The 3D view is not available here: this browser provides no WebGL context/, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByRole("application", { name: /Flat map/ })).toBeInTheDocument();
    expect(within(views).getByRole("button", { name: "Explore in 3D" })).toBeDisabled();
  });

  it("refuses a tampered terrain file and draws nothing in its place", async () => {
    const bad = new Uint8Array(terrainBytes);
    bad[40] ^= 0x01;
    stubFetch(bad);
    await renderPage();
    const alert = await screen.findByRole("alert", {}, { timeout: 8000 });
    expect(alert).toHaveTextContent(/terrain data did not match its pinned digest/);
    expect(alert).toHaveTextContent(/Nothing is drawn in its place/);
    expect(screen.queryByRole("application", { name: /Flat map/ })).not.toBeInTheDocument();
  });

  it("reports a missing terrain file as an explicit absence", async () => {
    stubFetch(null);
    await renderPage();
    expect(await screen.findByRole("alert", {}, { timeout: 8000 })).toHaveTextContent(/HTTP 404/);
  });

  it("on a narrow screen shows one map at a time and keeps the selected cell when switching", async () => {
    mediaMatching("max-width: 700px");
    stubFetch(terrainBytes);
    await renderPage();
    const map = await screen.findByRole("application", { name: /Flat map/ }, { timeout: 8000 });
    // one map, the charge map by default, with its own unit and scale stated
    expect(document.querySelectorAll(".carpet")).toHaveLength(1);
    expect(screen.getByText("Calculated energy charge, £")).toBeInTheDocument();
    expect(screen.getByText(/£0 to £7\.43 per half hour, pooled/)).toBeInTheDocument();
    map.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowDown}");
    const readout = document.getElementById("year-readout")!;
    expect(readout).toHaveTextContent(/2013-01-02, 00:30 label/);
    const show = screen.getByRole("group", { name: "Which map to show" });
    await userEvent.click(within(show).getByRole("button", { name: "Electricity, kWh" }));
    expect(document.querySelectorAll(".carpet")).toHaveLength(1);
    expect(screen.getByText("Included electricity, kWh")).toBeInTheDocument();
    expect(screen.getByText(/0 to 14\.353 kWh per half hour, pooled/)).toBeInTheDocument();
    // the cell selected on the charge map is still the cell on the electricity map
    expect(readout).toHaveTextContent(/2013-01-02, 00:30 label/);
    expect(document.querySelector(".cell-marker.cursor")).not.toBeNull();
    await userEvent.click(within(show).getByRole("button", { name: "Households" }));
    expect(screen.getByText("Households contributing")).toBeInTheDocument();
    expect(readout).toHaveTextContent(/2013-01-02, 00:30 label/);
  });

  it("on a wide screen shows both maps together and can enlarge them without dropping a cell", async () => {
    stubFetch(terrainBytes);
    await renderPage();
    await screen.findByRole("application", { name: /Flat map/ }, { timeout: 8000 });
    expect(document.querySelectorAll(".carpet")).toHaveLength(2);
    const canvases = document.querySelectorAll<HTMLCanvasElement>(".carpet-frame canvas");
    expect(canvases).toHaveLength(2);
    // one canvas pixel per cell, whatever the displayed size
    for (const c of canvases) expect([c.width, c.height]).toEqual([48, 365]);
    await userEvent.click(screen.getByLabelText("larger map"));
    expect(document.querySelector(".carpets")).toHaveClass("large");
    await userEvent.click(screen.getByLabelText("show coverage"));
    expect(document.querySelectorAll(".carpet")).toHaveLength(3);
  });

  it("carries the reduced-motion preference into the section", async () => {
    mediaMatching("prefers-reduced-motion");
    stubFetch(terrainBytes);
    await renderPage();
    await screen.findByRole("application", { name: /Flat map/ }, { timeout: 8000 });
    expect(document.querySelector(".instrument.year")).toHaveAttribute("data-reduced-motion", "true");
  });
});
