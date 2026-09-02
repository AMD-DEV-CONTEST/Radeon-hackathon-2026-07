"use client";

import { motion } from "framer-motion";
import { Brain, GraduationCap, Target } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

interface AiSummaryCardProps {
  summary: string;
  experienceSummary: string;
  educationSummary: string;
  readinessScore: number;
  recommendedFocus: ReadonlyArray<string>;
}

export function AiSummaryCard({
  summary,
  experienceSummary,
  educationSummary,
  readinessScore,
  recommendedFocus,
}: AiSummaryCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-5 p-5">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              AI Summary
            </h3>
          </div>

          <p className="text-sm leading-relaxed text-muted-foreground">
            {summary || "Run resume analysis to generate an AI summary."}
          </p>

          {experienceSummary ? (
            <div className="rounded-xl border border-border/70 bg-[#0f1018] p-3">
              <p className="mb-1.5 text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                Experience Summary
              </p>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {experienceSummary}
              </p>
            </div>
          ) : null}

          {educationSummary ? (
            <div className="rounded-xl border border-border/70 bg-[#0f1018] p-3">
              <div className="mb-1.5 flex items-center gap-2">
                <GraduationCap className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                <p className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                  Education Summary
                </p>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {educationSummary}
              </p>
            </div>
          ) : null}

          <div className="rounded-xl border border-primary/25 bg-primary/5 p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-xs font-semibold tracking-[0.12em] text-primary uppercase">
                Interview Readiness Score
              </p>
              <span className="text-sm font-bold text-white">
                {readinessScore}%
              </span>
            </div>
            <Progress value={readinessScore} className="h-2" />
          </div>

          <div>
            <div className="mb-2 flex items-center gap-2">
              <Target className="h-4 w-4 text-primary" aria-hidden="true" />
              <p className="text-xs font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                Suggested Interview Focus
              </p>
            </div>
            {recommendedFocus.length > 0 ? (
              <ul className="space-y-2">
                {recommendedFocus.map((focus) => (
                  <li
                    key={focus}
                    className="rounded-lg border border-border/70 bg-[#0f1018] px-3 py-2 text-sm text-muted-foreground"
                  >
                    {focus}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                No suggested focus areas yet.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
