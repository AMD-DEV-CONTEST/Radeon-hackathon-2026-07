"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface ProgressProps extends React.ComponentProps<"div"> {
  value?: number;
  indicatorClassName?: string;
}

function Progress({
  className,
  value = 0,
  indicatorClassName,
  ...props
}: ProgressProps) {
  const clamped = Math.min(100, Math.max(0, value));

  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
      data-slot="progress"
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-muted",
        className
      )}
      {...props}
    >
      <div
        data-slot="progress-indicator"
        className={cn(
          "h-full rounded-full bg-primary transition-[width] duration-300 ease-out",
          indicatorClassName
        )}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

export { Progress };
