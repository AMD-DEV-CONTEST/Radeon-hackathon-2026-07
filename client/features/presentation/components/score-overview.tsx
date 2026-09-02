"use client";

import { motion } from "framer-motion";
import {
  Cpu,
  Handshake,
  Lightbulb,
  MessageSquare,
  ShieldCheck,
  Users,
} from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { PresentationScores } from "@/features/presentation/types/presentation.types";

interface ScoreOverviewProps {
  scores: PresentationScores;
}

const METRICS = [
  { key: "technical", label: "Technical", icon: Cpu },
  { key: "communication", label: "Communication", icon: MessageSquare },
  { key: "behavioral", label: "Behavioral", icon: Users },
  { key: "confidence", label: "Confidence", icon: ShieldCheck },
  { key: "problemSolving", label: "Problem Solving", icon: Lightbulb },
  { key: "collaboration", label: "Collaboration", icon: Handshake },
] as const;

export function ScoreOverview({ scores }: ScoreOverviewProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Performance Metrics
          </h2>
          <ul
            className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
            aria-label="Performance metrics"
          >
            {METRICS.map((metric, index) => {
              const Icon = metric.icon;
              const value = scores[metric.key];
              return (
                <motion.li
                  key={metric.key}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: 0.04 * index }}
                  className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-2 text-sm text-white">
                      <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                      {metric.label}
                    </span>
                    <span className="text-sm font-semibold text-white">
                      {value}%
                    </span>
                  </div>
                  <Progress
                    value={value}
                    className="h-1.5"
                    aria-label={`${metric.label} score ${value} percent`}
                  />
                </motion.li>
              );
            })}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
