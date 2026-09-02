"use client";

import { motion } from "framer-motion";
import { Bot, LoaderCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { OrchestrationStage } from "@/features/agents/types/orchestration.types";
import { cn } from "@/lib/utils";

interface OrchestrationPanelProps {
  currentStage: OrchestrationStage | null;
  progressPercent: number;
}

export function OrchestrationPanel({
  currentStage,
  progressPercent,
}: OrchestrationPanelProps) {
  const isRunning = currentStage?.status === "running";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Card
        className={cn(
          "rounded-2xl border bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl",
          isRunning
            ? "border-primary/50 shadow-[0_0_24px_rgba(139,92,246,0.25)]"
            : "border-white/10"
        )}
      >
        <CardContent className="space-y-4 p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <span
                className={cn(
                  "flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/30 bg-primary/15 text-primary",
                  isRunning && "animate-pulse"
                )}
              >
                {isRunning ? (
                  <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" />
                ) : (
                  <Bot className="h-5 w-5" aria-hidden="true" />
                )}
              </span>
              <div>
                <h2 className="text-base font-semibold text-white">
                  {currentStage?.label || "No active agent"}
                </h2>
                <p className="text-xs text-muted-foreground">
                  {currentStage?.description ||
                    "Start the workflow to begin multi-agent orchestration."}
                </p>
              </div>
            </div>
            <Badge
              className={cn(
                "capitalize tracking-normal normal-case",
                isRunning
                  ? "border-sky-400/40 bg-sky-500/15 text-sky-200"
                  : "border-white/10 bg-white/5 text-muted-foreground"
              )}
            >
              {currentStage?.status || "idle"}
            </Badge>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Current Task</span>
              <span className="text-white">
                {currentStage?.currentTask || "—"}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Agent Progress</span>
              <span className="font-mono text-white">
                {currentStage?.progress ?? 0}%
              </span>
            </div>
            <Progress value={currentStage?.progress ?? 0} className="h-1.5" />
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Workflow Progress</span>
              <span className="font-mono text-white">{progressPercent}%</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
