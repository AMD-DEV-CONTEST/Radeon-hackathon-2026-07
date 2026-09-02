"use client";

import { motion } from "framer-motion";

import { Card, CardContent } from "@/components/ui/card";
import type { PlanningCandidate } from "@/features/interview/types/interview.types";

interface InterviewOverviewProps {
  candidate: PlanningCandidate;
}

export function InterviewOverview({ candidate }: InterviewOverviewProps) {
  const stats = [
    { label: "Candidate", value: candidate.fullName },
    { label: "Selected Role", value: candidate.selectedRole || "—" },
    { label: "Resume Score", value: `${candidate.resumeScore}%` },
    { label: "AI Readiness Score", value: `${candidate.readinessScore}%` },
    {
      label: "Resume",
      value: candidate.resumeFileName || candidate.resumeStatus || "—",
    },
    {
      label: "Resume Status",
      value: candidate.resumeStatus || "unknown",
    },
  ] as const;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.04 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="rounded-xl border border-border/70 bg-[#0f1018] px-3 py-3"
            >
              <p className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                {stat.label}
              </p>
              <p className="mt-1 truncate text-sm font-semibold text-white">
                {stat.value}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
    </motion.div>
  );
}
