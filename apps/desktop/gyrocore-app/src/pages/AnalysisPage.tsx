import type { WorkspacePayload } from "../bridge/types";
import { StatusBadge } from "../components/StatusBadge";

export function AnalysisPage({ ws }: { ws: WorkspacePayload }) {
  const a = ws.analysis;
  if (!a) {
    return (
      <div className="panel">
        <h2>Analysis</h2>
        <p className="muted">No analysis payload.</p>
      </div>
    );
  }
  const problems = ((a.problems as { problems?: unknown[] })?.problems || []) as Array<Record<string, unknown>>;
  return (
    <div className="stack">
      <div className="grid3">
        <div className="panel">
          <h2>Quality</h2>
          <StatusBadge value={String((a.quality as { status?: string })?.status || (a.ok ? "PASS" : "BLOCK"))} />
          <pre className="mono muted" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(a.quality || {}, null, 2)}
          </pre>
        </div>
        <div className="panel">
          <h2>Resonance</h2>
          <pre className="mono muted" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(a.resonance || {}, null, 2)}
          </pre>
        </div>
        <div className="panel">
          <h2>Motors / eRPM</h2>
          <pre className="mono muted" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify({ motors: a.motors, erpm: a.erpm, saturation: a.saturation }, null, 2)}
          </pre>
        </div>
      </div>
      <div className="grid2">
        <div className="panel">
          <h2>FFT / spectral</h2>
          <pre className="mono muted" style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>
            {JSON.stringify(a.spectral || {}, null, 2)}
          </pre>
        </div>
        <div className="panel">
          <h2>Step / D-effectiveness</h2>
          <pre className="mono muted" style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>
            {JSON.stringify({ step_response: a.step_response, d_effectiveness: a.d_effectiveness }, null, 2)}
          </pre>
        </div>
      </div>
      <div className="panel">
        <h2>Detected problems</h2>
        {problems.length ? (
          <ul className="checks">
            {problems.map((p, i) => (
              <li key={i}>
                {String(p.type || p.description || JSON.stringify(p))}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">None.</p>
        )}
      </div>
    </div>
  );
}
