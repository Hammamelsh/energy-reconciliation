import type { Household } from "./bundle";

export type Counts = { lower: number; higher: number; equal: number };

/**
 * Compare a candidate flat price with each household's break-even price. The break-even
 * prices were computed exactly in Python; this is a comparison of two numbers per household,
 * not a recomputation of any charge.
 */
export function countAt(households: Household[], pricePence: number): Counts {
  const out: Counts = { lower: 0, higher: 0, equal: 0 };
  for (const h of households) {
    const even = h.breakeven_flat_price.display;
    if (even === null) out.equal += 1;
    else if (even < pricePence) out.lower += 1;
    else if (even > pricePence) out.higher += 1;
    else out.equal += 1;
  }
  return out;
}

