import * as React from "react";
import { cn } from "@/lib/utils";
import { microLabel } from "@/lib/premium-theme";

export type MicroLabelProps = React.HTMLAttributes<HTMLSpanElement>;

const MicroLabel = React.forwardRef<HTMLSpanElement, MicroLabelProps>(
  ({ className, ...props }, ref) => (
    <span ref={ref} className={cn(microLabel, className)} {...props} />
  ),
);
MicroLabel.displayName = "MicroLabel";

export { MicroLabel };
