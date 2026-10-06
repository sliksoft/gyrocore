import type { StageValues, WorkspacePayload } from "../bridge/types";
import { StatusBadge } from "../components/StatusBadge";

function StageTable({ title, stage }: { title: string; stage?: StageValues | null }) {
  if (!stage || !stage.axes) {
    return (
      <div className="panel">
        <h3>{title}</h3>
        <p className="muted">Not available.</p>
      </div>
    );
  }
  return (
    <div className="panel">
      <h3>{title}</h3>
      <table className="data">
        <thead>
          <tr>
            <th>Axis</th>
            <th>P</th>
            <th>I</th>
            <th>D</th>
            <th>D-max</th>
            <th>FF</th>
          </tr>
        </thead>
        <tbody>
          {["roll", "pitch", "yaw"].map((axis) => {
            const a = stage.axes?.[axis] || {};
            return (
              <tr key={axis}>
                <td>{axis}</td>
                <td className="num">{a.p ?? "—"}</td>
                <td className="num">{a.i ?? "—"}</td>
                <td className="num">{a.d ?? "—"}</td>
                <td className="num">{a.d_max ?? "—"}</td>
                <td className="num">{a.ff ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {stage.filters && (
        <pre className="mono muted" style={{ whiteSpace: "pre-wrap", marginTop: "0.5rem" }}>
          {JSON.stringify(stage.filters, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function TunePage({ ws }: { ws: WorkspacePayload }) {
  const t = ws.tune;
  if (!t) {
    return (
      <div className="panel">
        <h2>Tune</h2>
        <p className="muted">Tune stages unavailable (missing baseline or blocked upstream).</p>
      </div>
    );
  }
  const mergeReview = String(t.merge_status || "").includes("review") || (t.review_reasons || []).length > 0;

  return (
    <div className="stack">
      {mergeReview && (
        <div className="banner block" data-testid="merge-review">
          MERGE REQUIRES REVIEW — {t.review_reasons?.join("; ") || t.merge_status}
        </div>
      )}
      <div className="panel">
        <h2>
          Stages <StatusBadge value={ws.overview?.final_safety as string} />
        </h2>
        <p className="muted">Recommendation and safe output are shown separately. Core owns the numbers.</p>
        <div className="kv">
          <div>Merge status</div>
          <div className="mono">{t.merge_status}</div>
          <div>Merged sliders</div>
          <div className="mono">{JSON.stringify(t.merged_sliders || {})}</div>
          <div>Per-axis WU8</div>
          <div className="mono">{JSON.stringify(t.per_axis_recommendations || {})}</div>
          <div>Clamps</div>
          <div className="mono">{(t.wu10_safe_target?.clamp_ids || []).join(", ") || "none"}</div>
        </div>
      </div>
      <div className="grid2">
        <StageTable title="CURRENT" stage={t.current} />
        <StageTable title="WU8 AUTOTUNE (sliders / axes)" stage={null} />
      </div>
      <div className="panel">
        <h3>WU8 Autotune recommendation (non-actionable)</h3>
        <pre className="mono muted" style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(t.wu8_autotune || {}, null, 2)}
        </pre>
      </div>
      <div className="grid2">
        <StageTable title="WU9 ABSOLUTE PROPOSAL" stage={t.wu9_absolute_proposal as StageValues} />
        <StageTable title="WU10 SAFE / CLAMPED TARGET" stage={t.wu10_safe_target} />
      </div>
    </div>
  );
}
