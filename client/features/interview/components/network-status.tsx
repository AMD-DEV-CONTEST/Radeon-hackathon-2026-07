"use client";

import { Activity } from "lucide-react";

import { cn } from "@/lib/utils";

interface NetworkStatusProps {
  latencyMs: number;
  isConnected: boolean;
  className?: string;
}

export function NetworkStatus({
  latencyMs,
  isConnected,
  className,
}: NetworkStatusProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 text-xs font-medium",
        isConnected ? "text-muted-foreground" : "text-destructive",
        className
      )}
      aria-live="polite"
    >
      <Activity
        className={cn(
          "h-3.5 w-3.5",
          isConnected ? "text-emerald-400" : "text-destructive"
        )}
        aria-hidden="true"
      />
      {isConnected
        ? `Current Delay: ${latencyMs}ms latency`
        : "Connection Lost"}
    </div>
  );
}
