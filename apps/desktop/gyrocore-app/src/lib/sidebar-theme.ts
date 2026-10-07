/**
 * Sidebar recipes ported from AeroTuner frontend/lib/sidebar-theme.ts.
 * Desktop-only shell: mobile drawer / auth / account variants are not ported.
 */
import { cn } from "@/lib/utils";

export const sidebarShell = cn(
  "relative flex h-screen min-h-0 shrink-0 flex-col overflow-hidden",
  "border-r border-[var(--gc-border-default)]",
  "bg-[var(--gc-bg-surface-1)]/95 backdrop-blur-xl",
  "shadow-[inset_-1px_0_0_0_rgba(255,255,255,0.03)]",
  "transition-[width] duration-200 ease-out",
);

export function sidebarWidthClass(collapsed: boolean) {
  return collapsed ? "w-[68px]" : "w-[248px]";
}

export const sidebarBrandClass = cn(
  "bg-gradient-to-b from-white via-violet-100 to-violet-400 bg-clip-text",
  "text-lg font-semibold tracking-tight text-transparent",
);

export const sidebarNavLinkBase = cn(
  "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[14px] font-medium leading-snug transition",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/35 focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--gc-bg-base)]",
);

export function sidebarNavLinkClass(active: boolean) {
  return cn(
    sidebarNavLinkBase,
    active
      ? "border border-violet-400/40 bg-gradient-to-r from-violet-500/20 to-violet-500/5 text-violet-50 shadow-[0_0_0_1px_rgba(139,92,246,0.18),0_0_20px_-6px_rgba(139,92,246,0.45)]"
      : "border border-transparent text-[var(--gc-text-secondary)] hover:border-violet-400/15 hover:bg-white/[0.04] hover:text-[var(--gc-text-heading)]",
  );
}

export const sidebarWaveDecoration = cn(
  "pointer-events-none absolute inset-x-0 bottom-0 h-32 overflow-hidden",
  "before:absolute before:-bottom-12 before:-left-8 before:h-40 before:w-40 before:rounded-full before:bg-violet-500/15 before:blur-3xl",
  "after:absolute after:-bottom-16 after:left-12 after:h-32 after:w-56 after:rounded-full after:bg-violet-600/10 after:blur-2xl",
);

export const sidebarCollapseToggleBtn = cn(
  "grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/10",
  "text-[var(--gc-text-secondary)] transition hover:border-violet-400/40 hover:text-white",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/35",
);
