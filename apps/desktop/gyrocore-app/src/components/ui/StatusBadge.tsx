import * as React from "react";
import { cn } from "@/lib/utils";
import { statusBadge } from "@/lib/premium-theme";

type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "muted";

export interface StatusBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

const StatusBadge = React.forwardRef<HTMLSpanElement, StatusBadgeProps>(
  ({ tone = "neutral", className, ...props }, ref) => (
    <span ref={ref} className={cn(statusBadge(tone), className)} {...props} />
  ),
);
StatusBadge.displayName = "StatusBadge";

export { StatusBadge };
