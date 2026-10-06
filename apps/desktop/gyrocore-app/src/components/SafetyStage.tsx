import { StatusBadge } from "./StatusBadge";

export function SafetyStage({
  title,
  status,
  body,
}: {
  title: string;
  status?: string | null;
  body: Record<string, unknown> | null | undefined;
}) {
  const checks = Array.isArray(body?.checks) ? (body?.checks as Array<Record<string, unknown>>) : [];
  const reasons = [
    ...((body?.blocking_reasons as string[]) || []),
    ...((body?.blocked_reasons as string[]) || []),
    ...((body?.warning_reasons as string[]) || []),
    ...((body?.warnings as string[]) || []),
    ...((body?.reasons as string[]) || []),
  ];
  const clampIds = (body?.clamp_ids as string[]) || [];

  return (
    <div className="panel">
      <h3>
        {title} <StatusBadge value={status || (body?.status as string)} />
      </h3>
      {reasons.length > 0 && (
        <ul className="checks">
          {reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {clampIds.length > 0 && (
        <p className="mono muted">clamp_ids: {clampIds.join(", ")}</p>
      )}
      {checks.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Rule</th>
              <th>Verdict</th>
              <th>Message</th>
              <th>Before</th>
              <th>After</th>
            </tr>
          </thead>
          <tbody>
            {checks.map((c, i) => (
              <tr key={`${c.rule_id}-${i}`}>
                <td className="mono">{String(c.rule_id || "")}</td>
                <td>
                  <StatusBadge value={String(c.verdict || "")} />
                </td>
                <td>{String(c.message || "")}</td>
                <td className="num">{c.before == null ? "—" : String(c.before)}</td>
                <td className="num">{c.after == null ? "—" : String(c.after)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!reasons.length && !checks.length && <p className="muted">No detailed reasons for this stage.</p>}
    </div>
  );
}
