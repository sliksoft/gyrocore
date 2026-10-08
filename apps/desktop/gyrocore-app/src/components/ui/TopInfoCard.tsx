import type { ReactNode } from "react"

import { SelectionCard } from "@/components/ui/SelectionCard"
import { cn } from "@/lib/utils"

const badgeSpanClassName =
  "shrink-0 rounded-md border border-cyan-500/25 bg-cyan-500/8 px-2 py-0.5 text-[12px] font-medium text-cyan-300"

export type TopInfoCardProps = {
  title: string
  description: ReactNode
  /** Plain string uses the grid-aligned pill; pass a node for custom markup. */
  badge?: ReactNode
  className?: string
  /** Subtle blue glow (e.g. log-inferred recommendation). */
  highlighted?: boolean
}

/**
 * Non-interactive top-of-step info block; same shell as grid `SelectionCard` (`info` layout).
 */
export function TopInfoCard({
  title,
  description,
  badge,
  className,
  highlighted = false,
}: TopInfoCardProps) {
  return (
    <div className={cn("mb-6 w-full", className)}>
      <SelectionCard variant="info" highlighted={highlighted} selected={false}>
        <div className="flex flex-col gap-1.5 text-left">
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-base font-semibold tracking-tight text-zinc-100">
              {title}
            </h3>
            {badge != null ? (
              typeof badge === "string" ? (
                <span className={badgeSpanClassName}>{badge}</span>
              ) : (
                <div className="shrink-0">{badge}</div>
              )
            ) : null}
          </div>
          <div className="text-sm leading-relaxed text-zinc-400">{description}</div>
        </div>
      </SelectionCard>
    </div>
  )
}
