"use client";

import { motion } from "framer-motion";
import { FileText, MoreHorizontal } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  CandidatePipelineStatus,
  RecentCandidateRow,
  RecentInterviewRow,
} from "@/features/admin/types/admin.types";
import { cn } from "@/lib/utils";

interface CandidateTableProps {
  candidates: ReadonlyArray<RecentCandidateRow>;
  interviews: ReadonlyArray<RecentInterviewRow>;
}

const STATUS_CLASS: Record<CandidatePipelineStatus, string> = {
  interviewing: "border-sky-400/30 bg-sky-500/10 text-sky-200",
  evaluated: "border-primary/30 bg-primary/10 text-primary",
  hired: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
  rejected: "border-destructive/30 bg-destructive/10 text-destructive",
  pending: "border-amber-400/30 bg-amber-500/10 text-amber-200",
};

export function CandidateTable({
  candidates,
  interviews,
}: CandidateTableProps) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Recent Candidates
            </h2>
            <div className="overflow-x-auto">
              <table
                className="w-full min-w-[640px] text-left"
                aria-label="Recent candidates"
              >
                <thead>
                  <tr className="border-b border-white/10 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                    <th className="pb-3 pr-3 font-semibold">Candidate</th>
                    <th className="pb-3 pr-3 font-semibold">Position</th>
                    <th className="pb-3 pr-3 font-semibold">Score</th>
                    <th className="pb-3 pr-3 font-semibold">Status</th>
                    <th className="pb-3 pr-3 font-semibold">Report</th>
                    <th className="pb-3 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate) => (
                    <tr
                      key={candidate.id}
                      className="border-b border-white/5 last:border-b-0"
                    >
                      <td className="py-3 pr-3">
                        <div className="flex items-center gap-2">
                          <span
                            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-white"
                            aria-hidden="true"
                          >
                            {candidate.initials}
                          </span>
                          <span className="text-sm font-medium text-white">
                            {candidate.name}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 pr-3 text-sm text-muted-foreground">
                        {candidate.position}
                      </td>
                      <td className="py-3 pr-3">
                        <div className="min-w-[100px] space-y-1">
                          <span className="text-sm text-white">{candidate.score}</span>
                          <Progress value={candidate.score} className="h-1.5" />
                        </div>
                      </td>
                      <td className="py-3 pr-3">
                        <Badge
                          className={cn(
                            "tracking-normal normal-case capitalize",
                            STATUS_CLASS[candidate.status]
                          )}
                        >
                          {candidate.status}
                        </Badge>
                      </td>
                      <td className="py-3 pr-3">
                        <Link
                          href={`/interviews/report?id=${candidate.reportId}`}
                          className={cn(
                            buttonVariants({ variant: "outline", size: "sm" }),
                            "h-8"
                          )}
                          aria-label={`View report for ${candidate.name}`}
                        >
                          <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                          Report
                        </Link>
                      </td>
                      <td className="py-3">
                        <Link
                          href={`/candidates/dossier?id=${candidate.id}`}
                          className={cn(
                            buttonVariants({ variant: "ghost", size: "icon" }),
                            "h-8 w-8"
                          )}
                          aria-label={`Open actions for ${candidate.name}`}
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.05 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Recent Interviews
            </h2>
            <div className="overflow-x-auto">
              <table
                className="w-full min-w-[560px] text-left"
                aria-label="Recent interviews"
              >
                <thead>
                  <tr className="border-b border-white/10 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                    <th className="pb-3 pr-3 font-semibold">Candidate</th>
                    <th className="pb-3 pr-3 font-semibold">Interview</th>
                    <th className="pb-3 pr-3 font-semibold">Started At</th>
                    <th className="pb-3 pr-3 font-semibold">Duration</th>
                    <th className="pb-3 font-semibold">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {interviews.map((interview) => (
                    <tr
                      key={interview.id}
                      className="border-b border-white/5 last:border-b-0"
                    >
                      <td className="py-3 pr-3 text-sm font-medium text-white">
                        {interview.candidateName}
                      </td>
                      <td className="py-3 pr-3 text-sm text-muted-foreground">
                        {interview.interviewTitle}
                      </td>
                      <td className="py-3 pr-3 text-xs text-muted-foreground">
                        {new Intl.DateTimeFormat("en-US", {
                          dateStyle: "medium",
                          timeStyle: "short",
                        }).format(new Date(interview.startedAt))}
                      </td>
                      <td className="py-3 pr-3 text-sm text-white">
                        {interview.durationMinutes}m
                      </td>
                      <td className="py-3">
                        <Badge
                          variant="purple"
                          className="tracking-normal normal-case"
                        >
                          {interview.result}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
