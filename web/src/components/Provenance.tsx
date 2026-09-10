import type { Bundle } from "../lib/bundle";
import { integer, money, pct, signedMoney, signedPct } from "../lib/format";

const REPO = "https://github.com/Hammamelsh/energy-reconciliation";

export function Provenance({ bundle, digest }: { bundle: Bundle; digest: string }) {
  const p = bundle.source.publication;
  const a = bundle.source.attribution;
  const c = bundle.comparison;
  const rows: [string, string][] = [
    ["published version", `${p.version} (${p.version_file})`],
    ["promoted (UTC)", String(p.promoted_at_utc)],
    ["dbt build run", String(p.run_id)],
    ["required build", `${p.required_build} — ${p.required_nodes_total} required nodes`],
    ["dbt", `dbt-core ${p.dbt_core_version}, dbt-duckdb ${p.dbt_duckdb_version}`],
    ["schedule", `${p.schedule_source} (${p.schedule_variant}), sha256 ${p.schedule_sha256}`],
    ["price catalogue", String(p.price_catalogue_version)],
    ["calculation code sha256", String(p.calculation_code_sha256)],
    ["built tables digest", `${p.built_output_sha256} (${p.output_digest_version})`],
    ["version file sha256", String(p.file_sha256)],
    ["this page's data (bundle) sha256", digest],
    ["runtime fingerprint", String(p.runtime_fingerprint)],
  ];
  return (
    <div>
      <details open>
        <summary>Assumptions — the two things this scenario takes as given</summary>
        <div className="body">
          <p>
            <b>A1.</b> {bundle.assumptions.A1}
          </p>
          <p>
            <b>A2.</b> {bundle.assumptions.A2}
          </p>
          <p>
            Prices are publisher-documented: {bundle.prices.map((x) => `${x.tariff_group} ${x.band} ${Number(x.pence_per_kwh).toFixed(x.band === "flat" ? 3 : 2)}p (${x.valid_from === "UNKNOWN" ? "period unknown" : `${x.valid_from} to ${x.valid_until_exclusive}`})`).join(" · ")}.
          </p>
        </div>
      </details>
      <details>
        <summary>What this does not show</summary>
        <div className="body">
          <ul>
            {bundle.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <p>
            Variation, stated only as measured: the largest single household difference is{" "}
            {c.variation.largest_difference ? signedMoney(c.variation.largest_difference.display) : "—"}
            {c.variation.largest_share_of_pooled_pct?.display != null
              ? ` (${pct(c.variation.largest_share_of_pooled_pct.display)} of the pooled difference)`
              : ""}
            ; the median household difference is{" "}
            {c.variation.median_household_difference ? signedMoney(c.variation.median_household_difference.display) : "—"}.
          </p>
        </div>
      </details>
      <details>
        <summary>Where the numbers come from — identity of the sealed build</summary>
        <div className="body">
          <table className="idtable">
            <tbody>
              {rows.map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td className="mono">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Every value on this page was exported from that sealed publication by{" "}
            <a href={`${REPO}/blob/main/src/energy_reconciliation/presentation.py`}>one deterministic export</a>; exact
            decimals travel as text, and the browser only formats them. Pooled: dynamic {money(c.dynamic_charge.display)} = £
            {c.dynamic_charge.exact}; flat {money(c.flat_charge.display)} = £{c.flat_charge.exact}; difference{" "}
            {signedMoney(c.flat_minus_dynamic.display)} = £{c.flat_minus_dynamic.exact} ({signedPct(c.pct_of_flat.display)} of the flat-price
            charge; exact {c.pct_of_flat.exact}%).
          </p>
        </div>
      </details>
      <details>
        <summary>The data, its licence, and what is and is not here</summary>
        <div className="body">
          <p>
            {a.notice} Accessed {a.accessed}.{" "}
            <a href={a.dataset_url}>Dataset</a> · <a href={a.licence_url}>{a.licence}</a>.
          </p>
          <p>
            This page holds summaries only: {integer(c.households)} household totals, band shares, counts and identities —
            no individual reading and no per-reading timestamp. Household codes are the publisher's own pseudonymous
            identifiers; nothing here links them to a person, an address or a location, and no map is drawn because the
            data contains no coordinates.
          </p>
          <p>
            The project's code has no licence yet: readable, not reusable. The <a href={REPO}>repository</a> holds the
            calculation, the tests and the full write-ups.
          </p>
        </div>
      </details>
    </div>
  );
}
