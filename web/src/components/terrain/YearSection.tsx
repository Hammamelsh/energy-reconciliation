import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { Bundle, Manifest } from "../../lib/bundle";
import { describeCell, indexOf, loadTerrain, type Mode, type Terrain } from "../../lib/terrain";
import { energy, integer, money } from "../../lib/format";
import { useInView, useMediaQuery } from "../../hooks";
import { TerrainFlat } from "./TerrainFlat";
import { BAND_HEX, type Carpet, type Highlight } from "./flat";

// The 3D scene and Three.js live in their own chunk, fetched only when the terrain is
// about to be drawn in 3D. The initial page never carries them.
const Terrain3D = lazy(() => import("./Terrain3D"));

type DataState =
  | { kind: "loading" }
  | { kind: "ready"; terrain: Terrain }
  | { kind: "error"; message: string };

const BANDS: Highlight[] = ["all", "Low", "Normal", "High"];

function peakIndex(t: Terrain, mode: Mode): number | null {
  const p = mode === "kwh" ? t.peaks.kwh : t.peaks.charge;
  if (!p) return null;
  const d = t.grid.date_labels.indexOf(p.date);
  return d < 0 ? null : indexOf(t, d, p.slot);
}

export function YearSection({ bundle, manifest, base = "data/" }: { bundle: Bundle; manifest: Manifest; base?: string }) {
  const s = bundle.terrain;
  const high = bundle.bands.find((b) => b.band === "High");
  const [ref, near] = useInView<HTMLDivElement>("600px 0px");
  const [data, setData] = useState<DataState>({ kind: "loading" });
  const started = useRef(false);
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)");
  // One map at a time on a narrow screen; two side by side otherwise.
  const compact = useMediaQuery("(max-width: 700px)");
  const [mode, setMode] = useState<Mode>("charge");
  const [single, setSingle] = useState<Carpet>("charge");
  const [highlight, setHighlight] = useState<Highlight>("all");
  const [want3d, setWant3d] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [showCoverage, setShowCoverage] = useState(false);
  const [large, setLarge] = useState(false);

  useEffect(() => {
    // the file is fetched once, when the section comes within 600px of the viewport
    if (!near || started.current) return;
    started.current = true;
    let cancelled = false;
    loadTerrain(manifest, base)
      .then((terrain) => !cancelled && setData({ kind: "ready", terrain }))
      .catch((error: unknown) => {
        if (!cancelled) setData({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [near, manifest, base]);

  const terrain = data.kind === "ready" ? data.terrain : null;
  // The flat map is the view on every device; the 3D terrain (and Three.js) load only when asked for.
  const show3d = want3d === true && unavailable === null;
  const focus = hover ?? cursor;
  const readout = useMemo(() => {
    if (!terrain) return null;
    if (focus !== null) return describeCell(terrain, focus);
    const p = peakIndex(terrain, mode);
    return p === null ? "No cell has a charged reading." : `Tallest half hour in this view: ${describeCell(terrain, p)}`;
  }, [terrain, focus, mode]);

  // The date in the readout stays on one line on a phone: the same characters, wrapped, not replaced.
  const readoutNode = useMemo(() => {
    if (readout === null) return null;
    const m = readout.match(/^([^]*?)(\d{4}-\d{2}-\d{2})([^]*)$/);
    if (!m) return readout;
    return (
      <>
        {m[1]}
        <span className="nobreak">{m[2]}</span>
        {m[3]}
      </>
    );
  }, [readout]);

  const year = s.grid.first_date.slice(0, 4);
  // The single-map choice on a narrow screen also sets what the 3D height shows, so the
  // selected cell and the "tallest half hour" readout carry across views.
  const pickSingle = (c: Carpet) => {
    setSingle(c);
    if (c !== "coverage") setMode(c);
  };

  // Measure, band highlight and view are the primary controls; camera and zoom live inside
  // the 3D panel. On a phone the measure and view controls come before the map, and the
  // band highlight sits behind a small disclosure so the map is not pushed down.
  const measureCtl = compact ? (
    <span className="ctl">
      <span className="lbl">Show</span>
      <span className="seg" role="group" aria-label="Which map to show">
        <button type="button" aria-pressed={single === "kwh"} onClick={() => pickSingle("kwh")}>
          Electricity
        </button>
        <button type="button" aria-pressed={single === "charge"} onClick={() => pickSingle("charge")}>
          Charge
        </button>
        <button
          type="button"
          aria-pressed={single === "coverage"}
          disabled={show3d}
          title={show3d ? "Households are shown on the flat map" : undefined}
          onClick={() => pickSingle("coverage")}
        >
          Households
        </button>
      </span>
    </span>
  ) : show3d ? (
    <span className="ctl">
      <span className="lbl">Height</span>
      <span className="seg" role="group" aria-label="What height shows">
        <button type="button" aria-pressed={mode === "kwh"} onClick={() => setMode("kwh")}>
          Electricity, kWh
        </button>
        <button type="button" aria-pressed={mode === "charge"} onClick={() => setMode("charge")}>
          Charge, £
        </button>
      </span>
    </span>
  ) : null;
  const highlightCtl = (
    <span className="ctl">
      <span className="lbl">Highlight</span>
      <span className="seg" role="group" aria-label="Highlight one band">
        {BANDS.map((b) => (
          <button key={b} type="button" aria-pressed={highlight === b} onClick={() => setHighlight(b)}>
            {b === "all" ? "all bands" : b}
          </button>
        ))}
      </span>
    </span>
  );
  const viewCtl = (
    <span className="ctl">
      <span className="lbl">View</span>
      <span className="seg" role="group" aria-label="View">
        <button
          type="button"
          aria-pressed={show3d}
          disabled={unavailable !== null}
          title={unavailable ?? undefined}
          onClick={() => setWant3d(true)}
        >
          Explore in 3D
        </button>
        <button type="button" aria-pressed={!show3d} onClick={() => setWant3d(false)}>
          Flat map
        </button>
      </span>
    </span>
  );
  const toolbar = compact ? (
    <>
      <div className="instrument-bar" role="toolbar" aria-label="Map controls">
        {measureCtl}
        {viewCtl}
      </div>
      <details className="map-options">
        <summary>Map options</summary>
        <div className="body">{highlightCtl}</div>
      </details>
    </>
  ) : (
    <div className="instrument-bar" role="toolbar" aria-label="Map controls">
      {measureCtl}
      {highlightCtl}
      {viewCtl}
      {!show3d && (
        <span className="lbl-checks">
          <label className="lbl-check">
            <input type="checkbox" checked={showCoverage} onChange={(e) => setShowCoverage(e.target.checked)} /> show coverage
          </label>
          <label className="lbl-check">
            <input type="checkbox" checked={large} onChange={(e) => setLarge(e.target.checked)} /> larger map
          </label>
        </span>
      )}
    </div>
  );

  return (
    <div ref={ref} className="instrument year" data-reduced-motion={reduced ? "true" : "false"}>
      {high && (
        <div
          className="takeaway"
          role="img"
          aria-label={`High-price half-hours: ${high.consumption_share_pct}% of included electricity, ${high.charge_share_pct}% of calculated energy charge.`}
        >
          <div className="takeaway-title">High-price half-hours</div>
          <div className="takeaway-row">
            <span>of included electricity</span>
            <div className="track">
              <i style={{ width: `${high.consumption_share_pct}%` }} />
            </div>
            <b>{high.consumption_share_pct}%</b>
          </div>
          <div className="takeaway-row">
            <span>of calculated energy charge</span>
            <div className="track">
              <i style={{ width: `${high.charge_share_pct}%` }} />
            </div>
            <b>{high.charge_share_pct}%</b>
          </div>
        </div>
      )}
      <p className="year-lead">
        Each cell represents one half-hour timestamp label in {year}. Brightness shows the amount. Colour shows its tariff band.
      </p>
      <p className="year-note">
        {s.coverage.households_per_cell_min} to {s.coverage.households_per_cell_max} households per cell. Historical scenario under
        A1, not a bill.
      </p>
      <details className="year-how">
        <summary>How to read this map</summary>
        <div className="body">
          <p>
            <b>Cells and coverage.</b> One cell per half-hour timestamp label of {year}: {integer(s.grid.cells)} cells,{" "}
            {integer(s.grid.dates)} date labels down the side by {s.grid.slots} labels across the day. A cell pools the charged
            readings of the households present in it, {s.coverage.households_per_cell_min} to {s.coverage.households_per_cell_max} of
            the {s.totals.households}; a brightness or height also moves when that coverage changes, not only when recorded usage
            does. A cell with no charged reading is empty, not zero.
          </p>
          <p>
            <b>Included electricity, calculated charge.</b> "Included" means the readings the dynamic scenario charged: time-of-use
            households' readings inside the 2013 schedule that carry a value and a schedule label. The charge is that reading's
            kWh times the band price the schedule assigned, under assumption A1 (a reading's timestamp label and the schedule label
            denote the same half hour). Assumption A2, the documented flat price, belongs only to the dynamic-versus-flat comparison
            elsewhere on this page; it does not shape these maps.
          </p>
          <p>
            <b>Brightness and colour.</b> Brightness on the flat map, or height in 3D, is the amount in the cell on a linear,
            zero-based scale, stated beneath each map with its maximum; the two maps are not on a shared scale. Colour is the band
            the schedule assigned to that half hour: Low, Normal or High. These band colours differ from the lime and ember used
            elsewhere for a lower or higher outcome.
          </p>
          <p>
            <b>Rounding and totals.</b> Cell values are rounded once in the export, kWh to three decimal places and charge to two,
            and are never added in the browser. The {s.peaks.charge ? money(s.peaks.charge.charge.display) : "peak"} shown for the
            highest label is that display value; the export's unrounded pooled charge for it is £{s.peaks.charge?.charge.exact ?? "n/a"}.
            Together the cells hold {energy(s.totals.kwh.display)} and {money(s.totals.charge.display)} as display totals; the
            export's full-precision totals, reconciled against the comparison before the file was written, appear under the month
            table.
          </p>
          <p>
            <b>Reading a cell.</b> Hover, tap or use the arrow keys; the readout beneath the map states the cell's label, kWh,
            households, band, price and charge. Page Up and Page Down move a week; Home and End reach the first and last half hour
            of the day.
          </p>
          {terrain && (
            <ul className="caveats">
              {terrain.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      </details>

      {toolbar}

      <div className="stage">
      {data.kind === "loading" ? (
        <p className="hint stage-note" role="status">
          Loading the terrain file and checking its digest…
        </p>
      ) : data.kind === "error" ? (
        <div className="refusal" role="alert">
          <b>The terrain data did not match its pinned digest.</b> {data.message}. Nothing is drawn in its place; the figures
          above come from the verified bundle.
        </div>
      ) : show3d ? (
        <Suspense
          fallback={
            <p className="hint stage-note" role="status">
              Loading the 3D scene…
            </p>
          }
        >
          <Terrain3D
            terrain={data.terrain}
            mode={mode}
            highlight={highlight}
            cursor={cursor}
            hover={hover}
            reducedMotion={reduced}
            onHover={setHover}
            onSelect={setCursor}
            onCursor={setCursor}
            onUnavailable={(why) => setUnavailable(why)}
          />
        </Suspense>
      ) : (
        <TerrainFlat
          terrain={data.terrain}
          highlight={highlight}
          cursor={cursor}
          hover={hover}
          onHover={setHover}
          onSelect={setCursor}
          onCursor={setCursor}
          showCoverage={showCoverage}
          only={compact ? single : null}
          large={large && !compact}
        />
      )}
      </div>

      <div className="band-legend" role="group" aria-label="Legend">
        <span>
          <i style={{ background: BAND_HEX.Low }} className="sw low" /> Low, 3.99p
        </span>
        <span>
          <i style={{ background: BAND_HEX.Normal }} className="sw normal" /> Normal, 11.76p
        </span>
        <span>
          <i style={{ background: BAND_HEX.High }} className="sw high" /> High, 67.20p (striped in 3D when zoomed)
        </span>
        <span className="dimtext">Brightness shows amount. Colour shows tariff band.</span>
      </div>

      <p className="readout" id="year-readout" aria-live="polite">
        {readoutNode ?? "Cell readout appears here once the terrain has loaded."}
      </p>
      {unavailable && (
        <p className="hint" role="status">
          The 3D view is not available here: {unavailable}. The flat map shows the same cells.
        </p>
      )}

      {terrain && (
        <details>
          <summary>The same cells as a table: month by band</summary>
          <div className="body scroll-x">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Month</th>
                  <th>Half hours</th>
                  <th>Households</th>
                  <th>kWh</th>
                  <th>Dynamic £</th>
                  <th>High kWh</th>
                  <th>High £</th>
                </tr>
              </thead>
              <tbody>
                {terrain.by_month.map((m) => (
                  <tr key={m.month}>
                    <td>{m.month}</td>
                    <td>{integer(m.cells_with_readings)}</td>
                    <td>
                      {m.households_min === m.households_max ? m.households_min : `${m.households_min} to ${m.households_max}`}
                    </td>
                    <td>{energy(m.kwh.display)}</td>
                    <td>{money(m.charge.display)}</td>
                    <td>{energy(m.bands.High.kwh.display)}</td>
                    <td>{money(m.bands.High.charge.display)}</td>
                  </tr>
                ))}
                <tr>
                  <td>{year}</td>
                  <td>{integer(terrain.coverage.cells_with_readings)}</td>
                  <td>
                    {terrain.coverage.households_per_cell_min} to {terrain.coverage.households_per_cell_max}
                  </td>
                  <td>{energy(terrain.totals.kwh.display)}</td>
                  <td>{money(terrain.totals.charge.display)}</td>
                  <td>{energy(terrain.by_band.find((b) => b.band === "High")?.kwh.display ?? 0)}</td>
                  <td>{money(terrain.by_band.find((b) => b.band === "High")?.charge.display ?? 0)}</td>
                </tr>
              </tbody>
            </table>
            <p className="hint">
              Full-precision year totals from the export: {terrain.totals.kwh.exact} kWh and £{terrain.totals.charge.exact},
              reconciled against the comparison ({terrain.reconciliation.compared_with}) before this file was written. Monthly
              rows are display values rounded once in the export.
            </p>
          </div>
        </details>
      )}
    </div>
  );
}
