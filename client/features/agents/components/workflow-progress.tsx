"use client";

import { motion } from "framer-motion";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  OrchestrationStage,
  OrchestrationWorkflowStatus,
} from "@/features/agents/types/orchestration.types";
import { cn } from "@/lib/utils";

interface WorkflowProgressProps {
  progressPercent: number;
  status: OrchestrationWorkflowStatus;
  stages: ReadonlyArray<OrchestrationStage>;
  currentStageLabel?: string | null;
}

export function WorkflowProgress({
  progressPercent,
  status,
  stages,
  currentStageLabel,
}: WorkflowProgressProps) {
  const completedCount = stages.filter(
    (stage) => stage.status === "completed" || stage.status === "skipped"
  ).length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Workflow Progress
              </h2>
              <p className="mt-1 text-sm text-white">
                {currentStageLabel || "Waiting for orchestration"}
              </p>
            </div>
            <div className="text-right">
              <p className="font-mono text-2xl font-semibold text-white">
                {progressPercent}%
              </p>
              <p className="text-xs text-muted-foreground capitalize">
                {status.replace("_", " ")} · {completedCount}/{stages.length}
              </p>
            </div>
          </div>

          <Progress value={progressPercent} className="h-2" />

          <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            {stages.map((stage) => (
              <li
                key={stage.id}
                className={cn(
                  "rounded-xl border px-3 py-2 text-[11px]",
                  stage.status === "running" &&
                    "border-primary/50 bg-primary/10 text-white",
                  stage.status === "completed" &&
                    "border-emerald-400/30 bg-emerald-500/10 text-emerald-100",
                  stage.status === "failed" &&
                    "border-destructive/40 bg-destructive/10 text-destructive",
                  stage.status === "pending" &&
                    "border-white/10 bg-[#0f1018] text-muted-foreground",
                  stage.status === "cancelled" &&
                    "border-amber-400/30 bg-amber-500/10 text-amber-100"
                )}
              >
                <p className="truncate font-semibold">{stage.label}</p>
                <p className="mt-1 capitalize opacity-80">{stage.status}</p>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </motion.div>
  );
}
