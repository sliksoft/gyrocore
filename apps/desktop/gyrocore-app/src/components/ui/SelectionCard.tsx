import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export type SelectionCardProps = {
  selected?: boolean
  highlighted?: boolean
  disabled?: boolean
  onClick?: () => void
  /** `info`: compact non-grid copy (top info blocks). `default`: selectable grid tiles. */
  variant?: "default" | "info"
  /** Shorter grid tiles (e.g. hardware motor temperature). */
  compact?: boolean
  children: ReactNode
}

export function SelectionCard({
  selected = false,
  highlighted = false,
  disabled = false,
  onClick,
  variant = "default",
  compact = false,
  children,
}: SelectionCardProps) {
  const interactive = Boolean(onClick) && !disabled
  const infoLayout = variant === "info"

  const shadowClass = infoLayout
    ? highlighted
      ? "shadow-[0_0_14px_rgba(34,211,238,0.08)]"
      : null
    : selected && highlighted
      ? "shadow-[0_0_0_1px_rgba(34,211,238,0.25),0_0_14px_rgba(34,211,238,0.08)]"
      : selected
        ? "shadow-[0_0_0_1px_rgba(34,211,238,0.25)]"
        : highlighted
          ? "shadow-[0_0_14px_rgba(34,211,238,0.08)]"
          : null

  return (
    <div
      className={cn(
        "relative z-0 box-border flex w-full max-w-full flex-col overflow-hidden rounded-2xl border shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)] transition-all duration-200",
        infoLayout
          ? "min-h-0 justify-start border-slate-600/20 bg-gradient-to-b from-[#0c1324] to-[#0a1020] p-5"
          : cn(
              "justify-start border-slate-600/22 bg-gradient-to-b from-[#0e1526] to-[#0c1220]",
              compact ? "min-h-[80px] p-4" : "min-h-[128px] p-5",
            ),
        interactive && "cursor-pointer",
        !interactive && !disabled && "cursor-default",
        disabled && "cursor-not-allowed opacity-50",
        !infoLayout &&
          !selected &&
          !disabled &&
          interactive &&
          "hover:border-cyan-500/30 hover:bg-[#101b2e] hover:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05),0_2px_8px_rgba(0,0,0,0.25)]",
        !infoLayout && selected && "border-cyan-500/50 bg-[#0f1d34] shadow-[inset_0_1px_0_0_rgba(34,211,238,0.06),0_0_0_1px_rgba(34,211,238,0.20)]",
        shadowClass,
      )}
      onClick={disabled ? undefined : onClick}
    >
      {children}
    </div>
  )
}
