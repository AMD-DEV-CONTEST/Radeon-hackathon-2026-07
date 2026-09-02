"use client";

import { ShieldCheck } from "lucide-react";

import { Progress } from "@/components/ui/progress";

interface ConfidenceScoreProps {
  score: number;
  label?: string;
}

export function ConfidenceScore({
  score,
  label = "Honesty",
}: ConfidenceScoreProps) {
  return (
    <li className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-2 text-sm text-white">
          <ShieldCheck className="h-4 w-4 text-primary" aria-hidden="true" />
          {label}
        </span>
        <span className="text-sm font-semibold text-white">{score}%</span>
      </div>
      <Progress
        value={score}
        className="h-1.5"
        aria-label={`${label} score ${score} percent`}
      />
    </li>
  );
}
