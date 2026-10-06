import type { WorkspacePayload } from "../bridge/types";

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
    <div className="stack">
      {ws.demo && <div className="banner">{ws.demo_label}</div>}
      <div className="panel">
        <h2>Blackbox Viewer</h2>
        <p className="muted">
          Upstream foundation: <span className="mono">{String(bb.viewer || "third_party/betaflight/blackbox-log-viewer")}</span>
          . Host: <span className="mono">{String(bb.host || "apps/desktop/blackbox-host")}</span>. Not reimplemented.
        </p>
        <div className="kv" style={{ marginTop: "0.5rem" }}>
          <div>Filename</div>
          <div className="mono">{String(bb.filename || "—")}</div>
          <div>Size</div>
          <div className="mono">{bb.size_bytes != null ? `${bb.size_bytes} bytes` : "—"}</div>
          <div>Log index</div>
          <div className="mono">{String(bb.selected_log_index ?? "—")}</div>
        </div>
      </div>

      <div className="panel">
        <h3>Viewer host</h3>
        <p className="muted">
          Start <span className="mono">apps/desktop/blackbox-host</span> (`npm run dev`) to embed the vendored
          Explorer. Tuning authority stays in Python Core — the viewer is presentation only.
        </p>
        <iframe className="viewer-frame" title="Blackbox Viewer" src={viewerUrl} data-testid="viewer-frame" />
      </div>

      <div className="grid2">
        <div className="panel">
          <h3>Upstream components in use</h3>
          <ul className="checks">
            {UPSTREAM.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
        <div className="panel">
          <h3>Useful signals</h3>
          <ul className="checks mono">
            {fields.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          <p className="muted">gyro · setpoint · PID · motors · RC · debug</p>
        </div>
      </div>
    </div>
  );
}
