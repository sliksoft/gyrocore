import { TriangleAlert, Waves } from "lucide-react";
import type { WorkspacePayload } from "@/bridge/types";
import { CodeBlock, KeyValue, ReasonList } from "@/components/KeyValue";
import { SeriesChart } from "@/components/SeriesChart";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricTile } from "@/components/ui/MetricTile";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StatusAlert } from "@/components/ui/StatusAlert";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { chirpDisplay } from "@/lib/chirpStatus";
import { pageStack } from "@/lib/gyrocore-theme";

export function ChirpPage({ ws }: { ws: WorkspacePayload }) {
  const c = ws.chirp;
  if (!c) {
    return (
      <SurfaceCard>
        <SectionHeader title="CHIRP / System ID" />
        <EmptyState icon={<Waves className="h-5 w-5" aria-hidden />} title="No CHIRP payload." />
      </SurfaceCard>
    );
  }
  const display = chirpDisplay(c);
  if (!display.chartable) {
    // available=true with empty series or a non-usable status is a contradiction, never a PASS.
    const reason = display.reason;
    return (
      <div className={pageStack}>
        <SurfaceCard data-testid="chirp-unavailable">
          <SectionHeader
            title="CHIRP / System ID"
            subtitle="No valid CHIRP segment for Bode charts."
            actions={<StatusBadge value={display.badge} />}
          />
          <KeyValue
            rows={[
              { label: "Reason", value: reason, mono: true },
              ...(c.status ? [{ label: "Status", value: c.status, mono: true }] : []),
            ]}
          />
          {(c.warnings || []).length > 0 && <ReasonList items={c.warnings || []} className="mt-4" />}
        </SurfaceCard>
      </div>
    );
  }

  return (
    <div className={pageStack} data-testid="chirp-available">
      <SurfaceCard>
        <SectionHeader title="CHIRP / System ID" subtitle="Closed-loop system identification from the CHIRP segment." actions={<StatusBadge value={display.badge} />} />
        <div className="mb-4 grid grid-cols-3 gap-3">
          <MetricTile label="Axis" value={c.axis || "—"} />
          <MetricTile label="Sample rate" value={c.sample_rate_hz ?? "—"} unit={c.sample_rate_hz != null ? "Hz" : undefined} />
          <MetricTile label="Quality" value={c.quality || "—"} />
        </div>
        <KeyValue
          rows={[
            { label: "Rate source", value: c.sample_rate_source || "—", mono: true },
            { label: "Header vs timestamp", value: <CodeBlock value={c.header_vs_timestamp || {}} maxHeight={160} /> },
            { label: "Usable range", value: <CodeBlock value={c.usable_frequency_hz || {}} maxHeight={120} /> },
            { label: "Segment", value: <CodeBlock value={c.segment || {}} maxHeight={160} /> },
          ]}
        />
        {(c.warnings || []).length > 0 && (
          <StatusAlert
            tone="warning"
            className="mt-4"
            icon={<TriangleAlert className="h-4 w-4 text-[var(--gc-status-warn)]" />}
            title="Sample-rate / quality warnings"
          >
            {(c.warnings || []).join("; ")}
          </StatusAlert>
        )}
      </SurfaceCard>
      <div className="grid grid-cols-3 gap-4">
        <SeriesChart title="Magnitude" points={c.magnitude} yKey="db" yLabel="dB" />
        <SeriesChart title="Phase" points={c.phase} yKey="deg" yLabel="deg" />
        <SeriesChart title="Coherence" points={c.coherence} yKey="value" yLabel="0–1" />
      </div>
    </div>
  );
}
