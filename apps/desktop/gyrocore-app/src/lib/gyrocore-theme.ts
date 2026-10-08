/**
 * GyroCore desktop recipes built on the premium-theme tokens (tables, key/value
 * rows, data chips). Extends — does not replace — premium-theme.ts.
 */
import { cn } from "@/lib/utils";

export const dataTable = "w-full border-collapse text-sm";

export const dataTableHead = cn(
  "border-b border-[var(--gc-border-default)] px-3 py-2 text-left",
  "text-[11px] font-medium uppercase tracking-wider text-[var(--gc-text-tertiary)]",
);

export const dataTableCell = cn(
  "border-b border-[var(--gc-border-subtle)] px-3 py-2 align-top text-[var(--gc-text-primary)]",
);

export const dataTableNum = cn(dataTableCell, "text-right font-mono tabular-nums");

export const dataTableRow = "transition-colors hover:bg-white/[0.02] last:[&>td]:border-b-0";

export const kvGrid = "grid grid-cols-[minmax(110px,auto)_1fr] items-baseline gap-x-4 gap-y-2.5 text-sm";

export const kvKey = "text-xs font-medium text-[var(--gc-text-tertiary)]";

export const kvValue = "min-w-0 break-words text-[var(--gc-text-primary)]";

export const monoValue = "font-mono text-[13px] text-[var(--gc-text-primary)] [overflow-wrap:anywhere]";

export const reasonChip = cn(
  "inline-flex max-w-full items-center rounded-md border border-[var(--gc-border-default)]",
  "bg-[var(--gc-bg-inset)] px-2 py-1 font-mono text-[12px] leading-tight text-[var(--gc-text-secondary)] [overflow-wrap:anywhere]",
);

export const pageStack = "flex flex-col gap-5";

export const cardTitle = "text-sm font-semibold tracking-tight text-[var(--gc-text-heading)]";
