"use client";

import { motion } from "framer-motion";
import { ArrowDown, CircleDot, Workflow } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type {
  PipelineStage,
  PipelineStageStatus,
} from "@/features/presentation/types/presentation.types";
import { cn } from "@/lib/utils";

interface HiringPipelineProps {
  stages: ReadonlyArray<PipelineStage>;
}

const STATUS_CLASS: Record<PipelineStageStatus, string> = {
  completed: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
  active:
    "border-primary/40 bg-primary/15 text-primary shadow-[0_0_16px_rgba(139,92,246,0.35)]",
  upcoming: "border-border/70 bg-muted/30 text-muted-foreground",
};

export function HiringPipeline({ stages }: HiringPipelineProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.14 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-4 flex items-center gap-2">
            <Workflow className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Evaluation Pipeline
            </h2>
          </div>

          <ol
            className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-stretch lg:justify-between"
            aria-label="Hiring evaluation pipeline"
          >
            {stages.map((stage, index) => (
              <li
                key={stage.id}
                className="flex flex-1 flex-col items-center lg:min-w-[120px]"
              >
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: 0.04 * index }}
                  className={cn(
                    "w-full rounded-xl border px-3 py-3 text-center",
                    STATUS_CLASS[stage.status]
                  )}
                  aria-current={stage.status === "active" ? "step" : undefined}
                >
                  <div className="mb-1 flex items-center justify-center gap-1.5">
                    <CircleDot className="h-3.5 w-3.5" aria-hidden="true" />
                    <Badge
                      className="tracking-normal normal-case capitalize"
                      variant="outline"
                    >
                      {stage.status}
                    </Badge>
                  </div>
                  <p className="text-xs font-semibold text-white">{stage.label}</p>
                  {stage.completedAt ? (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {stage.completedAt}
                    </p>
                  ) : null}
                </motion.div>
                {index < stages.length - 1 ? (
                  <ArrowDown
                    className="my-1 h-4 w-4 text-muted-foreground lg:hidden"
                    aria-hidden="true"
                  />
                ) : null}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </motion.div>
  );
}
