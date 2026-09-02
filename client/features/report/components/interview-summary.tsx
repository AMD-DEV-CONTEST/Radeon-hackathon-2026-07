"use client";

import { motion } from "framer-motion";
import { Brain, Lightbulb } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { InterviewReport } from "@/features/report/types/report.types";

interface InterviewSummaryProps {
  summary: InterviewReport["summary"];
}

export function InterviewSummary({ summary }: InterviewSummaryProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.12 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="flex h-full flex-col gap-4 p-5 sm:p-6">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Summary
            </h3>
          </div>

          <div className="space-y-3 text-sm leading-relaxed text-muted-foreground">
            <p>
              <span className="font-medium text-white">Executive Summary. </span>
              {summary.executive}
            </p>
            <p>
              <span className="font-medium text-white">Overall Performance. </span>
              {summary.overallPerformance}
            </p>
            <p>
              <span className="font-medium text-white">AI Feedback. </span>
              {summary.aiFeedback}
            </p>
            <p>
              <span className="font-medium text-white">Final Recommendation. </span>
              {summary.finalRecommendation}
            </p>
          </div>

          <div className="mt-auto rounded-xl border border-primary/25 bg-primary/5 p-3">
            <div className="mb-1.5 flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-primary" aria-hidden="true" />
              <p className="text-xs font-semibold tracking-[0.12em] text-primary uppercase">
                Executive Note
              </p>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground italic">
              {summary.executiveNote}
            </p>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
