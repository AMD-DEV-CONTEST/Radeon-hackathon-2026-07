import type { HTMLAttributes } from "react";

import { cn } from "../../lib/utils";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
}

export function Badge({ tone = "neutral", className, ...props }: BadgeProps) {
  return <span className={cn("badge", `badge--${tone}`, className)} {...props} />;
}
