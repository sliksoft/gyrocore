import type { WorkspacePayload } from "../bridge/types";
import { SeriesChart } from "../components/SeriesChart";
import { StatusBadge } from "../components/StatusBadge";

export function ChirpPage({ ws }: { ws: WorkspacePayload }) {
  const c = ws.chirp;
  if (!c) {
    return (
      <div className="panel">
        <h2>CHIRP / System ID</h2>
        <p className="muted">No CHIRP payload.</p>
      </div>
    );
  }
  if (!c.available) {
    return (
      <div className="stack">
        <div className="panel" data-testid="chirp-unavailable">
          <h2>
            CHIRP / System ID <StatusBadge value="NOT AVAILABLE" />
          </h2>
          <p className="muted">No valid CHIRP segment for Bode charts.</p>
          <div className="kv">
            <div>Reason</div>
            <div className="mono">{c.reason || "unavailable"}</div>
          </div>
          {(c.warnings || []).length > 0 && (
            <ul className="checks">
              {c.warnings!.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="stack" data-testid="chirp-available">
      <div className="panel">
        <h2>
          CHIRP / System ID <StatusBadge value="PASS" />
        </h2>
        <div className="kv">
          <div>Axis</div>
          <div>{c.axis || "—"}</div>
          <div>Sample rate</div>
          <div className="mono">{c.sample_rate_hz ?? "—"} Hz</div>
          <div>Rate source</div>
          <div className="mono">{c.sample_rate_source || "—"}</div>
          <div>Header vs timestamp</div>
          <div className="mono">{JSON.stringify(c.header_vs_timestamp || {})}</div>
          <div>Usable range</div>
          <div className="mono">{JSON.stringify(c.usable_frequency_hz || {})}</div>
          <div>Quality</div>
          <div>{c.quality || "—"}</div>
          <div>Segment</div>
          <div className="mono">{JSON.stringify(c.segment || {})}</div>
        </div>
        {(c.warnings || []).length > 0 && (
          <div className="banner" style={{ marginTop: "0.6rem" }}>
            Sample-rate / quality warnings: {(c.warnings || []).join("; ")}
          </div>
        )}
      </div>
      <div className="grid3">
        <SeriesChart title="Magnitude" points={c.magnitude} yKey="db" yLabel="dB" />
        <SeriesChart title="Phase" points={c.phase} yKey="deg" yLabel="deg" />
        <SeriesChart title="Coherence" points={c.coherence} yKey="value" yLabel="0–1" />
      </div>
    </div>
  );
}
