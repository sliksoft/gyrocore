import * as React from "react";
import { cn } from "@/lib/utils";
import { gradeBadge } from "@/lib/premium-theme";

type Grade = "A" | "B" | "C" | "D" | "F" | string;

const gradeColorMap: Record<string, string> = {
  A: "border-[rgba(16,185,129,0.18)] bg-[rgba(16,185,129,0.10)] text-[#6ee7b7]",
  B: "border-[rgba(34,211,238,0.18)] bg-[rgba(34,211,238,0.08)] text-[var(--gc-accent)]",
  C: "border-[rgba(245,158,11,0.18)] bg-[rgba(245,158,11,0.10)] text-[#fcd34d]",
  D: "border-[rgba(251,146,60,0.18)] bg-[rgba(251,146,60,0.08)] text-[#fdba74]",
  F: "border-[rgba(239,68,68,0.18)] bg-[rgba(239,68,68,0.08)] text-[#fca5a5]",
};

const fallbackColor =
  "border-white/[0.08] bg-gradient-to-b from-[var(--gc-bg-surface-3)] to-[var(--gc-bg-surface-2)] text-[var(--gc-text-secondary)]";

export interface GradeBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  grade: Grade;
}

const GradeBadge = React.forwardRef<HTMLSpanElement, GradeBadgeProps>(
  ({ grade, className, ...props }, ref) => {
    const letter = grade.charAt(0).toUpperCase();
    const color = gradeColorMap[letter] ?? fallbackColor;
    return (
      <span
        ref={ref}
        className={cn(gradeBadge, color, className)}
        {...props}
      >
        {grade}
      </span>
    );
  },
);
GradeBadge.displayName = "GradeBadge";

export { GradeBadge };
