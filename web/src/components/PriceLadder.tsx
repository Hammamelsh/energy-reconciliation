import type { Bundle } from "../lib/bundle";
import { useMediaQuery } from "../hooks";
import { BAND, CURRENT, EMBER, INK, LINE, MUTED, NEUTRAL, SLATE, SURFACE, TEXT } from "../lib/palette";

type Mark = { key: string; p: number; label: string; tone: string; tier: "up" | "up2" | "down" | "down2"; anchor: "start" | "middle" | "end" };

/** The four prices on one scale, plus the pooled break-even. A picture of "17 to 1". */
export function PriceLadder({ bundle }: { bundle: Bundle }) {
  const compact = useMediaQuery("(max-width: 700px)");
  const prices = bundle.prices;
  const byBand = (band: string) => prices.find((p) => p.band === band);
  const low = Number(byBand("Low")?.pence_per_kwh ?? 0);
  const normal = Number(byBand("Normal")?.pence_per_kwh ?? 0);
  const high = Number(byBand("High")?.pence_per_kwh ?? 0);
  const flat = Number(bundle.comparison.flat_price.pence_per_kwh);
  const even = bundle.comparison.breakeven_flat_price.display ?? 0;
  const max = Math.ceil(Math.max(high, flat) / 10) * 10;
  const ratio = low > 0 ? (high / low).toFixed(0) : "n/a";
  const marks: Mark[] = [
    { key: "low", p: low, label: `Low ${low.toFixed(2)}p`, tone: CURRENT, tier: "down", anchor: "start" },
    // Ends at its own marker so the break-even guide line, a few pixels to the right, never crosses it.
    { key: "normal", p: normal, label: `Normal ${normal.toFixed(2)}p`, tone: SLATE, tier: "up", anchor: "end" },
    { key: "even", p: even, label: `Break-even ${even.toFixed(3)}p`, tone: NEUTRAL, tier: "up2", anchor: "middle" },
    { key: "flat", p: flat, label: `Flat ${flat.toFixed(3)}p`, tone: EMBER, tier: "down2", anchor: "middle" },
    { key: "high", p: high, label: `High ${high.toFixed(2)}p`, tone: EMBER, tier: "up", anchor: "end" },
  ];
  const intro = (
    <>
      <h2>Four prices on one scale</h2>
      <p>
        The dynamic tariff's High band cost about {ratio}× its Low band. The pooled break-even is the flat price
        at which this recorded consumption would have cost exactly what it did under the dynamic tariff. The
        documented flat price sits {flat > even ? "above" : "below"} it, and that gap is the{" "}
        {bundle.comparison.pct_of_flat.display?.toFixed(1) ?? "n/a"}%.
      </p>
    </>
  );
  if (compact) {
    return (
      <div className="ladder">
        {intro}
        <ul className="ladder-list" aria-label="Prices in pence per kWh">
          {[...marks].sort((a, b) => a.p - b.p).map((m) => (
            <li key={m.key}>
              <span className="lbl">{m.label}</span>
              <span className="track">
                <span className="fill" style={{ width: `${(m.p / max) * 100}%`, background: m.tone }} />
              </span>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  const W = 900;
  const LINE_Y = 62;
  const x = (p: number) => 46 + (p / max) * (W - 92);
  const y = (tier: Mark["tier"]) => (tier === "up" ? LINE_Y - 22 : tier === "up2" ? LINE_Y - 44 : tier === "down" ? LINE_Y + 30 : LINE_Y + 50);
  return (
    <div className="ladder">
      {intro}
      <svg
        viewBox={`0 0 ${W} 124`}
        role="img"
        aria-label={`Price scale from 0 to ${max} pence per kWh: Low ${low}p, Normal ${normal}p, break-even ${even}p, flat ${flat}p, High ${high}p.`}
      >
        <defs>
          <linearGradient id="g" x1="0" x2="1">
            <stop offset="0" stopColor={BAND.Low} />
            <stop offset="0.25" stopColor={BAND.Normal} />
            <stop offset="1" stopColor={BAND.High} />
          </linearGradient>
        </defs>
        <line x1={46} x2={W - 46} y1={LINE_Y} y2={LINE_Y} stroke={LINE} strokeWidth={6} strokeLinecap="round" />
        <line x1={x(low)} x2={x(high)} y1={LINE_Y} y2={LINE_Y} stroke="url(#g)" strokeWidth={6} strokeLinecap="round" />
        <line className="current" x1={x(low)} x2={x(high)} y1={LINE_Y} y2={LINE_Y} stroke={TEXT} strokeOpacity={0.55} strokeWidth={2} strokeLinecap="round" strokeDasharray="6 34" />
        {marks.map((m) => {
          const ly = y(m.tier);
          const up = m.tier.startsWith("up");
          return (
            <g key={m.key}>
              <line x1={x(m.p)} x2={x(m.p)} y1={up ? ly + 4 : ly - 12} y2={LINE_Y} stroke={m.tone} strokeWidth={1.5} strokeDasharray={m.key === "even" ? "3 3" : undefined} />
              <circle cx={x(m.p)} cy={LINE_Y} r={m.key === "even" ? 5 : 6.5} fill={m.key === "even" ? INK : m.tone} stroke={m.key === "even" ? MUTED : INK} strokeWidth={2} />
            </g>
          );
        })}
        {/* Labels last, with a halo in the card colour: a taller mark's guide line can pass
            through a neighbour's label (break-even 13.661p over Normal 11.76p), and the text
            must stay legible over it. */}
        {marks.map((m) => (
          <text
            key={`${m.key}-label`}
            x={x(m.p)}
            y={y(m.tier)}
            textAnchor={m.anchor}
            fontSize={13}
            fill={TEXT}
            stroke={SURFACE}
            strokeWidth={4}
            strokeLinejoin="round"
            paintOrder="stroke"
            fontWeight={m.key === "flat" || m.key === "even" ? 700 : 500}
          >
            {m.label}
          </text>
        ))}
        <text x={46} y={122} fontSize={11} fill={MUTED}>0p</text>
        <text x={W - 46} y={122} fontSize={11} fill={MUTED} textAnchor="end">{max}p per kWh</text>
      </svg>
    </div>
  );
}
