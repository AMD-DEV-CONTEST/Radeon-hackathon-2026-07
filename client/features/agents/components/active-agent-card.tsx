"use client";

import { motion } from "framer-motion";
import { Bot, Cpu, MemoryStick } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  AgentCardData,
  AgentRuntimeStatus,
} from "@/features/agents/types/agents.types";
import { cn } from "@/lib/utils";

interface ActiveAgentCardProps {
  agent: AgentCardData;
  index?: number;
  isActive?: boolean;
}

const STATUS_CLASS: Record<AgentRuntimeStatus, string> = {
  idle: "border-border/70 bg-muted/30 text-muted-foreground",
  running: "border-sky-400/40 bg-sky-500/15 text-sky-200",
  busy: "border-cyan-400/40 bg-cyan-500/15 text-cyan-200",
  waiting: "border-amber-400/40 bg-amber-500/10 text-amber-200",
  error: "border-destructive/40 bg-destructive/15 text-destructive",
  completed: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
};

export function ActiveAgentCard({
  agent,
  index = 0,
  isActive = false,
}: ActiveAgentCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.04 * index }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card
        className={cn(
          "h-full rounded-2xl border bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl",
          isActive
            ? "border-primary/50 shadow-[0_0_24px_rgba(139,92,246,0.28)]"
            : "border-white/10"
        )}
      >
        <CardContent className="space-y-3 p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 text-primary",
                  isActive && "animate-pulse"
                )}
              >
                <Bot className="h-4 w-4" aria-hidden="true" />
              </span>
              <div>
                <p className="text-sm font-semibold text-white">{agent.name}</p>
                <p className="text-[11px] text-muted-foreground">
                  Updated {agent.lastUpdated}
                </p>
              </div>
            </div>
            <Badge
              className={cn(
                "tracking-normal normal-case capitalize",
                STATUS_CLASS[agent.status]
              )}
            >
              {agent.status}
            </Badge>
          </div>

          <p className="text-xs leading-relaxed text-muted-foreground">
            {agent.currentTask}
          </p>

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-white/5 bg-[#0f1018] px-2 py-1.5">
              <p className="text-muted-foreground">Exec</p>
              <p className="font-semibold text-white">{agent.executionTimeMs}ms</p>
            </div>
            <div className="rounded-lg border border-white/5 bg-[#0f1018] px-2 py-1.5">
              <p className="text-muted-foreground">Queue</p>
              <p className="font-semibold text-white">{agent.queueSize}</p>
            </div>
            <div className="rounded-lg border border-white/5 bg-[#0f1018] px-2 py-1.5">
              <p className="inline-flex items-center gap-1 text-muted-foreground">
                <MemoryStick className="h-3 w-3" aria-hidden="true" />
                Memory
              </p>
              <p className="font-semibold text-white">{agent.memoryMb}MB</p>
            </div>
            <div className="rounded-lg border border-white/5 bg-[#0f1018] px-2 py-1.5">
              <p className="inline-flex items-center gap-1 text-muted-foreground">
                <Cpu className="h-3 w-3" aria-hidden="true" />
                CPU
              </p>
              <p className="font-semibold text-white">{agent.cpuPercent}%</p>
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Confidence</span>
              <span className="text-white">{agent.confidence}%</span>
            </div>
            <Progress value={agent.confidence} className="h-1.5" />
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Success Rate</span>
              <span className="text-white">{agent.successRate}%</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
