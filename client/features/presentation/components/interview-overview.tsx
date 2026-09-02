"use client";

import { motion } from "framer-motion";
import { LayoutDashboard } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { PresentationCandidate } from "@/features/presentation/types/presentation.types";

interface InterviewOverviewProps {
  candidate: PresentationCandidate;
  durationMinutes: number;
  totalQuestions: number;
  reportId: string;
}

export function InterviewOverview({
  candidate,
  durationMinutes,
  totalQuestions,
  reportId,
}: InterviewOverviewProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.06 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            <LayoutDashboard className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Overview
            </h2>
          </div>

          <dl className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3 border-b border-white/5 pb-2">
              <dt className="text-muted-foreground">Candidate</dt>
              <dd className="font-medium text-white">{candidate.fullName}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-b border-white/5 pb-2">
              <dt className="text-muted-foreground">Role</dt>
              <dd className="font-medium text-white">{candidate.appliedRole}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-b border-white/5 pb-2">
              <dt className="text-muted-foreground">Company</dt>
              <dd className="font-medium text-white">{candidate.company}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-b border-white/5 pb-2">
              <dt className="text-muted-foreground">Duration</dt>
              <dd className="font-medium text-white">{durationMinutes} minutes</dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-b border-white/5 pb-2">
              <dt className="text-muted-foreground">Questions</dt>
              <dd className="font-medium text-white">{totalQuestions}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">Report ID</dt>
              <dd className="font-mono text-xs text-primary">{reportId}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </motion.div>
  );
}
