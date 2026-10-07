import * as React from "react";
import { cn } from "@/lib/utils";
import {
  metricTile as metricTileStyle,
  metricValue,
  microLabel,
} from "@/lib/premium-theme";

export interface MetricTileProps extends React.HTMLAttributes<HTMLDivElement> {
  label: string;
  value: string | number;
  unit?: string;
}

const MetricTile = React.forwardRef<HTMLDivElement, MetricTileProps>(
  ({ label, value, unit, className, ...props }, ref) => (
    <div ref={ref} className={cn(metricTileStyle, className)} {...props}>
      <span className={microLabel}>{label}</span>
      <div className="flex items-baseline gap-1.5 pt-0.5">
        <span className={metricValue}>{value}</span>
        {unit && (
          <span className="text-xs text-[var(--gc-text-tertiary)]">{unit}</span>
        )}
      </div>
    </div>
  ),
);
MetricTile.displayName = "MetricTile";

export { MetricTile };
