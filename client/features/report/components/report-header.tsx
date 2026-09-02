"use client";

import { motion } from "framer-motion";
import { CalendarClock, Clock3, Hash } from "lucide-react";

import { HiringRecommendation } from "@/features/report/components/hiring-recommendation";
import type { InterviewReport } from "@/features/report/types/report.types";

interface ReportHeaderProps {
  report: InterviewReport;
}

function formatConductedAt(iso: string): string {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function ReportHeader({ report }: ReportHeaderProps) {
  return (
    <motion.header
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between"
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <HiringRecommendation recommendation={report.recommendation} />
          <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
            <Hash className="h-3.5 w-3.5" aria-hidden="true" />
            {report.interviewId}
          </span>
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Interview Report
          </h1>
          <p className="mt-1 text-base text-muted-foreground">
            {report.interviewTitle}
          </p>
        </div>
        <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          <span className="inline-flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-primary" aria-hidden="true" />
            <span>{formatConductedAt(report.conductedAt)}</span>
          </span>
          <span className="inline-flex items-center gap-2">
            <Clock3 className="h-4 w-4 text-primary" aria-hidden="true" />
            <span>{report.durationMinutes}m session</span>
          </span>
          <span className="text-white">{report.candidate.fullName}</span>
        </div>
      </div>
    </motion.header>
  );
}
