import { useState } from "react";
import type { Household } from "../lib/bundle";
import { energy, integer, money, outcomeGlyph, outcomeWord, pct, pence, signedMoney, signedPct } from "../lib/format";

const BANDS = ["Low", "Normal", "High"] as const;

export function HouseholdDetail({ household: h, flatPence, highRank, total }: { household: Household; flatPence: string; highRank: number; total: number }) {
  const [copied, setCopied] = useState(false);
  const max = Math.max(h.dynamic_charge.display, h.flat_charge.display, 0.01);
  const bands = BANDS.map((b) => h.bands.find((x) => x.band === b)).filter(Boolean) as Household["bands"];
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className={`card detail ${h.outcome_under_dynamic === "higher" ? "higher-tone" : ""}`} aria-live="polite">
      <div className="id">{h.household_id}</div>
      <h3 style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span>{signedMoney(h.flat_minus_dynamic.display)}</span>
        <span className={`badge ${h.outcome_under_dynamic}`}>
          <span aria-hidden="true">{outcomeGlyph(h.outcome_under_dynamic)}</span> {outcomeWord(h.outcome_under_dynamic)}
        </span>
      </h3>

      <div className="bars">
        <div className="hbar">
          <span>Dynamic</span>
          <div className="track">
            <div className="fill dyn" style={{ width: `${(h.dynamic_charge.display / max) * 100}%` }} />
          </div>
          <b>{money(h.dynamic_charge.display)}</b>
        </div>
        <div className="hbar">
          <span>Flat price</span>
          <div className="track">
            <div className="fill flat" style={{ width: `${(h.flat_charge.display / max) * 100}%` }} />
          </div>
          <b>{money(h.flat_charge.display)}</b>
        </div>
      </div>

      <dl className="kv">
        <dt>Difference</dt>
        <dd>
          {signedMoney(h.flat_minus_dynamic.display)} · {signedPct(h.pct_of_flat.display)} of its flat-price charge
        </dd>
        <dt>Break-even flat price</dt>
        <dd>
          {pence(h.breakeven_flat_price.display)} per kWh{" "}
          <span className="hint" style={{ display: "inline" }}>
            (documented flat price {Number(flatPence).toFixed(3)}p)
          </span>
        </dd>
        <dt>Charged readings</dt>
        <dd>
          {integer(h.charged_readings)} of {integer(h.schedule_slots)} half hours · {pct(h.coverage.display)} coverage
        </dd>
        <dt>Period</dt>
        <dd>
          {h.first_charged_date} to {h.last_charged_date}
        </dd>
        <dt>Energy</dt>
        <dd>{energy(h.kwh.display)}</dd>
      </dl>

      <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 6 }}>Where its electricity fell, by price band</div>
      <div className="stack" role="img" aria-label={`Consumption share by band: ${bands.map((b) => `${b.band} ${b.consumption_share_pct}%`).join(", ")}`}>
        {bands.map((b) => (
          <span key={b.band} className={`band-${b.band}`} style={{ width: `${b.consumption_share_pct}%` }} title={`${b.band}: ${b.consumption_share_pct}% of kWh`} />
        ))}
      </div>
      <div style={{ fontSize: 13, color: "var(--muted)" }}>Where its scenario charge fell, by price band</div>
      <div className="stack" role="img" aria-label={`Charge share by band: ${bands.map((b) => `${b.band} ${b.charge_share_pct}%`).join(", ")}`}>
        {bands.map((b) => (
          <span key={b.band} className={`band-${b.band}`} style={{ width: `${b.charge_share_pct}%` }} title={`${b.band}: ${b.charge_share_pct}% of charge`} />
        ))}
      </div>
      <div className="chips">
        {bands.map((b) => (
          <span key={b.band}>
            <i className={`band-${b.band}`} />
            {b.band} {Number(b.price_pence_per_kwh).toFixed(2)}p · {b.consumption_share_pct}% of kWh → {b.charge_share_pct}% of charge
          </span>
        ))}
      </div>
      <p className="why">
        {(() => {
          const high = bands.find((b) => b.band === "High");
          const share = high?.consumption_share_pct ?? 0;
          const chargeShare = high?.charge_share_pct ?? 0;
          const pos = highRank === 1 ? "the largest of any household" : highRank === total ? "the smallest of any household" : `rank ${highRank} of ${total}`;
          return `${share.toFixed(1)}% of its electricity fell in High-price half hours — ${pos} — and that ${share.toFixed(1)}% became ${chargeShare.toFixed(1)}% of its scenario charge. ${
            h.outcome_under_dynamic === "higher"
              ? "Enough to tip it: on this recorded consumption the flat price comes out lower."
              : h.outcome_under_dynamic === "lower"
                ? "Not enough to outweigh the cheaper Low and Normal half hours, so the dynamic scenario comes out lower."
                : "Exactly balanced."
          }`;
        })()}
      </p>
      <p className="hint">Coverage is observed half-hour labels, never scaled to a year.</p>
      <button className="copy" type="button" onClick={copy}>
        {copied ? "Link copied" : "Copy a link to this household"}
      </button>
    </div>
  );
}
