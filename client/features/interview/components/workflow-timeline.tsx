"use client";

import { motion } from "framer-motion";
import {
  CheckCircle2,
  Code2,
  FileSearch,
  Flame,
  Link2,
  Network,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type {
  WorkflowStep,
  WorkflowStepStatus,
} from "@/features/interview/types/interview.types";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<WorkflowStep["icon"], LucideIcon> = {
  resume: FileSearch,
  planning: Link2,
  questions: Code2,
  difficulty: Flame,
  graph: Network,
  ready: Sparkles,
};

interface WorkflowTimelineProps {
  steps: ReadonlyArray<WorkflowStep>;
}

function stepStyles(status: WorkflowStepStatus): string {
  if (status === "completed") {
    return "border-primary/50 bg-primary/20 text-primary";
  }
  if (status === "active") {
    return "border-primary bg-primary text-white shadow-[0_0_24px_rgba(139,92,246,0.45)]";
  }
  return "border-border/70 bg-[#16161f] text-muted-foreground";
}

export function WorkflowTimeline({ steps }: WorkflowTimelineProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      whileHover={{ y: -2 }}
    >
      <Card className="overflow-hidden rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-0">
          <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-4">
            <div>
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                AI Agent Workflow Stream
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Real-time visualization of planning state transitions
              </p>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/30 bg-sky-400/10 px-2.5 py-1 text-[11px] font-semibold tracking-[0.12em] text-sky-300 uppercase">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-400" />
              Live Sync
            </div>
          </div>

          <div className="relative mx-5 mb-5 overflow-hidden rounded-xl border border-border/60">
            <div
              aria-hidden="true"
              className="aspect-[21/9] bg-[radial-gradient(circle_at_20%_40%,rgba(249,115,22,0.35),transparent_35%),radial-gradient(circle_at_70%_50%,rgba(139,92,246,0.28),transparent_40%),linear-gradient(135deg,#111827,#09090b)]"
            />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 opacity-40"
              style={{
                backgroundImage:
                  "linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)",
                backgroundSize: "28px 28px",
              }}
            />
          </div>

          <ol
            className="grid gap-4 px-5 pb-5 sm:grid-cols-3 xl:grid-cols-6"
            aria-label="Interview planning workflow"
          >
            {steps.map((step, index) => {
              const Icon = ICON_MAP[step.icon];
              const isActive = step.status === "active";
              const isCompleted = step.status === "completed";

              return (
                <motion.li
                  key={step.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: index * 0.05 }}
                  className="relative flex flex-col items-center text-center"
                >
                  {isCompleted ? (
                    <CheckCircle2
                      className="mb-2 h-4 w-4 text-sky-400"
                      aria-hidden="true"
                    />
                  ) : (
                    <span className="mb-2 h-4" />
                  )}

                  <div
                    className={cn(
                      "flex h-14 w-14 items-center justify-center rounded-full border-2 transition-colors",
                      stepStyles(step.status)
                    )}
                    aria-current={isActive ? "step" : undefined}
                  >
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </div>

                  <p className="mt-3 text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                    Step {step.step}
                  </p>
                  <p
                    className={cn(
                      "mt-1 text-xs font-semibold",
                      isActive ? "text-primary" : "text-white"
                    )}
                  >
                    {step.title}
                  </p>
                </motion.li>
              );
            })}
          </ol>
        </CardContent>
      </Card>
    </motion.div>
  );
}
