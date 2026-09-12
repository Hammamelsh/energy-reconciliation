/** Where a two-line annotation goes so it stays inside the canvas. Right of the point when
 * there is room, left of it otherwise; on a canvas too narrow for either (a phone), pinned
 * to a top corner with the leader line drawn to it. The corner is the one away from the
 * scale bar (`preferRight`), and `lines` says how many lines the caller will draw there, so
 * the leader meets the block below them. Pure layout: no value is changed. */
export function placeLabel(
  x: number,
  y: number,
  longest: string,
  w: number,
  h: number,
  opts: { preferRight?: boolean; lines?: 1 | 3 } = {},
) {
  const est = longest.length * 6.6 + 12;
  const ty = Math.max(18, Math.min(h - 8, y - 38));
  if (x + 30 + est <= w - 4) return { tx: x + 30, ty, anchor: "start" as const, lx: x + 26, ly: ty + 4, pinned: false };
  if (x - 30 - est >= 4) return { tx: x - 30, ty, anchor: "end" as const, lx: x - 26, ly: ty + 4, pinned: false };
  // pinned to the top edge: on a portrait canvas the top corners are clear of the terrain
  const top = 18;
  const reach = Math.min(est, w - 16) / 3;
  const ly = top + (opts.lines === 1 ? 4 : 34);
  if (opts.preferRight) return { tx: w - 8, ty: top, anchor: "end" as const, lx: w - 8 - reach, ly, pinned: true };
  return { tx: 8, ty: top, anchor: "start" as const, lx: 8 + reach, ly, pinned: true };
}
