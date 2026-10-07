import { BarChart3, ListChecks } from "lucide-react";
import type { WorkspacePayload } from "@/bridge/types";
import { CodeBlock, ReasonList } from "@/components/KeyValue";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { GradeBadge } from "@/components/ui/GradeBadge";
import { MetricTile } from "@/components/ui/MetricTile";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { pageStack } from "@/lib/gyrocore-theme";

type Obj = Record<string, unknown>;

function asObj(v: unknown): Obj {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {};
}

function fmt(v: unknown, digits = 1): string | null {
  if (typeof v !== "number" || !Number.isFinite(v)) return null;
  return Number.isInteger(v) ? String(v) : v.toFixed(digits);
}

export function AnalysisPage({ ws }: { ws: WorkspacePayload }) {
  const a = ws.analysis;
  if (!a) {
    return (
      <SurfaceCard>
        <SectionHeader title="Analysis" />
        <EmptyState icon={<BarChart3 className="h-5 w-5" aria-hidden />} title="No analysis payload." />
      </SurfaceCard>
    );
  }
  const problems = ((a.problems as { problems?: unknown[] })?.problems || []) as Array<Record<string, unknown>>;
  const quality = asObj(a.quality);
  const resonance = asObj(a.resonance);
  const primary = asObj(resonance.primary);
  const peaks = Array.isArray(resonance.peaks) ? resonance.peaks : null;
  const motors = asObj(a.motors);
  const saturation = asObj(motors.saturation);
  const qualityWarnings = Array.isArray(quality.warnings) ? (quality.warnings as unknown[]).map(String) : [];

  return (
    <div className={pageStack}>
      <div className="grid grid-cols-3 gap-4">
        <SurfaceCard className="flex min-w-0 flex-col">
          <SectionHeader
            title="Quality"
            actions={
              <>
                {typeof quality.grade === "string" && <GradeBadge grade={quality.grade} />}
                <StatusBadge value={String((a.quality as { status?: string })?.status || (a.ok ? "PASS" : "BLOCK"))} />
              </>
            }
          />
          {fmt(quality.score) != null && <MetricTile label="Quality score" value={fmt(quality.score)!} className="mb-3" />}
          {qualityWarnings.length > 0 && <ReasonList items={qualityWarnings} className="mb-3" />}
          <CodeBlock value={a.quality || {}} />
        </SurfaceCard>
        <SurfaceCard className="flex min-w-0 flex-col">
          <SectionHeader title="Resonance" />
          {(fmt(primary.freq) != null || peaks) && (
            <div className="mb-3 grid grid-cols-2 gap-3">
              {fmt(primary.freq) != null && <MetricTile label="Primary peak" value={fmt(primary.freq)!} unit="Hz" />}
              {peaks && <MetricTile label="Peaks" value={peaks.length} />}
            </div>
          )}
          <CodeBlock value={a.resonance || {}} />
        </SurfaceCard>
        <SurfaceCard className="flex min-w-0 flex-col">
          <SectionHeader title="Motors / eRPM" />
          {(fmt(saturation.saturation_pct) != null || typeof saturation.status === "string") && (
            <div className="mb-3 grid grid-cols-2 gap-3">
              {fmt(saturation.saturation_pct) != null && (
                <MetricTile label="Saturation" value={fmt(saturation.saturation_pct)!} unit="%" />
              )}
              {typeof saturation.status === "string" && <MetricTile label="Saturation status" value={saturation.status} />}
            </div>
          )}
          <CodeBlock value={{ motors: a.motors, erpm: a.erpm, saturation: a.saturation }} />
        </SurfaceCard>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <SurfaceCard className="min-w-0">
          <SectionHeader title="FFT / spectral" />
          <CodeBlock value={a.spectral || {}} />
        </SurfaceCard>
        <SurfaceCard className="min-w-0">
          <SectionHeader title="Step / D-effectiveness" />
          <CodeBlock value={{ step_response: a.step_response, d_effectiveness: a.d_effectiveness }} />
        </SurfaceCard>
      </div>

      <SurfaceCard>
        <SectionHeader title="Detected problems" />
        {problems.length ? (
          <ReasonList items={problems.map((p) => String(p.type || p.description || JSON.stringify(p)))} />
        ) : (
          <EmptyState icon={<ListChecks className="h-5 w-5" aria-hidden />} title="None." className="py-8" />
        )}
      </SurfaceCard>
    </div>
  );
}
