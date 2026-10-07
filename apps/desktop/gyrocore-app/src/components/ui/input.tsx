import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-8 w-full min-w-0 rounded-lg border border-[var(--gc-border-default)] bg-[var(--gc-bg-inset)] px-2.5 py-1 text-base text-[var(--gc-text-primary)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.12)] transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-[var(--gc-text-primary)] placeholder:text-[var(--gc-text-tertiary)] focus-visible:border-[var(--gc-accent-border)] focus-visible:ring-2 focus-visible:ring-[var(--gc-accent)]/20 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-[var(--gc-bg-surface-1)] disabled:text-[var(--gc-text-tertiary)] disabled:opacity-60 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 md:text-sm",
        className
      )}
      {...props}
    />
  )
}

export { Input }
