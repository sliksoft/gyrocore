import { StatusBadge } from "../components/StatusBadge";
import type { WorkspacePayload } from "../bridge/types";

export function OverviewPage({ ws }: { ws: WorkspacePayload }) {
  const o = ws.overview || {};
  return (
    <div className="stack">
      {ws.demo && <div className="banner">{ws.demo_label}</div>}
      <div className="grid3">
        <div className="panel">
          <h2>Craft / firmware</h2>
          <div className="kv">
            <div>Craft</div>
            <div>{String(o.craft || "—")}</div>
            <div>Target</div>
            <div>{String(o.target || "—")}</div>
            <div>Betaflight</div>
            <div className="mono">{String(o.betaflight_version || "—")}</div>
            <div>PID profile</div>
            <div className="mono">{String(o.pid_profile ?? "—")}</div>
          </div>
        </div>
        <div className="panel">
          <h2>Log</h2>
          <div className="kv">
            <div>Duration</div>
            <div className="mono">{o.log_duration_s != null ? `${o.log_duration_s} s` : "—"}</div>
            <div>Sample rate</div>
            <div className="mono">{o.sample_rate_hz != null ? `${o.sample_rate_hz} Hz` : "—"}</div>
            <div>CHIRP</div>
            <div>
              <StatusBadge value={o.chirp_detected ? "PASS" : "NOT AVAILABLE"} />
            </div>
            <div>Tune rec.</div>
            <div className="mono">{String(o.tune_recommendation || "—")}</div>
          </div>
        </div>
        <div className="panel">
          <h2>Safety / CLI</h2>
          <div className="kv">
            <div>Mechanical</div>
            <div>
              <StatusBadge value={String(o.mechanical_safety || "NOT AVAILABLE")} />
            </div>
            <div>Final safety</div>
            <div>
              <StatusBadge value={String(o.final_safety || "NOT AVAILABLE")} />
            </div>
            <div>CLI auth</div>
            <div>
              <StatusBadge value={String(o.cli_authorization || "NOT AVAILABLE")} />
            </div>
          </div>
        </div>
      </div>
      <div className="panel">
        <h2>Detected issues</h2>
        {Array.isArray(o.detected_issues) && o.detected_issues.length ? (
          <ul className="checks">
            {(o.detected_issues as string[]).map((x) => (
              <li key={String(x)}>{String(x)}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">None reported.</p>
        )}
        {o.message ? <p className="muted">{String(o.message)}</p> : null}
      </div>
    </div>
  );
}
