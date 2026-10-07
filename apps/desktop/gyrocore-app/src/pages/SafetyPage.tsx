import { ShieldCheck } from "lucide-react";
import type { WorkspacePayload } from "@/bridge/types";
import { ReasonList } from "@/components/KeyValue";
import { SafetyStage } from "@/components/SafetyStage";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { pageStack } from "@/lib/gyrocore-theme";
import { statusTone } from "@/lib/status";
import { cn } from "@/lib/utils";

const FINAL_RING: Record<string, string> = {
  success: "border-[var(--gc-status-good-border)]",
  warning: "border-[var(--gc-status-warn-border)]",
  danger: "border-[var(--gc-status-error-border)]",
};

export function SafetyPage({ ws }: { ws: WorkspacePayload }) {
  const s = ws.safety;
  if (!s) {
    return (
      <SurfaceCard>
        <SectionHeader title="Safety" />
        <EmptyState icon={<ShieldCheck className="h-5 w-5" aria-hidden />} title="Safety stages unavailable." />
      </SurfaceCard>
    );
  }
  const finalStatus = String(s.final?.status || "");
  const finalReasons = (s.final?.blocked_reasons as string[] | undefined) || [];
  return (
    <div className={pageStack} data-testid="safety-page">
      <SurfaceCard variant="elevated" className={cn(FINAL_RING[statusTone(finalStatus)])}>
        <SectionHeader
          eyebrow="Final verdict"
          title="Final"
          subtitle="Why GyroCore allows or blocks this tune — mechanical → clamps → tuning_output_safety → (WU11 CLI separately)."
          actions={<StatusBadge value={finalStatus} className="px-3 py-1 text-xs" />}
        />
        <ReasonList items={finalReasons} />
      </SurfaceCard>
      <SafetyStage step={1} title="Mechanical Safety" status={String(s.mechanical?.status || "")} body={s.mechanical} />
      <SafetyStage step={2} title="Safe-Tune / Clamps" status={String(s.safe_tune?.status || "")} body={s.safe_tune} />
      <SafetyStage
        step={3}
        title="Tuning Output Safety"
        status={String(s.tuning_output_safety?.status || "")}
        body={s.tuning_output_safety}
      />
    </div>
  );
}
