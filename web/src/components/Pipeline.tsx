import type { Bundle } from "../lib/bundle";
import { integer, money, reasonLabel, shortDigest } from "../lib/format";
import { useCountUp, useInView } from "../hooks";

function Step({ n, t, s, run, amber, format }: { n: number; t: string; s?: string; run: boolean; amber?: boolean; format?: (v: number) => string }) {
  const v = useCountUp(n, 1000, run);
  const f = format ?? ((x: number) => integer(Math.round(x)));
  return (
    <div className="step">
      <div className={`n ${amber ? "amber" : ""}`}>{f(v)}</div>
      <div className="t">{t}</div>
      {s && <div className="s">{s}</div>}
    </div>
  );
}

export function Pipeline({ bundle, digest }: { bundle: Bundle; digest: string }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const a = bundle.accounting;
  const w = bundle.source.warehouse;
  const p = bundle.source.publication;
  const c = bundle.comparison;
  const reasons = Object.entries(a.excluded_by_reason).sort((x, y) => y[1] - x[1]);
  const maxReason = reasons[0]?.[1] ?? 1;
  return (
    <div ref={ref}>
      <div className="flow">
        <Step n={w.readings_loaded} t="readings loaded" s={`from ${w.source_files.length} of ${w.source_files_in_dataset} source files`} run={seen} />
        <Step n={a.rows_collapsed_by_policy} t="identical duplicates collapsed" s="counted, never silently dropped" run={seen} amber />
        <Step n={a.distinct_readings} t="distinct readings" s="every one ends up charged or excluded" run={seen} />
        <Step n={a.charged_readings} t="charged under the dynamic tariff" s="the 27 time-of-use households, 2013" run={seen} />
        <Step n={a.excluded_readings} t="excluded, each with one reason" s="flat-rate households, other years…" run={seen} amber />
        <Step n={c.dynamic_charge.display} t="the dynamic-tariff charge" s={`exact £${c.dynamic_charge.exact}`} run={seen} format={money} />
      </div>
      <div className="reasons" aria-label="Why readings were excluded">
        {reasons.map(([reason, n]) => (
          <div className="reason" key={reason}>
            <span>{reasonLabel(reason)}</span>
            <b>{integer(n)}</b>
            <div className="track">
              <div className="fill" style={{ width: seen ? `${(n / maxReason) * 100}%` : 0 }} />
            </div>
          </div>
        ))}
      </div>
      <p className="hint">
        {a.reconciles ? "The ladder reconciles: " : "The ladder does not reconcile: "}
        {integer(a.raw_rows)} − {integer(a.rows_collapsed_by_policy)} = {integer(a.distinct_readings)} ={" "}
        {integer(a.charged_readings)} + {integer(a.excluded_readings)}. Counted from the sealed tables, not copied
        from a note.
      </p>
      <div className="grid3" style={{ marginTop: 18 }}>
        <div className="card">
          <h3>Built and sealed</h3>
          <div className="mini">
            <div className="row"><span>dbt build</span><b>{p.required_nodes_total} of {p.required_nodes_total} nodes</b></div>
            <div className="row"><span>run</span><b className="mono">{String(p.run_id).slice(0, 22)}…</b></div>
            <div className="row"><span>published as</span><b>{String(p.version)}</b></div>
            <div className="row"><span>version file sha256</span><b className="mono">{shortDigest(String(p.file_sha256))}</b></div>
          </div>
        </div>
        <div className="card">
          <h3>Same answer twice</h3>
          <p className="hint" style={{ marginTop: 0 }}>
            The tariff rules are written once in Python and generated into dbt; a drift check and row-level
            equivalence tests keep the two paths equal. A published result can be rebuilt from the raw archive and
            compared field by field.
          </p>
        </div>
        <div className="card">
          <h3>Verified in your browser</h3>
          <div className="mini">
            <div className="row"><span>this page's data</span><b className="ok">sha256 matched ✓</b></div>
            <div className="row"><span>bundle digest</span><b className="mono">{shortDigest(digest)}</b></div>
            <div className="row"><span>source</span><b>publication {String(p.version)}</b></div>
          </div>
          <p className="hint">Your browser hashed the data file it received and compared it with the pinned manifest before showing a number.</p>
        </div>
      </div>
    </div>
  );
}
