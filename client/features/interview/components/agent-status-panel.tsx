"use client";

import { motion } from "framer-motion";
import { Bot } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  RoomAgent,
  RoomAgentStatus,
} from "@/features/interview/types/interview.types";
import { cn } from "@/lib/utils";

interface AgentStatusPanelProps {
  agents: ReadonlyArray<RoomAgent>;
}

function statusClass(status: RoomAgentStatus): string {
  if (status === "active") {
    return "border-primary/40 bg-primary/15 text-primary";
  }
  if (status === "completed") {
    return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  }
  return "border-border/70 bg-muted/30 text-muted-foreground";
}

export function AgentStatusPanel({ agents }: AgentStatusPanelProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/85 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Agent Status Panel
            </h2>
          </div>

          <ul className="space-y-3" aria-label="AI agent statuses">
            {agents.map((agent, index) => (
              <motion.li
                key={agent.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: index * 0.03 }}
                className="rounded-xl border border-border/70 bg-[#0f1018] p-3"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-white">
                      {agent.name}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {agent.currentTask}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize",
                      statusClass(agent.status)
                    )}
                  >
                    {agent.status}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Progress</span>
                  <span className="text-white">{agent.progress}%</span>
                </div>
                <Progress value={agent.progress} className="mt-1.5 h-1.5" />
              </motion.li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
