"use client";

import { motion } from "framer-motion";
import { Bot, CircleCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  AgentStatus,
  InterviewAgent,
} from "@/features/interview/types/interview.types";
import { cn } from "@/lib/utils";

interface AiAgentsPanelProps {
  agents: ReadonlyArray<InterviewAgent>;
}

function statusBadge(status: AgentStatus): string {
  if (status === "ready") return "Ready";
  if (status === "running") return "Running";
  if (status === "blocked") return "Blocked";
  return "Idle";
}

function statusClass(status: AgentStatus): string {
  if (status === "ready") {
    return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  }
  if (status === "running") {
    return "border-primary/40 bg-primary/15 text-primary";
  }
  if (status === "blocked") {
    return "border-destructive/40 bg-destructive/10 text-destructive";
  }
  return "border-border/70 bg-muted/40 text-muted-foreground";
}

export function AiAgentsPanel({ agents }: AiAgentsPanelProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              AI Agents Panel
            </h2>
          </div>

          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((agent, index) => (
              <motion.li
                key={agent.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: index * 0.04 }}
                whileHover={{ y: -2 }}
                className="rounded-xl border border-border/70 bg-[#0f1018] p-3 transition-colors hover:border-primary/30"
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-white">
                      {agent.name}
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                      {agent.description}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase",
                      statusClass(agent.status)
                    )}
                  >
                    {statusBadge(agent.status)}
                  </span>
                </div>

                <div className="mt-3 space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Progress</span>
                    <span className="font-medium text-white">
                      {agent.progress}%
                    </span>
                  </div>
                  <Progress value={agent.progress} className="h-1.5" />
                </div>

                <div className="mt-3 flex items-center gap-1.5 text-xs">
                  {agent.ready ? (
                    <>
                      <CircleCheck
                        className="h-3.5 w-3.5 text-emerald-400"
                        aria-hidden="true"
                      />
                      <span className="text-emerald-300">Ready</span>
                    </>
                  ) : (
                    <Badge variant="secondary" className="normal-case">
                      Preparing
                    </Badge>
                  )}
                </div>
              </motion.li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
