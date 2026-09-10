/**
 * Formatting only. Every number here is a `display` value the bundle already rounded;
 * nothing is added, subtracted or divided in this module.
 */

const gbp = new Intl.NumberFormat("en-GB", {
  style: "currency",
  currency: "GBP",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const count = new Intl.NumberFormat("en-GB");
const kwh3 = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 3, maximumFractionDigits: 3 });

export function money(display: number): string {
  return gbp.format(display);
}

export function signedMoney(display: number): string {
  if (display > 0) return `+${gbp.format(display)}`;
  if (display < 0) return `−${gbp.format(Math.abs(display))}`;
  return gbp.format(0);
}

export function signedPct(display: number | null): string {
  if (display === null) return "undefined";
  const sign = display > 0 ? "+" : display < 0 ? "−" : "";
  return `${sign}${Math.abs(display).toFixed(1)}%`;
}

export function pct(display: number | null, digits = 1): string {
  return display === null ? "n/a" : `${display.toFixed(digits)}%`;
}

export function integer(value: number): string {
  return count.format(value);
}

export function energy(display: number): string {
  return `${kwh3.format(display)} kWh`;
}

export function pence(display: number | null): string {
  return display === null ? "n/a" : `${display.toFixed(3)}p`;
}

export function outcomeWord(outcome: "lower" | "higher" | "equal"): string {
  return outcome === "lower"
    ? "lower under the dynamic tariff"
    : outcome === "higher"
      ? "higher under the dynamic tariff"
      : "the same under both";
}

export function outcomeGlyph(outcome: "lower" | "higher" | "equal"): string {
  return outcome === "lower" ? "▲" : outcome === "higher" ? "▼" : "=";
}

export function shortDigest(hex: string | null | undefined, n = 12): string {
  return hex ? `${hex.slice(0, n)}…` : "n/a";
}

export function reasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    ineligible_tariff_group: "flat-rate households (not on the dynamic tariff)",
    outside_schedule_period: "outside the 2013 schedule",
    conflicting_label: "conflicting readings at one timestamp",
    off_grid_observation: "timestamp off the half-hour grid",
    missing_value: "missing value",
    unmatched_schedule_label: "no schedule label for the timestamp",
    unpriced_band: "band without a price",
  };
  return labels[reason] ?? reason.replaceAll("_", " ");
}
