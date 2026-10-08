// Standalone "R" mark derived from src/assets/redline-dynamics.png
// (crop x≈10–182, #01121f field converted to transparency).
import redlineMark from "@/assets/redline-mark.png";

const MARK_ASPECT = 168 / 107;

function RedlineMark({ height }: { height: number }) {
  return (
    <img
      src={redlineMark}
      alt=""
      aria-hidden
      draggable={false}
      className="block shrink-0 select-none"
      style={{ height, width: Math.round(height * MARK_ASPECT) }}
    />
  );
}

export function RedlineBrand({ collapsed = false }: { collapsed?: boolean }) {
  if (collapsed) {
    return (
      <div className="grid place-items-center" title="Built by Redline Dynamics" data-testid="redline-logo">
        <RedlineMark height={28} />
        <span className="sr-only">Built by Redline Dynamics</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="redline-brand">
      <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--gc-text-tertiary)]">Built by</span>
      <div className="flex items-center gap-3" data-testid="redline-logo">
        <RedlineMark height={46} />
        <span className="whitespace-nowrap text-[15px] font-semibold tracking-tight text-[var(--gc-text-heading)]">
          Redline Dynamics
        </span>
      </div>
    </div>
  );
}
