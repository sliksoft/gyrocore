import { GitMerge, SlidersHorizontal } from "lucide-react";
import type { StageValues, WorkspacePayload } from "@/bridge/types";
import { CodeBlock, KeyValue, ReasonList } from "@/components/KeyValue";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StatusAlert } from "@/components/ui/StatusAlert";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { cardTitle, dataTable, dataTableCell, dataTableHead, dataTableNum, dataTableRow, pageStack } from "@/lib/gyrocore-theme";
import { cn } from "@/lib/utils";

function StageTable({ title, stage, eyebrow }: { title: string; stage?: StageValues | null; eyebrow?: string }) {
  const header = (
    <div className="mb-3 flex flex-col gap-1">
      {eyebrow && <MicroLabel>{eyebrow}</MicroLabel>}
      <h3 className={cn(cardTitle, "m-0 font-mono tracking-wide")}>{title}</h3>
    </div>
  );
  if (!stage || !stage.axes) {
    return (
      <SurfaceCard className="min-w-0">
        {header}
        <EmptyState title="Not available." className="py-8" />
      </SurfaceCard>
    );
  }
  const filters = stage.filters ? Object.entries(stage.filters) : [];
  return (
    <SurfaceCard className="min-w-0">
      {header}
      <div className="overflow-x-auto rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)]/60">
        <table className={dataTable}>
          <thead>
            <tr>
              <th className={dataTableHead}>Axis</th>
              <th className={cn(dataTableHead, "text-right")}>P</th>
              <th className={cn(dataTableHead, "text-right")}>I</th>
              <th className={cn(dataTableHead, "text-right")}>D</th>
              <th className={cn(dataTableHead, "text-right")}>D-max</th>
              <th className={cn(dataTableHead, "text-right")}>FF</th>
            </tr>
          </thead>
          <tbody>
            {["roll", "pitch", "yaw"].map((axis) => {
              const a = stage.axes?.[axis] || {};
              return (
                <tr key={axis} className={dataTableRow}>
                  <td className={cn(dataTableCell, "capitalize text-[var(--gc-text-secondary)]")}>{axis}</td>
                  <td className={dataTableNum}>{a.p ?? "—"}</td>
                  <td className={dataTableNum}>{a.i ?? "—"}</td>
                  <td className={dataTableNum}>{a.d ?? "—"}</td>
                  <td className={dataTableNum}>{a.d_max ?? "—"}</td>
                  <td className={dataTableNum}>{a.ff ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {filters.length > 0 && (
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)]/60">
          <table className={dataTable}>
            <thead>
              <tr>
                <th className={dataTableHead}>Filter</th>
                <th className={cn(dataTableHead, "text-right")}>Value</th>
              </tr>
            </thead>
            <tbody>
              {filters.map(([key, value]) => (
                <tr key={key} className={dataTableRow}>
                  <td className={cn(dataTableCell, "font-mono text-xs text-[var(--gc-text-secondary)]")}>{key}</td>
                  <td className={dataTableNum}>{value ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SurfaceCard>
  );
}

export function TunePage({ ws }: { ws: WorkspacePayload }) {
  const t = ws.tune;
  if (!t) {
    return (
      <SurfaceCard>
        <SectionHeader title="Tune" />
        <EmptyState
          icon={<SlidersHorizontal className="h-5 w-5" aria-hidden />}
          title="Tune stages unavailable (missing baseline or blocked upstream)."
        />
      </SurfaceCard>
    );
  }
  const mergeReview = String(t.merge_status || "").includes("review") || (t.review_reasons || []).length > 0;
  const clampIds = t.wu10_safe_target?.clamp_ids || [];

  return (
    <div className={pageStack}>
      {mergeReview && (
        <StatusAlert
          tone="warning"
          icon={<GitMerge className="h-4 w-4 text-[var(--gc-status-warn)]" />}
          title="Merge requires review"
          data-testid="merge-review"
        >
          MERGE REQUIRES REVIEW — {t.review_reasons?.join("; ") || t.merge_status}
        </StatusAlert>
      )}
      <SurfaceCard>
        <SectionHeader
          title="Stages"
          subtitle="Recommendation and safe output are shown separately. Core owns the numbers."
          actions={<StatusBadge value={ws.overview?.final_safety as string} />}
        />
        <KeyValue
          rows={[
            { label: "Merge status", value: <StatusBadge value={t.merge_status} /> },
            { label: "Merged sliders", value: <CodeBlock value={t.merged_sliders || {}} maxHeight={160} /> },
            { label: "Per-axis WU8", value: <CodeBlock value={t.per_axis_recommendations || {}} maxHeight={200} /> },
            {
              label: "Clamps",
              value: clampIds.length ? <ReasonList items={clampIds} /> : <span className="font-mono text-[13px]">none</span>,
            },
          ]}
        />
      </SurfaceCard>
      <div className="grid grid-cols-2 gap-4">
        <StageTable title="CURRENT" eyebrow="Baseline" stage={t.current} />
        <StageTable title="WU8 AUTOTUNE (sliders / axes)" eyebrow="Recommendation" stage={null} />
      </div>
      <SurfaceCard>
        <SectionHeader title="WU8 Autotune recommendation (non-actionable)" />
        <CodeBlock value={t.wu8_autotune || {}} maxHeight={320} />
      </SurfaceCard>
      <div className="grid grid-cols-2 gap-4">
        <StageTable title="WU9 ABSOLUTE PROPOSAL" eyebrow="Proposal" stage={t.wu9_absolute_proposal as StageValues} />
        <StageTable title="WU10 SAFE / CLAMPED TARGET" eyebrow="Safe target" stage={t.wu10_safe_target} />
      </div>
    </div>
  );
}
