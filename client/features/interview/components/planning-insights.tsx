"use client";

import { motion } from "framer-motion";
import {
  Crosshair,
  Lightbulb,
  TriangleAlert,
  Zap,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  InterviewPlan,
  PlanningCandidate,
} from "@/features/interview/types/interview.types";

interface PlanningInsightsProps {
  candidate: PlanningCandidate;
  insights: InterviewPlan["insights"];
}

export function PlanningInsights({
  candidate,
  insights,
}: PlanningInsightsProps) {
  return (
    <div className="space-y-4">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-primary/30 bg-primary/15 text-sm font-bold text-primary">
                {candidate.avatarInitials}
              </div>
              <div>
                <h2 className="text-base font-semibold text-white">
                  {candidate.fullName}
                </h2>
                <p className="text-xs text-muted-foreground">
                  Candidate ID: {candidate.id}
                </p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant="secondary">{candidate.level}</Badge>
              <Badge variant="purple" className="normal-case tracking-normal">
                {candidate.percentileLabel}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.05 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <div className="mb-3 flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-primary" aria-hidden="true" />
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                AI Suggestions
              </h2>
            </div>
            <ul className="space-y-2">
              {insights.suggestions.map((suggestion) => (
                <li
                  key={suggestion}
                  className="rounded-xl border border-border/70 bg-[#0f1018] px-3 py-2 text-sm leading-relaxed text-muted-foreground"
                >
                  {suggestion}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.08 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="grid gap-4 p-5 sm:grid-cols-2">
            <div>
              <div className="mb-3 flex items-center gap-2">
                <Crosshair className="h-4 w-4 text-sky-400" aria-hidden="true" />
                <h3 className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                  Strengths
                </h3>
              </div>
              <ul className="space-y-3">
                {insights.strengths.map((item) => (
                  <li key={item.label} className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-white">{item.label}</span>
                      <span className="text-sky-300">{item.value}%</span>
                    </div>
                    <Progress
                      value={item.value}
                      className="h-1.5"
                      indicatorClassName="bg-sky-400"
                    />
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-3 flex items-center gap-2">
                <TriangleAlert
                  className="h-4 w-4 text-destructive"
                  aria-hidden="true"
                />
                <h3 className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                  Gaps
                </h3>
              </div>
              <ul className="space-y-3">
                {insights.gaps.map((item) => (
                  <li key={item.label} className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-white">{item.label}</span>
                      <span className="text-destructive">{item.value}%</span>
                    </div>
                    <Progress
                      value={item.value}
                      className="h-1.5"
                      indicatorClassName="bg-destructive"
                    />
                  </li>
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.11 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="space-y-4 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-primary" aria-hidden="true" />
                <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                  Interview Strategy
                </h2>
              </div>
              <Badge variant="secondary">Adaptive Pathing Active</Badge>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground italic">
              “{insights.strategy}”
            </p>
            <div className="rounded-xl border border-primary/25 bg-primary/5 p-3">
              <p className="text-[11px] font-semibold tracking-[0.14em] text-primary uppercase">
                Vox-1 Recommendation
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                {insights.recommendation}
              </p>
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
