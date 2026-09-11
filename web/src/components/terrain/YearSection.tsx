import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { Bundle, Manifest } from "../../lib/bundle";
import { describeCell, indexOf, loadTerrain, type Mode, type Terrain } from "../../lib/terrain";
import { energy, integer, money } from "../../lib/format";
import { useInView, useMediaQuery } from "../../hooks";
import { TerrainFlat } from "./TerrainFlat";
import { BAND_HEX, type Highlight } from "./flat";

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
  const [mode, setMode] = useState<Mode>("charge");
  const [highlight, setHighlight] = useState<Highlight>("all");
  const [want3d, setWant3d] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [showCoverage, setShowCoverage] = useState(false);

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

  const year = s.grid.first_date.slice(0, 4);
  const shares = high ? `${high.consumption_share_pct}% of the electricity and ${high.charge_share_pct}% of the charge` : null;

  return (
    <div ref={ref} className="instrument year" data-reduced-motion={reduced ? "true" : "false"}>
      <p className="sub" style={{ marginBottom: 14 }}>
        Every half hour of {year}: {integer(s.grid.cells)} cells, each pooling the charged readings of{" "}
        {s.coverage.households_per_cell_min} to {s.coverage.households_per_cell_max} of the {s.totals.households} households on the dynamic
        tariff. Colour is the band the schedule assigned to that half hour; height, or brightness on the flat map, is the
        electricity recorded in it, in kWh, or its cost under the dynamic scenario, in pounds. {shares && <>The High band is {shares}.</>}
        {" "}Together the cells hold exactly {energy(s.totals.kwh.display)} and {money(s.totals.charge.display)}, the comparison's dynamic total.
      </p>

      <div className="instrument-bar" role="toolbar" aria-label="Terrain controls">
        {show3d && (
          <>
            <span className="lbl">Height</span>
            <span className="seg square" role="group" aria-label="What height shows">
              <button type="button" aria-pressed={mode === "kwh"} onClick={() => setMode("kwh")}>
                charged kWh
              </button>
              <button type="button" aria-pressed={mode === "charge"} onClick={() => setMode("charge")}>
                dynamic charge, £
              </button>
            </span>
          </>
        )}
        <span className="lbl">Highlight</span>
        <span className="seg square" role="group" aria-label="Highlight one band">
          {BANDS.map((b) => (
            <button key={b} type="button" aria-pressed={highlight === b} onClick={() => setHighlight(b)}>
              {b === "all" ? "all bands" : b}
            </button>
          ))}
        </span>
        <span className="lbl">View</span>
        <span className="seg square" role="group" aria-label="View">
          <button
            type="button"
            aria-pressed={show3d}
            disabled={unavailable !== null}
            title={unavailable ?? undefined}
            onClick={() => setWant3d(true)}
          >
            3D terrain{!show3d && unavailable === null ? " (loads 135 kB)" : ""}
          </button>
          <button type="button" aria-pressed={!show3d} onClick={() => setWant3d(false)}>
            flat map
          </button>
        </span>
        {!show3d && (
          <label className="lbl-check">
            <input type="checkbox" checked={showCoverage} onChange={(e) => setShowCoverage(e.target.checked)} /> show coverage
          </label>
        )}
      </div>
      {unavailable && (
        <p className="hint" role="status">
          The 3D view is not available here: {unavailable}. The flat map shows the same cells.
        </p>
      )}

      {data.kind === "loading" ? (
        <p className="hint" role="status">
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
            <p className="hint" role="status">
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
        />
      )}

      <p className="readout" id="year-readout" aria-live="polite">
        {readout ?? "Cell readout appears here once the terrain has loaded."}
      </p>

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
        <span className="dimtext">band colours differ from the lime and ember used for lower and higher outcomes</span>
      </div>

      {terrain && (
        <>
          <ul className="caveats">
            {terrain.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
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
                Exact year totals from the export: {terrain.totals.kwh.exact} kWh and £{terrain.totals.charge.exact}, reconciled
                against the comparison ({terrain.reconciliation.compared_with}) before this file was written. Monthly rows are
                display values rounded once in the export.
              </p>
            </div>
          </details>
        </>
      )}
    </div>
  );
}
