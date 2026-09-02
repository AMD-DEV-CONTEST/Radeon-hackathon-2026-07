"use client";

import { Clock3 } from "lucide-react";

interface InterviewTimerProps {
  elapsedSeconds: number;
  className?: string;
}

function formatSeconds(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = Math.floor(totalSeconds % 60)
    .toString()
    .padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function InterviewTimer({
  elapsedSeconds,
  className,
}: InterviewTimerProps) {
  return (
    <div
      className={className}
      aria-label={`Elapsed question time ${formatSeconds(elapsedSeconds)}`}
    >
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
        <Clock3 className="h-4 w-4" aria-hidden="true" />
        {formatSeconds(elapsedSeconds)}
      </span>
    </div>
  );
}
