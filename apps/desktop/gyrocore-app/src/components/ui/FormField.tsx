import * as React from "react";
import { cn } from "@/lib/utils";
import {
  fieldLabel,
  fieldHelp,
  formError,
  inputBase,
} from "@/lib/premium-theme";

export interface FormFieldProps extends React.HTMLAttributes<HTMLDivElement> {
  label: string;
  htmlFor?: string;
  help?: string;
  error?: string;
}

const FormField = React.forwardRef<HTMLDivElement, FormFieldProps>(
  ({ label: labelText, htmlFor, help, error, children, className, ...props }, ref) => (
    <div ref={ref} className={cn("flex flex-col", className)} {...props}>
      <label htmlFor={htmlFor} className={fieldLabel}>
        {labelText}
      </label>
      {children ?? <input id={htmlFor} className={inputBase} />}
      {error ? (
        <p className={formError}>{error}</p>
      ) : help ? (
        <p className={fieldHelp}>{help}</p>
      ) : null}
    </div>
  ),
);
FormField.displayName = "FormField";

export { FormField };
