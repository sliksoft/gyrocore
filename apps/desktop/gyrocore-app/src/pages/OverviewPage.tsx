import { FlaskConical, ListChecks } from "lucide-react";
import type { WorkspacePayload } from "@/bridge/types";
import { KeyValue, ReasonList } from "@/components/KeyValue";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricTile } from "@/components/ui/MetricTile";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StatusAlert } from "@/components/ui/StatusAlert";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { TopInfoCard } from "@/components/ui/TopInfoCard";
import { chirpDisplay } from "@/lib/chirpStatus";
import { pageStack } from "@/lib/gyrocore-theme";

export function OverviewPage({ ws }: { ws: WorkspacePayload }) {
  const o = ws.overview || {};
  const issues = Array.isArray(o.detected_issues) ? (o.detected_issues as unknown[]).map(String) : [];
  return (
    <div className={pageStack}>
      {ws.demo && (
        <StatusAlert tone="warning" icon={<FlaskConical className="h-4 w-4 text-[var(--gc-status-warn)]" />} title="Demo workspace">
          {ws.demo_label}
        </StatusAlert>
      )}

      <TopInfoCard
        className="mb-0"
        title={ws.demo ? `Demo scenario · ${ws.scenario}` : `Workspace · ${ws.scenario}`}
        description={o.message ? String(o.message) : "Core results for the loaded log. Each stage is shown with its own Core status."}
        badge={<StatusBadge value={String(o.final_safety || "NOT AVAILABLE")} />}
      />

      <div className="grid grid-cols-3 gap-4">
        <SurfaceCard>
          <SectionHeader title="Craft / firmware" />
          <KeyValue
            rows={[
              { label: "Craft", value: String(o.craft || "—") },
              { label: "Target", value: String(o.target || "—") },
              { label: "Betaflight", value: String(o.betaflight_version || "—"), mono: true },
              { label: "PID profile", value: String(o.pid_profile ?? "—"), mono: true },
            ]}
          />
        </SurfaceCard>
        <SurfaceCard>
          <SectionHeader title="Log" />
          <div className="mb-4 grid grid-cols-2 gap-3">
            <MetricTile label="Duration" value={o.log_duration_s != null ? String(o.log_duration_s) : "—"} unit={o.log_duration_s != null ? "s" : undefined} />
            <MetricTile label="Sample rate" value={o.sample_rate_hz != null ? String(o.sample_rate_hz) : "—"} unit={o.sample_rate_hz != null ? "Hz" : undefined} className="min-w-0 [&>div>span:first-child]:truncate" />
          </div>
          <KeyValue
            rows={[
              { label: "CHIRP", value: <StatusBadge value={chirpDisplay(ws.chirp).badge} /> },
              { label: "Tune rec.", value: String(o.tune_recommendation || "—"), mono: true },
            ]}
          />
        </SurfaceCard>
        <SurfaceCard>
          <SectionHeader title="Safety / CLI" />
          <KeyValue
            rows={[
              { label: "Mechanical", value: <StatusBadge value={String(o.mechanical_safety || "NOT AVAILABLE")} /> },
              { label: "Final safety", value: <StatusBadge value={String(o.final_safety || "NOT AVAILABLE")} /> },
              { label: "CLI auth", value: <StatusBadge value={String(o.cli_authorization || "NOT AVAILABLE")} /> },
            ]}
          />
        </SurfaceCard>
      </div>

      <SurfaceCard>
        <SectionHeader title="Detected issues" />
        {issues.length ? (
          <ReasonList items={issues} />
        ) : (
          <EmptyState icon={<ListChecks className="h-5 w-5" aria-hidden />} title="None reported." className="py-8" />
        )}
      </SurfaceCard>
    </div>
  );
}
