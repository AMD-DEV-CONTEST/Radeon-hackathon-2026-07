import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type = "text", ...props }, ref) => {
    return (
      <input
        ref={ref}
        type={type}
        data-slot="input"
        className={cn(
          "flex h-11 w-full rounded-lg border border-border bg-[#0b1220] px-3 py-2 text-sm text-white shadow-sm transition-colors",
          "placeholder:text-muted-foreground/70",
          "outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/40",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/30",
          className
        )}
        {...props}
      />
    );
  }
);

Input.displayName = "Input";

export { Input };
