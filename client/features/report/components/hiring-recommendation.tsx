"use client";

import { Badge } from "@/components/ui/badge";
import type { HiringRecommendation as HiringRecommendationValue } from "@/features/report/types/report.types";
import { cn } from "@/lib/utils";

const RECOMMENDATION_STYLES: Record<
  HiringRecommendationValue,
  string
> = {
  "Strong Hire":
    "border-transparent bg-gradient-to-r from-violet-600 to-fuchsia-500 text-white shadow-[0_0_24px_rgba(139,92,246,0.45)]",
  Hire: "border-transparent bg-gradient-to-r from-violet-600 to-blue-500 text-white",
  Hold: "border-amber-400/40 bg-amber-500/15 text-amber-200",
  "No Hire": "border-destructive/40 bg-destructive/15 text-destructive",
};

interface HiringRecommendationProps {
  recommendation: HiringRecommendationValue;
  className?: string;
}

export function HiringRecommendation({
  recommendation,
  className,
}: HiringRecommendationProps) {
  return (
    <Badge
      aria-label={`Hiring recommendation: ${recommendation}`}
      className={cn(
        "px-4 py-1.5 text-sm font-semibold tracking-normal normal-case",
        RECOMMENDATION_STYLES[recommendation],
        className
      )}
    >
      {recommendation}
    </Badge>
  );
}
