import type { Bundle } from "../lib/bundle";
import { integer, pct } from "../lib/format";

export function Quality({ bundle }: { bundle: Bundle }) {
  const q = bundle.data_quality;
  const z = q.whole_zero_days;
  const f = bundle.forecast;
  const prof = bundle.source_file_profile;
  const maxMae = f.status === "applicable" ? Math.max(...f.holdout.models.map((m) => m.mae_kwh.display)) : 1;
  return (
    <div className="grid3">
      <div className="card">
        <h3>What the source actually contains</h3>
        <p className="hint" style={{ marginTop: 0 }}>{q.scope}: {integer(q.readings_loaded)} readings, {bundle.source.warehouse.households} households.</p>
        <div className="mini">
          <div className="row"><span>identical duplicate rows collapsed</span><b>{integer(q.exact_duplicate_extra_rows)}</b></div>
          <div className="row"><span>timestamps with conflicting values</span><b>{integer(q.conflicting_keys)}</b></div>
          <div className="row"><span>“Null” written where a reading should be</span><b>{integer(q.null_tokens)}</b></div>
          <div className="row"><span>readings off the half-hour grid</span><b>{integer(q.off_grid_rows)}</b></div>
          <div className="row"><span>readings of exactly zero</span><b>{integer(q.zero_readings)}</b></div>
        </div>
        <p className="hint">Missing is recorded as missing — nothing is filled with zero. A zero is a reading. Conflicts withhold a total rather than pick a side.</p>
        {prof && (
          <p className="hint">
            One file profiled in full ({String(prof.source_file)}): {integer(Number(prof.records))} records, {integer(Number(prof.exact_duplicate_extra_rows))} duplicate rows, {integer(Number(prof.null_tokens))} Null tokens (all {integer(Number(prof.off_grid_rows))} off the grid), {integer(Number(prof.zero_values))} zeros, {integer(Number(prof.households))} households.
          </p>
        )}
      </div>

      {z && (
        <div className="card">
          <h3>Zeros arrive in runs</h3>
          <div className="big">
            <span className="ember">{integer(z.zero_days)}</span> whole days at exactly zero
          </div>
          <div className="mini" style={{ marginTop: 8 }}>
            <div className="row"><span>of usable days</span><b>{integer(z.usable_days)} ({pct((z.zero_days / z.usable_days) * 100, 2)})</b></div>
            <div className="row"><span>households affected</span><b>{z.households_with_zero_days} of {z.households}</b></div>
            <div className="row"><span>runs of consecutive zero days</span><b>{z.runs}</b></div>
            <div className="row"><span>runs of four weeks or more</span><b>{z.runs_28_days_or_more}</b></div>
            <div className="row"><span>runs with normal usage on both sides</span><b>{z.runs_bounded_by_nonzero_usable_days} of {z.runs}</b></div>
            <div className="row"><span>longest run</span><b>{z.longest_run_days} days</b></div>
          </div>
          <p className="hint">
            A day of exact zeros costs nothing and raises no error — which is why it is worth finding. Why the days are
            zero is {z.cause}. These households are on the flat rate; none is in the tariff comparison.
          </p>
        </div>
      )}

      <div className="card">
        <h3>Can yesterday predict tomorrow?</h3>
        {f.status === "applicable" ? (
          <>
            <p className="hint" style={{ marginTop: 0 }}>
              Simple daily baselines, scored on the final {f.cohort.holdout_days} days of {f.cohort.households} households'
              clean runs — mean absolute error per day, lower is better.
            </p>
            <div className="bars">
              {f.holdout.models.map((m) => (
                <div className="fbar" key={m.name}>
                  <span title={m.description}>{m.name.replaceAll("_", " ")}</span>
                  <div className="track">
                    <div className={`fill ${m.name.startsWith("persistence") ? "ref" : ""}`} style={{ width: `${(m.mae_kwh.display / maxMae) * 100}%` }} />
                  </div>
                  <b>{m.mae_kwh.display.toFixed(3)} kWh</b>
                </div>
              ))}
            </div>
            <p className="hint">
              {f.holdout.scored_predictions_per_model} scored predictions per model. Every prediction uses only data dated on or
              before its origin. A retrospective, clean-data cohort — a floor for accuracy, not a forecast product.
            </p>
          </>
        ) : (
          <p className="hint" style={{ marginTop: 0 }}>Forecast summary omitted: {f.reason}.</p>
        )}
      </div>
    </div>
  );
}
