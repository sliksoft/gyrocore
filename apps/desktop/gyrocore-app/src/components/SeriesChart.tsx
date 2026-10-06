/** Lightweight SVG series chart — display only, no analysis math. */
export function SeriesChart({
  title,
  points,
  yKey,
  yLabel,
}: {
  title: string;
  points: Array<Record<string, number | null | undefined>>;
  yKey: string;
  yLabel: string;
}) {
  const cleaned = points
    .map((p) => ({ x: Number(p.hz), y: p[yKey] == null ? null : Number(p[yKey]) }))
    .filter((p) => Number.isFinite(p.x) && p.y != null && Number.isFinite(p.y)) as Array<{ x: number; y: number }>;

  if (!cleaned.length) {
    return (
      <div className="panel">
        <h3>{title}</h3>
        <p className="muted">No series data.</p>
      </div>
    );
  }

  const pad = 28;
  const w = 520;
  const h = 160;
  const xs = cleaned.map((p) => p.x);
  const ys = cleaned.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const dx = maxX - minX || 1;
  const dy = maxY - minY || 1;
  const coords = cleaned
    .map((p) => {
      const x = pad + ((p.x - minX) / dx) * (w - pad * 2);
      const y = h - pad - ((p.y - minY) / dy) * (h - pad * 2);
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="panel">
      <h3>
        {title} <span className="muted">({yLabel})</span>
      </h3>
      <div className="chart">
        <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={title}>
          <polyline fill="none" stroke="#3d9cf0" strokeWidth="1.5" points={coords} />
          <text x={pad} y={14}>
            {maxY.toFixed(1)}
          </text>
          <text x={pad} y={h - 8}>
            {minX.toFixed(0)} Hz
          </text>
          <text x={w - 80} y={h - 8}>
            {maxX.toFixed(0)} Hz
          </text>
        </svg>
      </div>
    </div>
  );
}
