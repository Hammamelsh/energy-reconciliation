/**
 * The presentation bundle: types, and loading it with its integrity verified.
 *
 * Every monetary and energy figure arrives as an exact decimal string with a unit and a
 * `display` value rounded once in Python. Nothing in the browser recomputes a charge, a
 * difference or a percentage; the page formats what it was given.
 */

import type { TerrainSummary } from "./terrain";

export type Money = { exact: string; unit: "GBP"; display: number };
export type Energy = { exact: string; unit: "kWh"; display: number };
export type Pct = {
  exact: string | null;
  unit: "percent";
  denominator: string;
  display: number | null;
};
export type Pence = { exact: string | null; unit: "pence per kWh"; display: number | null };

export type Band = {
  band: "Low" | "Normal" | "High" | string;
  price_pence_per_kwh: string;
  charged_readings: number;
  kwh: Energy;
  charge: Money;
  consumption_share_pct: number;
  charge_share_pct: number;
};

export type Outcome = "lower" | "higher" | "equal";

export type Household = {
  household_id: string;
  charged_readings: number;
  schedule_slots: number;
  coverage: Pct;
  first_charged_date: string;
  last_charged_date: string;
  kwh: Energy;
  dynamic_charge: Money;
  flat_charge: Money;
  flat_minus_dynamic: Money;
  pct_of_flat: Pct;
  breakeven_flat_price: Pence;
  outcome_under_dynamic: Outcome;
  bands: Band[];
};

export type Comparison = {
  definition: string;
  sign_convention: string;
  households: number;
  charged_readings: number;
  schedule_slots: number;
  kwh: Energy;
  dynamic_charge: Money;
  flat_charge: Money;
  flat_minus_dynamic: Money;
  pct_of_flat: Pct;
  breakeven_flat_price: Pence;
  breakeven_meaning: string;
  outcomes_under_dynamic: Record<Outcome, number>;
  variation: {
    largest_household?: string;
    largest_difference?: Money;
    largest_share_of_pooled_pct?: Pct;
    median_household_difference?: Money;
  };
  flat_price: {
    tariff_group: string;
    band: string;
    pence_per_kwh: string;
    gbp_per_kwh: string;
    catalogue_version: string;
    evidence_label: string;
    validity: string;
  };
  assumption_ids: string[];
  per_household: Household[];
};

export type HourBands = {
  hour_meaning: string;
  schedule_slots_by_band_and_hour: Record<string, number[]>;
  charged_kwh_by_band_and_hour: Record<string, ({ charged_readings: number; kwh: Energy } | null)[]>;
  caveat: string;
};

export type Accounting = {
  raw_rows: number;
  rows_collapsed_by_policy: number;
  distinct_readings: number;
  charged_readings: number;
  excluded_readings: number;
  excluded_by_reason: Record<string, number>;
  reconciles: boolean;
  counted_not_recorded: boolean;
};

export type ForecastModel = {
  name: string;
  description: string;
  mae_kwh: { exact: string; unit: string; display: number };
  median_ae_kwh_display: number;
};

export type Forecast =
  | { status: "omitted"; reason: string }
  | {
      status: "applicable";
      applicability: string;
      kind: string;
      target: string;
      cohort: {
        households: number;
        eligible_households: number;
        kind: string;
        min_run_days: number;
        holdout_days: number;
        horizon_days: number;
      };
      holdout: { scored_predictions_per_model: number; models: ForecastModel[] };
      identity: { dataset_sha256: string; forecast_code_sha256: string };
    };

export type Bundle = {
  definition: string;
  title: string;
  source: {
    publication: Record<string, string | number | null>;
    warehouse: {
      source_files: string[];
      source_files_in_dataset: number;
      readings_loaded: number;
      households: number;
      households_by_group: Record<string, number>;
      first_date: string;
      last_date: string;
    };
    attribution: Record<string, string>;
  };
  assumptions: { A1: string; A2: string };
  schedule: { first_date: string | null; last_date: string | null; source: string | null; slots: number | null };
  prices: {
    tariff_group: string;
    band: string;
    pence_per_kwh: string;
    gbp_per_kwh: string;
    valid_from: string;
    valid_until_exclusive: string;
    evidence_label: string;
  }[];
  bands: Band[];
  comparison: Comparison;
  hour_bands: HourBands;
  accounting: Accounting;
  data_quality: {
    scope: string;
    readings_loaded: number;
    exact_duplicate_extra_rows: number;
    conflicting_keys: number;
    null_tokens: number;
    off_grid_rows: number;
    zero_readings: number;
    policy: Record<string, string>;
    whole_zero_days?: {
      usable_days: number;
      zero_days: number;
      households_with_zero_days: number;
      households: number;
      runs: number;
      runs_28_days_or_more: number;
      runs_bounded_by_nonzero_usable_days: number;
      longest_run_days: number;
      cause: string;
    };
  };
  source_file_profile: Record<string, number | string | null> | null;
  forecast: Forecast;
  limitations: string[];
  terrain: TerrainSummary;
};

export type Manifest = {
  definition: string;
  bundle: string;
  content_digest: string;
  size_bytes: number;
  source: { version: string; run_id: string; file_sha256: string };
  /** The terrain file's pin: verified the same way before a cell is drawn. */
  terrain?: { file: string; definition: string; content_digest: string; size_bytes: number };
};

export const DEFINITION = "presentation-bundle-2";

export class BundleError extends Error {}

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Verify the bundle's bytes against the manifest before trusting a single number. */
export async function verifyBundle(manifest: Manifest, bytes: Uint8Array): Promise<Bundle> {
  if (manifest.definition !== DEFINITION) {
    throw new BundleError(`manifest definition ${manifest.definition} is not ${DEFINITION}`);
  }
  if (bytes.byteLength !== manifest.size_bytes) {
    throw new BundleError(
      `bundle is ${bytes.byteLength} bytes; the manifest pins ${manifest.size_bytes}`,
    );
  }
  const digest = await sha256Hex(bytes);
  if (digest !== manifest.content_digest) {
    throw new BundleError(
      `bundle digest ${digest.slice(0, 12)}… does not match the manifest's ${manifest.content_digest.slice(0, 12)}…`,
    );
  }
  const parsed = JSON.parse(new TextDecoder().decode(bytes)) as Bundle;
  if (parsed.definition !== DEFINITION) {
    throw new BundleError("bundle definition does not match");
  }
  if (parsed.source.publication.run_id !== manifest.source.run_id) {
    throw new BundleError("the bundle and its manifest name different runs");
  }
  return parsed;
}

export type Loaded = { bundle: Bundle; manifest: Manifest; digest: string };

export async function loadBundle(base = "data/"): Promise<Loaded> {
  const manifestResponse = await fetch(`${base}manifest.json`, { cache: "no-cache" });
  if (!manifestResponse.ok) throw new BundleError(`manifest: HTTP ${manifestResponse.status}`);
  const manifest = (await manifestResponse.json()) as Manifest;
  const bundleResponse = await fetch(`${base}${manifest.bundle}`, { cache: "no-cache" });
  if (!bundleResponse.ok) throw new BundleError(`bundle: HTTP ${bundleResponse.status}`);
  const bytes = new Uint8Array(await bundleResponse.arrayBuffer());
  const bundle = await verifyBundle(manifest, bytes);
  return { bundle, manifest, digest: manifest.content_digest };
}
