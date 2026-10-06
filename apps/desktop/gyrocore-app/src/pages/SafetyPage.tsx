import type { WorkspacePayload } from "../bridge/types";
import { SafetyStage } from "../components/SafetyStage";
import { StatusBadge } from "../components/StatusBadge";

export function SafetyPage({ ws }: { ws: WorkspacePayload }) {
  const s = ws.safety;
  if (!s) {
    return (
      <div className="panel">
        <h2>Safety</h2>
        <p className="muted">Safety stages unavailable.</p>
      </div>
    );
  }
  return (
    <div className="stack" data-testid="safety-page">
      <div className="panel">
        <h2>
          Final <StatusBadge value={String(s.final?.status || "")} />
        </h2>
        <p className="muted">
          Why GyroCore allows or blocks this tune — mechanical → clamps → tuning_output_safety → (WU11 CLI
          separately).
        </p>
        {(s.final?.blocked_reasons as string[] | undefined)?.length ? (
          <ul className="checks">
            {(s.final.blocked_reasons as string[]).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <SafetyStage
        title="1. Mechanical Safety"
        status={String(s.mechanical?.status || "")}
        body={s.mechanical}
      />
      <SafetyStage title="2. Safe-Tune / Clamps" status={String(s.safe_tune?.status || "")} body={s.safe_tune} />
      <SafetyStage
        title="3. Tuning Output Safety"
        status={String(s.tuning_output_safety?.status || "")}
        body={s.tuning_output_safety}
      />
    </div>
  );
}
