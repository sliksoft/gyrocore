import { GitCompareArrows } from "lucide-react";
import type { ComparePayload } from "@/bridge/types";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricTile } from "@/components/ui/MetricTile";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { dataTable, dataTableCell, dataTableHead, dataTableNum, dataTableRow, pageStack } from "@/lib/gyrocore-theme";
import { cn } from "@/lib/utils";

const AXES = ["roll", "pitch", "yaw"] as const;
const COMPS = [
  ["p", "P"],
  ["i", "I"],
  ["d", "D"],
  ["d_max", "D-max"],
  ["ff", "FF"],
] as const;

type Row = { key: string; label: string; mono: boolean; a: number | null; b: number | null };

function deltaClass(delta: number | null) {
  if (delta == null || delta === 0) return "text-[var(--gc-text-tertiary)]";
  return delta > 0 ? "text-[#6ee7b7]" : "text-[#fca5a5]";
}

export function CompareTable({ compare, unavailableReason }: { compare: ComparePayload | null; unavailableReason?: string }) {
  if (!compare) {
    return (
      <div className={pageStack}>
        <SurfaceCard>
          <SectionHeader title="Compare" actions={<StatusBadge value="NOT AVAILABLE" />} />
          <EmptyState
            icon={<GitCompareArrows className="h-5 w-5" aria-hidden />}
            title="No compare data available."
            description={unavailableReason ?? "Compare needs a current tune baseline and a final safe target from the safety pipeline."}
            data-testid="compare-unavailable"
          />
        </SurfaceCard>
      </div>
    );
  }
  const cur = compare.current;
  const fin = compare.final_safe;
  const rows: Row[] = [
    ...AXES.flatMap((axis) =>
      COMPS.map(([key, label]) => ({
        key: `${axis}.${key}`,
        label: `${axis} ${label}`,
        mono: false,
        a: cur.axes?.[axis]?.[key] ?? null,
        b: fin.axes?.[axis]?.[key] ?? null,
      })),
    ),
    ...Object.keys(cur.filters || {}).map((key) => ({
      key,
      label: key,
      mono: true,
      a: cur.filters?.[key] ?? null,
      b: fin.filters?.[key] ?? null,
    })),
  ];
  const withTarget = rows.filter((r) => r.b != null).length;
  const changed = rows.filter((r) => r.a != null && r.b != null && r.a !== r.b).length;

  return (
    <div className={pageStack}>
      <div className="grid grid-cols-3 gap-4">
        <MetricTile label="Settings compared" value={rows.length} />
        <MetricTile label="With final safe value" value={withTarget} />
        <MetricTile label="Changed" value={changed} />
      </div>
      <SurfaceCard>
        <SectionHeader title="Current vs Final Safe Target" subtitle="Values come from the Core safety pipeline; Δ = final safe − current." />
        <div className="overflow-x-auto rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)]/60">
          <table className={dataTable}>
            <thead>
              <tr>
                <th className={dataTableHead}>Setting</th>
                <th className={cn(dataTableHead, "text-right")}>Current</th>
                <th className={cn(dataTableHead, "text-right")}>Final safe</th>
                <th className={cn(dataTableHead, "text-right")}>Δ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const delta = r.a != null && r.b != null ? r.b - r.a : null;
                return (
                  <tr key={r.key} className={dataTableRow}>
                    <td className={cn(dataTableCell, r.mono ? "font-mono text-xs" : "capitalize")}>{r.label}</td>
                    <td className={dataTableNum}>{r.a ?? "—"}</td>
                    <td className={dataTableNum}>{r.b ?? "—"}</td>
                    <td className={cn(dataTableNum, deltaClass(delta))}>
                      {delta == null ? "—" : delta > 0 ? `+${delta}` : `${delta}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </SurfaceCard>
    </div>
  );
}
