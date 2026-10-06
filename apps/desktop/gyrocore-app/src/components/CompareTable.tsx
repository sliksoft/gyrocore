import type { ComparePayload } from "../bridge/types";

const AXES = ["roll", "pitch", "yaw"] as const;
const COMPS = [
  ["p", "P"],
  ["i", "I"],
  ["d", "D"],
  ["d_max", "D-max"],
  ["ff", "FF"],
] as const;

export function CompareTable({ compare }: { compare: ComparePayload | null }) {
  if (!compare) {
    return (
      <div className="panel">
        <h2>Compare</h2>
        <p className="muted">No compare data available.</p>
      </div>
    );
  }
  const cur = compare.current;
  const fin = compare.final_safe;
  const filterKeys = Object.keys(cur.filters || {});

  return (
    <div className="stack">
      <div className="panel">
        <h2>Current vs Final Safe Target</h2>
        <table className="data">
          <thead>
            <tr>
              <th>Setting</th>
              <th>Current</th>
              <th>Final safe</th>
              <th>Δ</th>
            </tr>
          </thead>
          <tbody>
            {AXES.flatMap((axis) =>
              COMPS.map(([key, label]) => {
                const a = cur.axes?.[axis]?.[key] ?? null;
                const b = fin.axes?.[axis]?.[key] ?? null;
                const delta = a != null && b != null ? b - a : null;
                return (
                  <tr key={`${axis}.${key}`}>
                    <td>
                      {axis} {label}
                    </td>
                    <td className="num">{a ?? "—"}</td>
                    <td className="num">{b ?? "—"}</td>
                    <td className={`num ${delta != null && delta > 0 ? "delta-pos" : delta != null && delta < 0 ? "delta-neg" : ""}`}>
                      {delta == null ? "—" : delta > 0 ? `+${delta}` : `${delta}`}
                    </td>
                  </tr>
                );
              }),
            )}
            {filterKeys.map((key) => {
              const a = cur.filters?.[key] ?? null;
              const b = fin.filters?.[key] ?? null;
              const delta = a != null && b != null ? b - a : null;
              return (
                <tr key={key}>
                  <td className="mono">{key}</td>
                  <td className="num">{a ?? "—"}</td>
                  <td className="num">{b ?? "—"}</td>
                  <td className={`num ${delta != null && delta > 0 ? "delta-pos" : delta != null && delta < 0 ? "delta-neg" : ""}`}>
                    {delta == null ? "—" : delta > 0 ? `+${delta}` : `${delta}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
