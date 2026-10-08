import { StatusBadge as Badge } from "@/components/ui/StatusBadge";
import { statusLabel, statusTone } from "@/lib/status";

/** Core status value rendered verbatim with the design-system tone for its semantics. */
export function StatusBadge({ value, className }: { value?: string | null; className?: string }) {
  const label = statusLabel(value);
  const tone = statusTone(label);
  return (
    <Badge tone={tone} className={className} data-tone={tone}>
      <span
        aria-hidden
        className={
          tone === "success"
            ? "h-1.5 w-1.5 rounded-full bg-[var(--gc-status-good)]"
            : tone === "warning"
              ? "h-1.5 w-1.5 rounded-full bg-[var(--gc-status-warn)]"
              : tone === "danger"
                ? "h-1.5 w-1.5 rounded-full bg-[var(--gc-status-error)]"
                : tone === "info"
                  ? "h-1.5 w-1.5 rounded-full bg-[var(--gc-accent)]"
                  : "h-1.5 w-1.5 rounded-full bg-[var(--gc-text-tertiary)]"
        }
      />
      {label}
    </Badge>
  );
}
