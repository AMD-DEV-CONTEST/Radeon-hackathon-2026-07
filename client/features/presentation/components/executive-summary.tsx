"use client";

import { motion } from "framer-motion";
import { Brain, CheckCircle2, Clock3, HelpCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type {
  CompletionStatus,
} from "@/features/presentation/types/presentation.types";

interface ExecutiveSummaryProps {
  summary: string;
  durationMinutes: number;
  totalQuestions: number;
  completionStatus: CompletionStatus;
}

export function ExecutiveSummary({
  summary,
  durationMinutes,
  totalQuestions,
  completionStatus,
}: ExecutiveSummaryProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.05 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-5 p-5 sm:p-6">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Executive Summary
            </h2>
          </div>

          <p className="text-sm leading-relaxed text-muted-foreground">
            {summary}
          </p>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-white/5 bg-[#0f1018] px-3 py-3">
              <p className="inline-flex items-center gap-1.5 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                <Clock3 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                Duration
              </p>
              <p className="mt-2 text-xl font-bold text-white">
                {durationMinutes}m
              </p>
            </div>
            <div className="rounded-xl border border-white/5 bg-[#0f1018] px-3 py-3">
              <p className="inline-flex items-center gap-1.5 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                <HelpCircle className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                Questions
              </p>
              <p className="mt-2 text-xl font-bold text-white">{totalQuestions}</p>
            </div>
            <div className="rounded-xl border border-white/5 bg-[#0f1018] px-3 py-3">
              <p className="inline-flex items-center gap-1.5 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                <CheckCircle2 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                Status
              </p>
              <Badge
                variant="purple"
                className="mt-2 tracking-normal normal-case capitalize"
              >
                {completionStatus}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
