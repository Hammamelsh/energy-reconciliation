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
    expect(screen.getByRole("heading", { name: bundle.terrain.title })).toBeInTheDocument();
    const map = await screen.findByRole("application", { name: /Flat map of 365 date labels by 48 half-hour labels/ }, { timeout: 8000 });
    // the readout opens on the tallest cell of the charge view, from the file's own peaks
    const readout = document.getElementById("year-readout")!;
    await waitFor(() => expect(readout).toHaveTextContent(/Tallest half hour in this view: 2013-03-17, 19:30 label/));
    expect(readout).toHaveTextContent(/dynamic charge £7\.43/);
    // the flat map is the default view everywhere; 3D is loaded only on request
    const views = screen.getByRole("group", { name: "View" });
    const flat = within(views).getByRole("button", { name: "flat map" });
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
    expect(screen.getByText(/Exact year totals from the export: 85467\.1329968000 kWh and £11675\.4339216532500000/)).toBeInTheDocument();
  });

  it("asks for WebGL only on request and reports when it is unavailable", async () => {
    stubFetch(terrainBytes);
    await renderPage();
    await screen.findByRole("application", { name: /Flat map/ }, { timeout: 8000 });
    const views = screen.getByRole("group", { name: "View" });
    await userEvent.click(within(views).getByRole("button", { name: /^3D terrain/ }));
    // the 3D chunk (Three.js) is imported on demand; give the import time to resolve
    expect(await screen.findByText(/The 3D view is not available here: this browser provides no WebGL context/, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByRole("application", { name: /Flat map/ })).toBeInTheDocument();
    expect(within(views).getByRole("button", { name: /^3D terrain/ })).toBeDisabled();
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

  it("carries the reduced-motion preference into the section", async () => {
    mediaMatching("prefers-reduced-motion");
    stubFetch(terrainBytes);
    await renderPage();
    await screen.findByRole("application", { name: /Flat map/ }, { timeout: 8000 });
    expect(document.querySelector(".instrument.year")).toHaveAttribute("data-reduced-motion", "true");
  });
});
