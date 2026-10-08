import { LineChart } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { chartWellPanel, metadataText } from "@/lib/premium-theme";
import { cardTitle } from "@/lib/gyrocore-theme";
import { cn } from "@/lib/utils";

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

  const header = (
    <div className="mb-3 flex items-baseline justify-between gap-2">
      <h3 className={cn(cardTitle, "m-0")}>
        {title} <span className={metadataText}>({yLabel})</span>
      </h3>
      {cleaned.length > 0 && <span className={metadataText}>{cleaned.length} pts</span>}
    </div>
  );

  if (!cleaned.length) {
    return (
      <SurfaceCard>
        {header}
        <EmptyState
          icon={<LineChart className="h-5 w-5" aria-hidden />}
          title="No series data."
          description="The workspace contains no points for this series."
          className="py-8"
        />
      </SurfaceCard>
    );
  }

  const pad = 28;
  const w = 520;
  const h = 170;
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
  const gridYs = [0.25, 0.5, 0.75].map((f) => pad + f * (h - pad * 2));

  return (
    <SurfaceCard>
      {header}
      <div className={cn(chartWellPanel, "h-[170px]")}>
        <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={title} className="block h-full w-full">
          {gridYs.map((y) => (
            <line key={y} x1={pad} x2={w - pad} y1={y} y2={y} stroke="rgba(148,163,184,0.08)" strokeWidth="1" />
          ))}
          <polyline fill="none" stroke="#22d3ee" strokeWidth="1.6" strokeLinejoin="round" points={coords} />
          <text x={pad} y={16} fill="#64748b" fontSize="13" fontFamily="Geist Mono Variable, monospace">
            {maxY.toFixed(1)}
          </text>
          <text x={pad} y={h - 8} fill="#64748b" fontSize="13" fontFamily="Geist Mono Variable, monospace">
            {minX.toFixed(0)} Hz
          </text>
          <text x={w - pad} y={h - 8} textAnchor="end" fill="#64748b" fontSize="13" fontFamily="Geist Mono Variable, monospace">
            {maxX.toFixed(0)} Hz
          </text>
        </svg>
      </div>
    </SurfaceCard>
  );
}
