/** One palette for the page and every chart. Ink base, volt for "dynamic lower" and
 * interaction, ember for "higher" and the High band, current blue for the Low band. */
export const INK = "#0b0e14";
export const SURFACE = "#131824";
export const LINE = "#262e40";
export const GRID = "#1a2130";
export const TEXT = "#eef2f7";
export const MUTED = "#9aa7bd";
export const DIM = "#8b96ab";
export const VOLT = "#c6f43a";
export const VOLT_DEEP = "#8fbf1f";
export const EMBER = "#ff8a3d";
export const EMBER_SOFT = "#ffb27a";
export const CURRENT = "#4c8bf5";
export const NEUTRAL = "#8a94a8";

export const OUTCOME: Record<"lower" | "higher" | "equal", string> = {
  lower: VOLT,
  higher: EMBER,
  equal: NEUTRAL,
};
export const BAND: Record<string, string> = { Low: CURRENT, Normal: VOLT_DEEP, High: EMBER };
