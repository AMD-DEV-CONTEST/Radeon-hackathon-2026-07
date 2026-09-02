"use client";

import { Check } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

interface CheckboxProps
  extends Omit<React.ComponentProps<"button">, "onChange"> {
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  (
    {
      className,
      checked = false,
      onCheckedChange,
      disabled,
      id,
      ...props
    },
    ref
  ) => {
    return (
      <button
        ref={ref}
        id={id}
        type="button"
        role="checkbox"
        aria-checked={checked}
        disabled={disabled}
        data-slot="checkbox"
        data-state={checked ? "checked" : "unchecked"}
        className={cn(
          "flex h-4 w-4 shrink-0 items-center justify-center rounded border border-border bg-[#0b1220] transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
          "data-[state=checked]:border-primary data-[state=checked]:bg-primary",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        onClick={() => {
          if (!disabled) {
            onCheckedChange?.(!checked);
          }
        }}
        {...props}
      >
        {checked ? (
          <Check className="h-3 w-3 text-white" aria-hidden="true" />
        ) : null}
      </button>
    );
  }
);

Checkbox.displayName = "Checkbox";

export { Checkbox };
