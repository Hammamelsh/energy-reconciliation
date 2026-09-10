import type { HourBands } from "./bundle";

/**
 * Where the schedule placed its High band, by hour of the timestamp label as written. Counts
 * only: no timezone or interval convention is applied, so these are label hours, not clock time.
 */
export type HighConcentration = {
  /** First and last label hour of the run holding the most High half hours. */
  from: number;
  to: number;
  /** High half hours in that run, and in the whole schedule. */
  slots: number;
  total: number;
  sharePct: number;
  /** Whether the run is one unbroken range of hours. */
  contiguous: boolean;
  /** Whether every label hour holds at least one High half hour. */
  everyHour: boolean;
};

export function highConcentration(hourBands: HourBands): HighConcentration | null {
  const high = hourBands.schedule_slots_by_band_and_hour.High ?? [];
  const total = high.reduce((s, v) => s + v, 0);
  if (total === 0) return null;
  const max = Math.max(...high);
  const hours = high.map((v, i) => (v === max ? i : -1)).filter((i) => i >= 0);
  const from = hours[0];
  const to = hours[hours.length - 1];
  const slots = hours.reduce((s, h) => s + high[h], 0);
  return {
    from,
    to,
    slots,
    total,
    sharePct: Math.round((slots / total) * 1000) / 10,
    contiguous: to - from + 1 === hours.length,
    everyHour: high.every((v) => v > 0),
  };
}

const two = (n: number) => String(n).padStart(2, "0");

/** "17:00 to 22:59": the label-hour range, stated as labels. */
export function labelRange(c: HighConcentration): string {
  return `${two(c.from)}:00 to ${two(c.to)}:59`;
}
