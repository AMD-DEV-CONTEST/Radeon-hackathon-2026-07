import * as React from "react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "success" | "warning" | "error" | "outline";
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const variants = {
    default: "bg-[var(--color-surface-hover)] text-[var(--color-foreground)] border-transparent",
    success: "bg-[var(--color-success)] text-white border-transparent",
    warning: "bg-[var(--color-warning)] text-white border-transparent",
    error: "bg-[var(--color-error)] text-white border-transparent",
    outline: "text-[var(--color-foreground)] border-[var(--color-border)]",
  };

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}

export { Badge };
