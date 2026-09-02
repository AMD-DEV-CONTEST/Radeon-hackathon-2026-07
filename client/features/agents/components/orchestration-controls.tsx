"use client";

import { motion } from "framer-motion";
import { Play, Square, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { OrchestrationFinalResult } from "@/features/agents/types/orchestration.types";

interface OrchestrationControlsProps {
  canStart: boolean;
  canFinalize: boolean;
  canRetry: boolean;
  canCancel: boolean;
  isRunning: boolean;
  finalResult: OrchestrationFinalResult;
  onStart: () => void;
  onFinalize: () => void;
  onRetry: () => void;
  onCancel: () => void;
}

export function OrchestrationControls({
  canStart,
  canFinalize,
  canRetry,
  canCancel,
  isRunning,
  finalResult,
  onStart,
  onFinalize,
  onRetry,
  onCancel,
}: OrchestrationControlsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.04 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5">
          <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Orchestration Controls
          </h2>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              className="glow-purple"
              disabled={!canStart || isRunning}
              onClick={onStart}
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              Start Workflow
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!canFinalize || isRunning}
              onClick={onFinalize}
            >
              Finalize Report
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!canRetry || isRunning}
              onClick={onRetry}
            >
              <Undo2 className="h-4 w-4" aria-hidden="true" />
              Retry
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={!canCancel || isRunning}
              onClick={onCancel}
            >
              <Square className="h-4 w-4" aria-hidden="true" />
              Cancel
            </Button>
          </div>

          <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
            <p>
              Interview:{" "}
              <span className="font-mono text-white">
                {finalResult.interviewId || "—"}
              </span>
            </p>
            <p>
              Report:{" "}
              <span className="font-mono text-white">
                {finalResult.reportId || "—"}
              </span>
            </p>
            <p>
              Plan:{" "}
              <span className="font-mono text-white">
                {finalResult.planId || "—"}
              </span>
            </p>
            <p>
              Recommendation:{" "}
              <span className="text-white">
                {finalResult.recommendation || "—"}
              </span>
            </p>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
