import * as React from "react"

import { cn } from "@/lib/utils"

export type WizardCardShellOptions = {
  selected?: boolean
  highlighted?: boolean
  disabled?: boolean
  /** When false, no hover styles (read-only banners). */
  enableHover?: boolean
  /** Default min height for wizard grid cells; set "none" for compact panels. */
  minHeight?: "grid" | "none"
  /** Visual variants for upload / success file row. */
  appearance?: "default" | "dashed" | "success"
  className?: string
}

const BASE =
  "relative z-0 box-border w-full max-w-full flex flex-col rounded-2xl border border-slate-600/22 bg-gradient-to-b from-[#0e1526] to-[#0c1220] p-5 text-left shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)] transition-all duration-200"

const HOVER =
  "hover:border-cyan-500/30 hover:bg-[#101b2e] hover:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05),0_2px_8px_rgba(0,0,0,0.25)]"

const SELECTED =
  "border-cyan-500/50 bg-[#0f1d34] shadow-[inset_0_1px_0_0_rgba(34,211,238,0.06),0_0_0_1px_rgba(34,211,238,0.20)]"

const HIGHLIGHT =
  "shadow-[0_0_16px_rgba(34,211,238,0.09)]"

const DISABLED = "opacity-50 cursor-not-allowed pointer-events-none"

const APPEARANCE: Record<NonNullable<WizardCardShellOptions["appearance"]>, string> = {
  default: "",
  dashed:
    "border-2 border-dashed border-slate-600/40 bg-[#0a1020]/50 hover:border-slate-500/55 hover:bg-[#0c1322]/60",
  success:
    "border border-green-500/35 bg-green-500/6 hover:border-green-500/45 hover:bg-green-500/8",
}

export function wizardCardShellClasses({
  selected = false,
  highlighted = false,
  disabled = false,
  enableHover = true,
  minHeight = "grid",
  appearance = "default",
  className,
}: WizardCardShellOptions) {
  return cn(
    BASE,
    minHeight === "grid" && "min-h-[128px]",
    appearance !== "default" && APPEARANCE[appearance],
    appearance === "default" &&
      enableHover &&
      !disabled &&
      HOVER,
    appearance === "default" && selected && SELECTED,
    highlighted && HIGHLIGHT,
    disabled && DISABLED,
    className,
  )
}

export type WizardCardProps = Omit<
  React.ComponentPropsWithoutRef<"div">,
  "onClick" | "title"
> &
  Omit<WizardCardShellOptions, "enableHover"> & {
    as?: "div" | "button" | "section"
    onClick?: () => void
    /** When false, disables hover styling (informational surfaces). */
    enableHover?: boolean
    /** Optional heading row (e.g. style recommendation). */
    title?: React.ReactNode
    /** Small pill, e.g. “AI Recommended”. */
    badge?: React.ReactNode
    children?: React.ReactNode
  }

/**
 * GyroCore design-system surface for wizard grids, hardware chips, and panels.
 * (Shadcn layout `Card` lives in `card.tsx` — import from `@/components/ui/card`.)
 */
export function WizardCard({
  as = "div",
  selected = false,
  highlighted = false,
  disabled = false,
  enableHover: enableHoverProp,
  minHeight = "grid",
  appearance = "default",
  className,
  onClick,
  title,
  badge,
  children,
  ...rest
}: WizardCardProps) {
  const enableHover =
    enableHoverProp !== undefined
      ? enableHoverProp
      : Boolean(onClick) && !disabled

  const shell = cn(
    wizardCardShellClasses({
      selected,
      highlighted,
      disabled,
      enableHover,
      minHeight,
      appearance,
    }),
    Boolean(onClick) && !disabled && "cursor-pointer",
    className,
  )

  const body = (
    <>
      {title ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-base font-semibold tracking-tight text-zinc-100">
            {title}
          </span>
          {badge ? (
            <span className="inline-flex shrink-0 rounded-md border border-cyan-500/25 bg-cyan-500/10 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-cyan-300">
              {badge}
            </span>
          ) : null}
        </div>
      ) : badge ? (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="inline-flex shrink-0 rounded-md border border-cyan-500/25 bg-cyan-500/10 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-cyan-300">
            {badge}
          </span>
        </div>
      ) : null}
      {children}
    </>
  )

  if (as === "button") {
    return (
      <button
        type="button"
        disabled={disabled}
        className={shell}
        onClick={disabled ? undefined : onClick}
        {...(rest as React.ComponentPropsWithoutRef<"button">)}
      >
        {body}
      </button>
    )
  }

  if (as === "section") {
    return (
      <section className={shell} {...rest}>
        {body}
      </section>
    )
  }

  return (
    <div
      role={onClick && !disabled ? "button" : undefined}
      tabIndex={onClick && !disabled ? 0 : undefined}
      className={shell}
      onClick={disabled ? undefined : onClick}
      onKeyDown={
        onClick && !disabled
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault()
                onClick()
              }
            }
          : undefined
      }
      {...rest}
    >
      {body}
    </div>
  )
}

/** Design-system card (same as {@link WizardCard}); import from `@/components/ui/WizardCard`. */
export { WizardCard as Card }
