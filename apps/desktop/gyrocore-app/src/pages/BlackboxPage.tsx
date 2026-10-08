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

type BrowserFlight = { index: number; label: string; durationUs: number | null; sampleCount: number; error?: string };

/** Browser workspace: the local decode of the selected log (no viewer host, no localhost). */
function BrowserBlackbox({ bb }: { bb: Record<string, unknown> }) {
  const flights = (bb.flights as BrowserFlight[] | undefined) || [];
  const md = (bb.metadata as Record<string, unknown> | undefined) || {};
  const fields = (bb.fields_hint as string[] | undefined) || [];
  const selected = Number(bb.selected_log_index);
  const value = (v: unknown) => (v == null || v === "" ? "—" : String(v));
  return (
    <div className={pageStack} data-testid="blackbox-browser">
      <SurfaceCard>
        <SectionHeader title="Blackbox log" subtitle="Decoded locally in this browser (vendored Betaflight flightlog.js). Nothing uploaded." />
        <KeyValue
          rows={[
            { label: "Filename", value: value(bb.filename), mono: true },
            { label: "Size", value: bb.size_bytes != null ? `${bb.size_bytes} bytes` : "—", mono: true },
            { label: "Log index", value: `${value(bb.selected_log_index)} of ${value(bb.log_count)}`, mono: true },
            { label: "Frames decoded", value: value(bb.frames_decoded), mono: true },
            { label: "Decoder", value: value(bb.decoder), mono: true },
            { label: "Firmware", value: value(md.firmware), mono: true },
            { label: "Board", value: value(md.board), mono: true },
            { label: "Craft", value: value(md.craft), mono: true },
            { label: "Looptime", value: md.looptime_us != null ? `${md.looptime_us} µs` : "—", mono: true },
            { label: "Debug mode", value: value(md.debug_mode), mono: true },
            {
              label: "Sample rate (est.)",
              value: typeof md.sample_rate_hz_estimate === "number" ? `${Math.round(md.sample_rate_hz_estimate)} Hz` : "—",
              mono: true,
            },
          ]}
        />
      </SurfaceCard>
      <div className="grid grid-cols-2 gap-4">
        <SurfaceCard>
          <SectionHeader title="Embedded logs" subtitle="The selected log is the one every workspace page refers to." />
          <div data-testid="blackbox-flights">
          <ReasonList
            items={flights.map(
              (f) =>
                `${f.index === selected ? "▶ " : ""}${f.index}: ${f.label}` +
                (f.error ? ` — ${f.error}` : ` — ${f.durationUs != null ? (f.durationUs / 1e6).toFixed(2) : "?"} s, ${f.sampleCount} samples`),
            )}
          />
          </div>
        </SurfaceCard>
        <SurfaceCard>
          <SectionHeader title="Logged fields" subtitle={`${fields.length} fields in the selected log`} />
          <ReasonList items={fields} />
        </SurfaceCard>
      </div>
    </div>
  );
}

export function BlackboxPage({ ws }: { ws: WorkspacePayload }) {
  const bb = ws.blackbox || {};
  if (bb.source === "browser") return <BrowserBlackbox bb={bb} />;
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
