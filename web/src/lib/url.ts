/** Shareable state lives in the URL: the household in focus and the break-even slider. */

export type UrlState = { household: string | null; flat: number | null };

export function readState(search: string): UrlState {
  const params = new URLSearchParams(search);
  const household = params.get("household");
  const flatRaw = params.get("flat");
  const flat = flatRaw === null ? null : Number(flatRaw);
  return {
    household: household && /^[A-Za-z0-9_-]{1,32}$/.test(household) ? household : null,
    flat: flat !== null && Number.isFinite(flat) && flat >= 0 && flat <= 100 ? flat : null,
  };
}

export function writeState(state: UrlState, current: string): string {
  const params = new URLSearchParams(current);
  if (state.household) params.set("household", state.household);
  else params.delete("household");
  if (state.flat !== null) params.set("flat", state.flat.toFixed(3));
  else params.delete("flat");
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function pushState(state: UrlState): void {
  if (typeof window === "undefined") return;
  const next = writeState(state, window.location.search) + window.location.hash;
  const currentUrl = window.location.search + window.location.hash;
  if (next !== currentUrl) window.history.replaceState(null, "", next || window.location.pathname);
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
