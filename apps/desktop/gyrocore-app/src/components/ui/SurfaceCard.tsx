import * as React from "react";
import { cn } from "@/lib/utils";
import { surfaceCard } from "@/lib/premium-theme";

type Variant = "base" | "elevated" | "interactive" | "muted" | "inset" | "data" | "chart" | "code";

export interface SurfaceCardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: Variant;
}

const SurfaceCard = React.forwardRef<HTMLDivElement, SurfaceCardProps>(
  ({ variant = "base", className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(surfaceCard(variant), "p-5", className)}
      {...props}
    />
  ),
);
SurfaceCard.displayName = "SurfaceCard";

export { SurfaceCard };
