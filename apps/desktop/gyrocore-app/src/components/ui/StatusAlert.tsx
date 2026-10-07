import * as React from "react";
import { cn } from "@/lib/utils";
import { statusPanel } from "@/lib/premium-theme";

type Tone = "neutral" | "better" | "worse" | "warning" | "info" | "missing" | "derived";

export interface StatusAlertProps extends React.HTMLAttributes<HTMLDivElement> {
  tone?: Tone;
  icon?: React.ReactNode;
  title?: string;
}

const StatusAlert = React.forwardRef<HTMLDivElement, StatusAlertProps>(
  ({ tone = "neutral", icon, title, children, className, ...props }, ref) => (
    <div
      ref={ref}
      role="status"
      className={cn(statusPanel(tone), className)}
      {...props}
    >
      <div className="flex items-start gap-3">
        {icon && (
          <div className="mt-0.5 shrink-0 text-[var(--gc-text-tertiary)]">
            {icon}
          </div>
        )}
        <div className="flex flex-col gap-1 min-w-0">
          {title && (
            <p className="text-sm font-medium text-[var(--gc-text-primary)]">
              {title}
            </p>
          )}
          {children && (
            <div className="text-xs text-[var(--gc-text-secondary)]">
              {children}
            </div>
          )}
        </div>
      </div>
    </div>
  ),
);
StatusAlert.displayName = "StatusAlert";

export { StatusAlert };
