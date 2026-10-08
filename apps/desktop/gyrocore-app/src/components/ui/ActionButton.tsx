import * as React from "react";
import { cn } from "@/lib/utils";
import { actionButton, smallButton, iconButton } from "@/lib/premium-theme";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export interface ActionButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "default" | "small" | "icon";
}

const ActionButton = React.forwardRef<HTMLButtonElement, ActionButtonProps>(
  ({ variant = "primary", size = "default", className, ...props }, ref) => {
    const base =
      size === "icon"
        ? iconButton
        : size === "small"
          ? cn(smallButton, actionButton(variant))
          : actionButton(variant);

    return <button ref={ref} className={cn(base, className)} {...props} />;
  },
);
ActionButton.displayName = "ActionButton";

export { ActionButton };
