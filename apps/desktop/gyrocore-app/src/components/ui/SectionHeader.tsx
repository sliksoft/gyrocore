import * as React from "react";
import { cn } from "@/lib/utils";
import {
  eyebrow as eyebrowStyle,
  sectionTitle,
  sectionSubtitle,
} from "@/lib/premium-theme";

export interface SectionHeaderProps
  extends React.HTMLAttributes<HTMLDivElement> {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

const SectionHeader = React.forwardRef<HTMLDivElement, SectionHeaderProps>(
  ({ eyebrow, title, subtitle, actions, className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("flex items-start justify-between gap-4 mb-4", className)}
      {...props}
    >
      <div className="flex flex-col gap-1">
        {eyebrow && <span className={eyebrowStyle}>{eyebrow}</span>}
        <h2 className={sectionTitle}>{title}</h2>
        {subtitle && <p className={cn(sectionSubtitle, "m-0 max-w-3xl")}>{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  ),
);
SectionHeader.displayName = "SectionHeader";

export { SectionHeader };
