"use client";

import { motion } from "framer-motion";
import { Hash, Timer } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { HiringRecommendation } from "@/features/report/components/hiring-recommendation";
import type { InterviewReport } from "@/features/report/types/report.types";

interface OverallScoreCardProps {
  report: InterviewReport;
}

export function OverallScoreCard({ report }: OverallScoreCardProps) {
  const { candidate, scores, recommendation, performanceConfidence, insightQuote } =
    report;

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="flex h-full flex-col gap-5 p-5 sm:p-6">
          <div className="flex items-start gap-4">
            <div
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 to-blue-500 text-base font-bold text-white"
              aria-hidden="true"
            >
              {candidate.avatarInitials}
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-lg font-semibold text-white">
                {candidate.fullName}
              </h2>
              <p className="truncate text-sm text-muted-foreground">
                {candidate.title}
              </p>
              <div className="mt-2 flex flex-wrap gap-3 text-[11px] tracking-[0.08em] text-muted-foreground uppercase">
                <span className="inline-flex items-center gap-1">
                  <Hash className="h-3 w-3" aria-hidden="true" />
                  {report.interviewId}
                </span>
                <span className="inline-flex items-center gap-1">
                  <Timer className="h-3 w-3" aria-hidden="true" />
                  {report.durationMinutes}M SESSION
                </span>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs tracking-[0.14em] text-muted-foreground uppercase">
                Overall Score
              </p>
              <p
                className="mt-1 text-4xl font-bold tracking-tight text-white"
                aria-label={`Overall score ${scores.overall} out of 100`}
              >
                {scores.overall}
                <span className="text-xl font-semibold text-muted-foreground">
                  {" "}
                  /100
                </span>
              </p>
            </div>
            <HiringRecommendation recommendation={recommendation} />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Performance Confidence</span>
              <span className="font-semibold text-white">
                {performanceConfidence.toFixed(1)}%
              </span>
            </div>
            <Progress
              value={performanceConfidence}
              className="h-1.5"
              aria-label="Performance confidence"
            />
          </div>

          <blockquote className="mt-auto border-l-2 border-primary/50 pl-3 text-sm leading-relaxed text-muted-foreground italic">
            {insightQuote}
          </blockquote>
        </CardContent>
      </Card>
    </motion.div>
  );
}
