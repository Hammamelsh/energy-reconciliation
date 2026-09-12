/** What a one-finger drag on the 3D canvas means, decided once per gesture from its first
 * clear movement. A mainly sideways drag turns the terrain; a mainly vertical one is left to
 * the browser, which scrolls the page, because the canvas declares `touch-action: pan-y`.
 * Movements shorter than the slop stay undecided, so a tap still selects a cell. */
export type TouchIntent = "undecided" | "turn" | "scroll";

export const TOUCH_SLOP = 8;

export function touchIntent(dx: number, dy: number, slop = TOUCH_SLOP): TouchIntent {
  if (Math.hypot(dx, dy) < slop) return "undecided";
  return Math.abs(dx) > Math.abs(dy) ? "turn" : "scroll";
}
