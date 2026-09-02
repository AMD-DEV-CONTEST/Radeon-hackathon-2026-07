"use client";

import { motion } from "framer-motion";
import { ClipboardList } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { PlanningSummary } from "@/features/interview/types/interview.types";

interface InterviewSummaryProps {
  summary: PlanningSummary;
}

export function InterviewSummary({ summary }: InterviewSummaryProps) {
  const items = [
    {
      label: "Estimated Duration",
      value: `${summary.estimatedDurationMinutes} min`,
    },
    {
      label: "Expected Questions",
      value: String(summary.expectedQuestionCount),
    },
    {
      label: "Difficulty",
      value: summary.difficulty,
    },
    {
      label: "Skill Coverage",
      value: `${summary.skillCoverage}%`,
    },
    {
      label: "Confidence Score",
      value: `${summary.confidenceScore}%`,
    },
  ] as const;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.12 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Generated Interview Plan
            </h2>
          </div>

          <dl className="grid grid-cols-2 gap-3">
            {items.map((item) => (
              <div
                key={item.label}
                className="rounded-xl border border-border/70 bg-[#0f1018] p-3"
              >
                <dt className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                  {item.label}
                </dt>
                <dd className="mt-1 text-sm font-semibold capitalize text-white">
                  {item.value}
                </dd>
              </div>
            ))}
          </dl>

          {summary.skillsToCover.length > 0 ? (
            <div className="mt-4">
              <p className="mb-2 text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                Skills To Cover
              </p>
              <ul className="flex flex-wrap gap-2" aria-label="Skills to cover">
                {summary.skillsToCover.map((skill) => (
                  <li
                    key={skill}
                    className="rounded-lg border border-border/70 bg-[#0f1018] px-2.5 py-1 text-xs text-muted-foreground"
                  >
                    {skill}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </motion.div>
  );
}
