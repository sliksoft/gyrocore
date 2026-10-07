import { FlaskConical } from "lucide-react";
import type { WorkspacePayload } from "@/bridge/types";
import { KeyValue, ReasonList } from "@/components/KeyValue";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StatusAlert } from "@/components/ui/StatusAlert";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { pageStack } from "@/lib/gyrocore-theme";
import { chartWellPanel, codePanel, mutedText } from "@/lib/premium-theme";
import { cn } from "@/lib/utils";

const UPSTREAM = [
  "flightlog.js / flightlog_parser.js — log model",
  "grapher.js / graph_config.js — timeline graphs",
  "seekbar.js / playback_controls.js — cursor / seek",
  "graph_spectrum*.js — FFT overlays",
  "components/* — Vue panels (legend, spectrum, PID table)",
];

export function BlackboxPage({ ws }: { ws: WorkspacePayload }) {
  const bb = ws.blackbox || {};
  const viewerUrl = (import.meta.env.VITE_BLACKBOX_VIEWER_URL as string | undefined) || "http://127.0.0.1:1422/";
  const fields = (bb.fields_hint as string[]) || [];

  return (
    <div className={pageStack}>
      {ws.demo && (
        <StatusAlert tone="warning" icon={<FlaskConical className="h-4 w-4 text-[var(--gc-status-warn)]" />} title="Demo workspace">
          {ws.demo_label}
        </StatusAlert>
      )}
      <SurfaceCard>
        <SectionHeader
          title="Blackbox Viewer"
          subtitle="Presentation only — tuning authority stays in the Python Core."
        />
        <p className={cn(mutedText, "m-0 mb-4")}>
          Upstream foundation:{" "}
          <span className="font-mono text-[var(--gc-text-secondary)]">
            {String(bb.viewer || "third_party/betaflight/blackbox-log-viewer")}
          </span>
          . Host: <span className="font-mono text-[var(--gc-text-secondary)]">{String(bb.host || "apps/desktop/blackbox-host")}</span>.
          Not reimplemented.
        </p>
        <KeyValue
          rows={[
            { label: "Filename", value: String(bb.filename || "—"), mono: true },
            { label: "Size", value: bb.size_bytes != null ? `${bb.size_bytes} bytes` : "—", mono: true },
            { label: "Log index", value: String(bb.selected_log_index ?? "—"), mono: true },
          ]}
        />
      </SurfaceCard>

      <SurfaceCard>
        <SectionHeader
          title="Viewer host"
          subtitle="Start apps/desktop/blackbox-host (npm run dev) to embed the vendored Explorer."
        />
        <div className={cn(chartWellPanel, "p-1")}>
          <iframe
            className="block h-[min(62vh,640px)] w-full rounded-lg border-0 bg-black"
            title="Blackbox Viewer"
            src={viewerUrl}
            data-testid="viewer-frame"
          />
        </div>
      </SurfaceCard>

      <div className="grid grid-cols-2 gap-4">
        <SurfaceCard>
          <SectionHeader title="Upstream components in use" />
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {UPSTREAM.map((x) => (
              <li key={x} className={cn(codePanel, "px-3 py-2")}>
                {x}
              </li>
            ))}
          </ul>
        </SurfaceCard>
        <SurfaceCard>
          <SectionHeader title="Useful signals" subtitle="gyro · setpoint · PID · motors · RC · debug" />
          <ReasonList items={fields} />
        </SurfaceCard>
      </div>
    </div>
  );
}
