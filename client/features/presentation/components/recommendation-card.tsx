"use client";

import { Badge } from "@/components/ui/badge";
import type { HiringRecommendation as HiringRecommendationValue } from "@/features/presentation/types/presentation.types";
import { cn } from "@/lib/utils";

const STYLES: Record<HiringRecommendationValue, string> = {
  "Strong Hire":
    "border-transparent bg-gradient-to-r from-violet-600 to-fuchsia-500 text-white shadow-[0_0_24px_rgba(139,92,246,0.45)]",
  Hire: "border-transparent bg-gradient-to-r from-violet-600 to-blue-500 text-white",
  Hold: "border-amber-400/40 bg-amber-500/15 text-amber-200",
  "No Hire": "border-destructive/40 bg-destructive/15 text-destructive",
};

interface RecommendationCardProps {
  recommendation: HiringRecommendationValue;
  explanation: string;
  className?: string;
}

export function RecommendationCard({
  recommendation,
  explanation,
  className,
}: RecommendationCardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-white/10 bg-[#12121a]/80 p-5 backdrop-blur-xl",
        className
      )}
    >
      <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        Hiring Recommendation
      </p>
      <Badge
        aria-label={`Hiring recommendation: ${recommendation}`}
        className={cn(
          "mt-3 px-4 py-1.5 text-sm font-semibold tracking-normal normal-case",
          STYLES[recommendation]
        )}
      >
        {recommendation}
      </Badge>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
        {explanation}
      </p>
    </div>
  );
}
