"use client";

import { motion } from "framer-motion";
import { Briefcase, FileText, Mail, UserRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { DashboardCandidate } from "@/features/dashboard/types/dashboard.types";

interface ProfileSummaryProps {
  candidate: DashboardCandidate;
}

export function ProfileSummary({ candidate }: ProfileSummaryProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-5 p-5">
          <div className="flex items-center gap-3">
            <div
              className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 to-blue-500 text-sm font-bold text-white"
              aria-hidden="true"
            >
              {candidate.avatarInitials}
            </div>
            <div className="min-w-0">
              <div className="mb-1 flex items-center gap-2">
                <UserRound className="h-4 w-4 text-primary" aria-hidden="true" />
                <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                  Profile Summary
                </h2>
              </div>
              <p className="truncate text-sm font-semibold text-white">
                {candidate.fullName}
              </p>
              {candidate.email ? (
                <p className="mt-1 inline-flex max-w-full items-center gap-1.5 text-xs text-muted-foreground">
                  <Mail className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span className="truncate">{candidate.email}</span>
                </p>
              ) : null}
            </div>
          </div>

          <div className="space-y-3">
            <div>
              <div className="mb-1.5 flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Resume Score</span>
                <span className="font-semibold text-white">
                  {candidate.resumeScore}%
                </span>
              </div>
              <Progress
                value={candidate.resumeScore}
                className="h-1.5"
                aria-label="Resume score"
              />
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Readiness Score</span>
                <span className="font-semibold text-white">
                  {candidate.readinessScore}%
                </span>
              </div>
              <Progress
                value={candidate.readinessScore}
                className="h-1.5"
                aria-label="Readiness score"
              />
            </div>
          </div>

          <div className="space-y-2 rounded-xl border border-white/5 bg-[#0f1018] p-3">
            <p className="inline-flex items-center gap-1.5 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
              <Briefcase className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              Preferred Role
            </p>
            <p className="text-sm font-medium text-white">
              {candidate.preferredRole || "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              Experience: {candidate.experienceLevel || "—"}
            </p>
            <p className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <FileText className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              Resume status
              <Badge variant="purple" className="ml-1 capitalize tracking-normal normal-case">
                {candidate.resumeStatus || "unknown"}
              </Badge>
            </p>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
