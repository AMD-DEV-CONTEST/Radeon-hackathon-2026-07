"use client";

import { motion } from "framer-motion";
import { ListChecks } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type {
  AgentCardData,
  AgentRuntimeStatus,
} from "@/features/agents/types/agents.types";
import { cn } from "@/lib/utils";

interface AgentStatusListProps {
  agents: ReadonlyArray<AgentCardData>;
  activeNodeId: string;
}

const STATUS_CLASS: Record<AgentRuntimeStatus, string> = {
  idle: "border-border/70 bg-muted/30 text-muted-foreground",
  running: "border-sky-400/40 bg-sky-500/15 text-sky-200",
  busy: "border-cyan-400/40 bg-cyan-500/15 text-cyan-200",
  waiting: "border-amber-400/40 bg-amber-500/10 text-amber-200",
  error: "border-destructive/40 bg-destructive/15 text-destructive",
  completed: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
};

export function AgentStatusList({
  agents,
  activeNodeId,
}: AgentStatusListProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Agent Status List
            </h2>
          </div>

          <ul className="space-y-2" aria-label="Compact agent status list">
            {agents.map((agent, index) => {
              const isActive = agent.id === activeNodeId;
              return (
                <motion.li
                  key={agent.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: 0.02 * index }}
                  className={cn(
                    "flex items-center justify-between gap-3 rounded-xl border px-3 py-2",
                    isActive
                      ? "border-primary/40 bg-primary/10"
                      : "border-white/5 bg-[#0f1018]"
                  )}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-white">
                      {agent.name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {agent.currentTask}
                    </p>
                  </div>
                  <Badge
                    className={cn(
                      "shrink-0 tracking-normal normal-case capitalize",
                      STATUS_CLASS[agent.status]
                    )}
                  >
                    {agent.status}
                  </Badge>
                </motion.li>
              );
            })}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
