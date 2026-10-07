import * as React from "react";
import { cn } from "@/lib/utils";
import { cardMuted } from "@/lib/premium-theme";

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  ({ icon, title, description, action, className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        cardMuted,
        "flex flex-col items-center justify-center gap-3 py-12 px-6 text-center",
        className,
      )}
      {...props}
    >
      {icon && (
        <div className="text-[var(--gc-text-tertiary)]">{icon}</div>
      )}
      <h3 className="text-sm font-medium text-[var(--gc-text-secondary)]">
        {title}
      </h3>
      {description && (
        <p className="max-w-sm text-xs text-[var(--gc-text-tertiary)]">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  ),
);
EmptyState.displayName = "EmptyState";

export { EmptyState };
