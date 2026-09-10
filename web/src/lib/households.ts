import type { Household } from "./bundle";
import { OUTCOME } from "./palette";
import { integer, money, outcomeWord, pct, signedMoney, signedPct } from "./format";

export type SortKey = "pct" | "gbp" | "coverage";

export const COLOUR = OUTCOME;

export function sortHouseholds(list: Household[], key: SortKey): Household[] {
  const value = (h: Household) =>
    key === "pct"
      ? (h.pct_of_flat.display ?? 0)
      : key === "gbp"
        ? h.flat_minus_dynamic.display
        : (h.coverage.display ?? 0);
  return [...list].sort((a, b) => value(a) - value(b) || a.household_id.localeCompare(b.household_id));
}

export function describe(h: Household): string {
  const cov = h.coverage.display;
  return (
    `${h.household_id}: ${outcomeWord(h.outcome_under_dynamic)} by ${signedPct(h.pct_of_flat.display)} ` +
    `(${signedMoney(h.flat_minus_dynamic.display)}); dynamic ${money(h.dynamic_charge.display)}, ` +
    `flat ${money(h.flat_charge.display)}; charged for ${integer(h.charged_readings)} of ` +
    `${integer(h.schedule_slots)} half hours (${pct(cov)} coverage)`
  );
}


export function highShare(h: Household): number {
  return h.bands.find((b) => b.band === "High")?.consumption_share_pct ?? 0;
}

/** Rank of a household's High-band share among all households, 1 = largest. */
export function highRank(households: Household[], id: string): number {
  const ordered = [...households].sort((a, b) => highShare(b) - highShare(a) || a.household_id.localeCompare(b.household_id));
  return ordered.findIndex((h) => h.household_id === id) + 1;
}

