import { useEffect, useState } from "react";
import { prefersReducedMotion } from "../lib/url";

export type TourStep = { id: string; title: string; text: string };

/** A guided walk through the page: six stops, one sentence each, keyboard-operable.
 * It scrolls; it never changes data. Escape or "Done" closes it. */
export function Tour({ steps, active, onClose }: { steps: TourStep[]; active: boolean; onClose: () => void }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!active) return;
    const el = document.getElementById(steps[i].id);
    el?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  }, [active, i, steps]);
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && i < steps.length - 1) setI(i + 1);
      if (e.key === "ArrowLeft" && i > 0) setI(i - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, i, steps.length, onClose]);
  if (!active) return null;
  const step = steps[i];
  const last = i === steps.length - 1;
  return (
    <div className="tour" role="dialog" aria-label="Guided walk-through" aria-live="polite">
      <div className="step-label">
        Step {i + 1} of {steps.length} · {step.title}
      </div>
      <p>{step.text}</p>
      <div className="row">
        <button type="button" className="link" onClick={onClose}>
          Close
        </button>
        <button type="button" onClick={() => setI(Math.max(0, i - 1))} disabled={i === 0}>
          Back
        </button>
        <button type="button" className="primary" onClick={() => (last ? onClose() : setI(i + 1))} autoFocus>
          {last ? "Done" : "Next"}
        </button>
      </div>
    </div>
  );
}
