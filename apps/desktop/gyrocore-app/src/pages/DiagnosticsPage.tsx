import type { ReactNode } from "react";
import { Info } from "lucide-react";
import type { WorkspacePayload } from "@/bridge/types";
import { CodeBlock } from "@/components/KeyValue";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StatusAlert } from "@/components/ui/StatusAlert";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { pageStack } from "@/lib/gyrocore-theme";

function Flag({ value }: { value: unknown }) {
  const text = String(value);
  const tone = text === "true" ? "info" : text === "false" || text === "n/a" || text === "none" ? "muted" : "neutral";
  return (
    <StatusBadge tone={tone} className="font-mono">
      {text}
    </StatusBadge>
  );
}

function Line({ children }: { children: ReactNode }) {
  return <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-[var(--gc-text-secondary)]">{children}</p>;
}

export function DiagnosticsPage({ ws }: { ws: WorkspacePayload }) {
  const d = (ws.diagnostics || {}) as Record<string, unknown>;
  const filter = (d.filter_evidence || {}) as Record<string, unknown>;
  const throttle = (d.throttle || {}) as Record<string, unknown>;
  const verification = (d.verification || {}) as Record<string, unknown>;

  return (
    <div className={pageStack} data-testid="diagnostics-page">
      <StatusAlert tone="info" icon={<Info className="h-4 w-4 text-[var(--gc-accent)]" />} title="WU13 selective diagnostics">
        WU13 selective diagnostics — read-only, never actionable CLI. {typeof d.note === "string" ? d.note : ""}
      </StatusAlert>

      <SurfaceCard>
        <SectionHeader title="Filter evidence" />
        <div data-testid="diag-filter" className="flex flex-col gap-2.5">
          <Line>
            Available: <Flag value={filter.available ?? false} /> · Actionable: <Flag value={filter.actionable ?? false} />
          </Line>
          <Line>
            Noise level: <Flag value={filter.overall_noise_level ?? "n/a"} />
          </Line>
          <Line>
            Confidence: <Flag value={filter.confidence ?? "n/a"} />
          </Line>
          <CodeBlock
            maxHeight={200}
            value={{
              noise_floor_db: filter.noise_floor_db,
              group_delay: filter.group_delay || filter.current_group_delay,
              dynamic: filter.dynamic_lpf || filter.throttle_dependent_noise,
              candidate: filter.candidate || filter.filter_candidate,
              warnings: filter.warnings,
            }}
          />
        </div>
      </SurfaceCard>

      <div className="grid grid-cols-2 gap-4">
        <SurfaceCard>
          <SectionHeader title="Throttle / TPA advisory" />
          <div data-testid="diag-throttle" className="flex flex-col gap-2.5">
            <Line>
              Available: <Flag value={throttle.available ?? throttle.usable_bands != null} /> · TPA advisory:{" "}
              <Flag value={throttle.tpa_advisory ?? "n/a"} />
            </Line>
            <Line>
              TPA value: <Flag value={throttle.tpa_value ?? "none"} /> · TPA CLI: <Flag value={throttle.tpa_cli ?? "none"} /> ·
              Auto-apply: <Flag value="NO" />
            </Line>
            <Line>
              Usable bands: <Flag value={throttle.usable_bands ?? "n/a"} /> · High-throttle degradation:{" "}
              <Flag value={throttle.high_throttle_degradation ?? false} />
            </Line>
          </div>
        </SurfaceCard>

        <SurfaceCard>
          <SectionHeader title="Verification / convergence" />
          <div data-testid="diag-verification" className="flex flex-col gap-2.5">
            <Line>
              Status: <Flag value={verification.overall_status ?? "n/a"} />
            </Line>
            <Line>
              Comparable: <Flag value={verification.comparable ?? false} /> · Rollback advisory:{" "}
              <Flag value={verification.rollback_advisory ?? false} /> · Auto-rollback: <Flag value="NO" />
            </Line>
            <p className="m-0 text-xs text-[var(--gc-text-tertiary)]">{String(verification.note ?? verification.label ?? "")}</p>
          </div>
        </SurfaceCard>
      </div>
    </div>
  );
}
