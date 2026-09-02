"use client";

import { Cpu } from "lucide-react";

import { Progress } from "@/components/ui/progress";

interface TechnicalScoreProps {
  score: number;
}

export function TechnicalScore({ score }: TechnicalScoreProps) {
  return (
    <li className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-2 text-sm text-white">
          <Cpu className="h-4 w-4 text-primary" aria-hidden="true" />
          Technical Depth
        </span>
        <span className="text-sm font-semibold text-white">{score}%</span>
      </div>
      <Progress
        value={score}
        className="h-1.5"
        aria-label={`Technical depth score ${score} percent`}
      />
    </li>
  );
}
