"use client";

import { Eye, EyeOff, Lock } from "lucide-react";
import * as React from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface PasswordInputProps
  extends Omit<React.ComponentProps<"input">, "type"> {
  error?: boolean;
}

export const PasswordInput = React.forwardRef<
  HTMLInputElement,
  PasswordInputProps
>(({ className, error = false, disabled, id, autoComplete, ...props }, ref) => {
  const [isVisible, setIsVisible] = React.useState(false);
  const inputId = id ?? "password";

  return (
    <div className="relative">
      <Lock
        className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <Input
        ref={ref}
        id={inputId}
        type={isVisible ? "text" : "password"}
        autoComplete={autoComplete ?? "current-password"}
        disabled={disabled}
        aria-invalid={error || undefined}
        className={cn("pr-11 pl-10", className)}
        {...props}
      />
      <button
        type="button"
        className="absolute top-1/2 right-2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        aria-label={isVisible ? "Hide password" : "Show password"}
        aria-controls={inputId}
        aria-pressed={isVisible}
        disabled={disabled}
        onClick={() => setIsVisible((previous) => !previous)}
      >
        {isVisible ? (
          <EyeOff className="h-4 w-4" aria-hidden="true" />
        ) : (
          <Eye className="h-4 w-4" aria-hidden="true" />
        )}
      </button>
    </div>
  );
});

PasswordInput.displayName = "PasswordInput";
