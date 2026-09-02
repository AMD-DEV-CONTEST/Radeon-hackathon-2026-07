"use client";

import { MessageSquare } from "lucide-react";

import { Progress } from "@/components/ui/progress";

interface CommunicationScoreProps {
  score: number;
}

export function CommunicationScore({ score }: CommunicationScoreProps) {
  return (
    <li className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-2 text-sm text-white">
          <MessageSquare className="h-4 w-4 text-primary" aria-hidden="true" />
          Communication
        </span>
        <span className="text-sm font-semibold text-white">{score}%</span>
      </div>
      <Progress
        value={score}
        className="h-1.5"
        aria-label={`Communication score ${score} percent`}
      />
    </li>
  );
}
