"use client";

import { motion } from "framer-motion";
import { Cpu } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

interface PlanningHeaderProps {
  candidateName: string;
  engineStatus: string;
  planningProgress: number;
}

export function PlanningHeader({
  candidateName,
  engineStatus,
  planningProgress,
}: PlanningHeaderProps) {
  return (
    <motion.header
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between"
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="purple" className="gap-1.5">
            <Cpu className="h-3 w-3" aria-hidden="true" />
            Vox-1 Planning Engine
          </Badge>
          <span className="text-xs font-medium tracking-[0.12em] text-muted-foreground uppercase">
            Status: {engineStatus}
          </span>
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Interview Orchestration
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
          Configuring technical depth, question weights, and multi-agent
          personas for {candidateName}.
        </p>
      </div>

      <div className="w-full max-w-xs space-y-2">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Planning Progress
          </p>
          <span className="text-sm font-bold text-white">
            {planningProgress}%
          </span>
        </div>
        <Progress value={planningProgress} className="h-1.5" />
      </div>
    </motion.header>
  );
}
