import { useState } from "react";
import { bridge } from "../bridge/client";
import type { InspectResult, WorkspacePayload } from "../bridge/types";

const DEMOS = ["pass", "warn", "block", "no_chirp", "merge_review", "no_autotune"] as const;

export function OpenPage({
  onLoaded,
}: {
  onLoaded: (ws: WorkspacePayload, inspect?: InspectResult | null) => void;
}) {
  const [path, setPath] = useState("");
  const [cliPath, setCliPath] = useState("");
  const [inspect, setInspect] = useState<InspectResult | null>(null);
  const [logIndex, setLogIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function doInspect() {
    setBusy(true);
    setError(null);
    try {
      const result = await bridge.inspect(path);
      setInspect(result);
      setLogIndex(result.recommended_log_index ?? 0);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function doAnalyze() {
    setBusy(true);
    setError(null);
    try {
      const ws = await bridge.analyze({
        path,
        log_index: logIndex,
        cli_path: cliPath || undefined,
      });
      onLoaded(ws, inspect);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function loadDemo(scenario: string) {
    setBusy(true);
    setError(null);
    try {
      const ws = await bridge.loadDemo(scenario);
      onLoaded(ws, null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="panel">
        <h2>Open Blackbox Log</h2>
        <p className="muted">Local files only. Nothing is uploaded. No flight-controller connection.</p>
        <div className="stack" style={{ marginTop: "0.6rem" }}>
          <label className="row">
            <span className="muted" style={{ width: 110 }}>
              Log path
            </span>
            <input
              className="mono"
              style={{ flex: 1, background: "#0a0d11", border: "1px solid var(--border)", padding: "0.35rem" }}
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/path/to/flight.bbl"
              data-testid="log-path"
            />
            <button type="button" onClick={doInspect} disabled={!path || busy}>
              Inspect
            </button>
          </label>
          <label className="row">
            <span className="muted" style={{ width: 110 }}>
              CLI dump
            </span>
            <input
              className="mono"
              style={{ flex: 1, background: "#0a0d11", border: "1px solid var(--border)", padding: "0.35rem" }}
              value={cliPath}
              onChange={(e) => setCliPath(e.target.value)}
              placeholder="optional /path/to/cli.txt"
              data-testid="cli-path"
            />
          </label>
          {inspect && (
            <div className="kv">
              <div>Filename</div>
              <div className="mono">{inspect.filename}</div>
              <div>Size</div>
              <div className="mono">{inspect.size_bytes} bytes</div>
              <div>Logs</div>
              <div>
                {inspect.multi_log ? (
                  <select
                    value={logIndex}
                    onChange={(e) => setLogIndex(Number(e.target.value))}
                    data-testid="log-index"
                  >
                    {inspect.logs.map((l) => (
                      <option key={l.index} value={l.index}>
                        {l.index}: {l.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span>1 log</span>
                )}
              </div>
              <div>Decoder</div>
              <div className="mono">{JSON.stringify(inspect.decoder)}</div>
            </div>
          )}
          <div className="row">
            <button type="button" className="primary" onClick={doAnalyze} disabled={!path || busy} data-testid="analyze-btn">
              Begin analysis
            </button>
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Demo / fixture mode</h2>
        <p className="muted">Synthetic Core scenarios for UI testing. Not real flight blackbox data.</p>
        <div className="row" style={{ marginTop: "0.5rem" }}>
          {DEMOS.map((s) => (
            <button key={s} type="button" onClick={() => loadDemo(s)} disabled={busy} data-testid={`demo-${s}`}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="banner block" data-testid="open-error">
          {error}
        </div>
      )}
      {busy && <div className="banner info">Working…</div>}
    </div>
  );
}
