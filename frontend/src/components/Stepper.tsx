const STEPS = ["Upload", "Confirm", "Process", "Results"] as const;
export type Step = (typeof STEPS)[number];

export function Stepper({ current }: { current: Step }) {
  const currentIdx = STEPS.indexOf(current);
  return (
    <div className="mb-3 flex items-center gap-2 text-[13px]">
      {STEPS.map((s, i) => (
        <span key={s} className="flex items-center gap-2">
          {i > 0 && <span className="text-line">›</span>}
          <span className={i === currentIdx ? "font-semibold text-ink" : i < currentIdx ? "text-body" : "text-mut"}>
            {i + 1} {s}
          </span>
        </span>
      ))}
    </div>
  );
}
