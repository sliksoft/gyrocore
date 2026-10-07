import type { ReactNode } from "react";
import { codePanel } from "@/lib/premium-theme";
import { kvGrid, kvKey, kvValue, monoValue, reasonChip } from "@/lib/gyrocore-theme";
import { cn } from "@/lib/utils";

export type KeyValueRow = { label: string; value: ReactNode; mono?: boolean };

/** Label/value grid for workspace facts — values rendered exactly as provided. */
export function KeyValue({ rows, className }: { rows: KeyValueRow[]; className?: string }) {
  return (
    <dl className={cn(kvGrid, className)}>
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className={kvKey}>{row.label}</dt>
          <dd className={cn("m-0", row.mono ? monoValue : kvValue)}>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Read-only JSON/code well; content is never truncated, only scrolled. */
export function CodeBlock({ value, maxHeight = 280, className }: { value: unknown; maxHeight?: number; className?: string }) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
  return (
    <pre
      className={cn(codePanel, "m-0 overflow-auto whitespace-pre-wrap [overflow-wrap:anywhere]", className)}
      style={{ maxHeight }}
    >
      {text}
    </pre>
  );
}

/** Core reason / rule identifiers as chips (verbatim strings). */
export function ReasonList({ items, className }: { items: string[]; className?: string }) {
  if (!items.length) return null;
  return (
    <ul className={cn("m-0 flex list-none flex-wrap gap-1.5 p-0", className)}>
      {items.map((item, i) => (
        <li key={`${item}-${i}`} className={reasonChip}>
          {item}
        </li>
      ))}
    </ul>
  );
}
