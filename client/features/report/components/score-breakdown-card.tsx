"use client";

import { motion } from "framer-motion";
import { BarChart3, Lightbulb } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { BehavioralScore } from "@/features/report/components/behavioral-score";
import { CommunicationScore } from "@/features/report/components/communication-score";
import { ConfidenceScore } from "@/features/report/components/confidence-score";
import { TechnicalScore } from "@/features/report/components/technical-score";
import type { ReportScores } from "@/features/report/types/report.types";

interface ScoreBreakdownCardProps {
  scores: ReportScores;
}

export function ScoreBreakdownCard({ scores }: ScoreBreakdownCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-4 flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Score Breakdown
            </h3>
          </div>

          <ul className="space-y-4" aria-label="Score breakdown">
            <TechnicalScore score={scores.technical} />
            <CommunicationScore score={scores.communication} />
            <BehavioralScore score={scores.leadership} label="Leadership" />
            <li className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <span className="inline-flex items-center gap-2 text-sm text-white">
                  <Lightbulb className="h-4 w-4 text-primary" aria-hidden="true" />
                  Problem Solving
                </span>
                <span className="text-sm font-semibold text-white">
                  {scores.problemSolving}%
                </span>
              </div>
              <Progress
                value={scores.problemSolving}
                className="h-1.5"
                aria-label={`Problem solving score ${scores.problemSolving} percent`}
              />
            </li>
            <ConfidenceScore score={scores.honesty} label="Honesty" />
          </ul>

          <div className="mt-5 grid grid-cols-2 gap-3 border-t border-white/5 pt-4">
            <div className="rounded-xl border border-white/5 bg-[#0f1018] px-3 py-2">
              <p className="text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                Behavioral
              </p>
              <p className="mt-1 text-lg font-semibold text-white">
                {scores.behavioral}%
              </p>
            </div>
            <div className="rounded-xl border border-white/5 bg-[#0f1018] px-3 py-2">
              <p className="text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                Confidence
              </p>
              <p className="mt-1 text-lg font-semibold text-white">
                {scores.confidence}%
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
