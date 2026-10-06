import type { ReactNode } from "react";
import type { WorkspacePayload } from "../bridge/types";

function block(title: string, body: ReactNode) {
  return (
    <section className="panel" style={{ marginBottom: 12 }}>
      <h2 style={{ margin: "0 0 8px", fontSize: 14 }}>{title}</h2>
      {body}
    </section>
  );
}

export function DiagnosticsPage({ ws }: { ws: WorkspacePayload }) {
  const d = (ws.diagnostics || {}) as Record<string, unknown>;
  const filter = (d.filter_evidence || {}) as Record<string, unknown>;
  const throttle = (d.throttle || {}) as Record<string, unknown>;
  const verification = (d.verification || {}) as Record<string, unknown>;

  return (
    <div data-testid="diagnostics-page">
      <p className="muted" style={{ marginTop: 0 }}>
        WU13 selective diagnostics — read-only, never actionable CLI.{" "}
        {typeof d.note === "string" ? d.note : ""}
      </p>

      {block(
        "Filter evidence",
        <div data-testid="diag-filter">
          <div>
            Available: {String(filter.available ?? false)} · Actionable:{" "}
            <strong>{String(filter.actionable ?? false)}</strong>
          </div>
          <div>Noise level: {String(filter.overall_noise_level ?? "n/a")}</div>
          <div>Confidence: {String(filter.confidence ?? "n/a")}</div>
          <pre className="code-block" style={{ maxHeight: 180, overflow: "auto" }}>
            {JSON.stringify(
              {
                noise_floor_db: filter.noise_floor_db,
                group_delay: filter.group_delay || filter.current_group_delay,
                dynamic: filter.dynamic_lpf || filter.throttle_dependent_noise,
                candidate: filter.candidate || filter.filter_candidate,
                warnings: filter.warnings,
              },
              null,
              2
            )}
          </pre>
        </div>
      )}

      {block(
        "Throttle / TPA advisory",
        <div data-testid="diag-throttle">
          <div>
            Available: {String(throttle.available ?? throttle.usable_bands != null)} · TPA
            advisory: <strong>{String(throttle.tpa_advisory ?? "n/a")}</strong>
          </div>
          <div>
            TPA value: {String(throttle.tpa_value ?? "none")} · TPA CLI:{" "}
            {String(throttle.tpa_cli ?? "none")} · Auto-apply: NO
          </div>
          <div>
            Usable bands: {String(throttle.usable_bands ?? "n/a")} · High-throttle degradation:{" "}
            {String(throttle.high_throttle_degradation ?? false)}
          </div>
        </div>
      )}

      {block(
        "Verification / convergence",
        <div data-testid="diag-verification">
          <div>
            Status: <strong>{String(verification.overall_status ?? "n/a")}</strong>
          </div>
          <div>
            Comparable: {String(verification.comparable ?? false)} · Rollback advisory:{" "}
            {String(verification.rollback_advisory ?? false)} · Auto-rollback: NO
          </div>
          <div className="muted">{String(verification.note ?? verification.label ?? "")}</div>
        </div>
      )}
    </div>
  );
}
