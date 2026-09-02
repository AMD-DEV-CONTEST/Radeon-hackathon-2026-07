"use client";

import { motion } from "framer-motion";
import { ArrowDown, GitBranch } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type {
  AgentRuntimeStatus,
  WorkflowNode,
  WorkflowNodeId,
} from "@/features/agents/types/agents.types";
import { cn } from "@/lib/utils";

interface WorkflowGraphProps {
  nodes: ReadonlyArray<WorkflowNode>;
  activeNodeId: WorkflowNodeId;
  logsPreview: ReadonlyArray<string>;
}

function nodeTone(status: AgentRuntimeStatus, isActive: boolean): string {
  if (isActive) {
    return "border-primary bg-primary/20 text-white shadow-[0_0_20px_rgba(139,92,246,0.45)]";
  }
  if (status === "completed") {
    return "border-emerald-400/30 bg-emerald-500/10 text-emerald-100";
  }
  if (status === "busy" || status === "running") {
    return "border-sky-400/40 bg-sky-500/10 text-sky-100";
  }
  if (status === "waiting") {
    return "border-amber-400/30 bg-amber-500/10 text-amber-100";
  }
  return "border-white/10 bg-[#0f1018] text-muted-foreground";
}

export function WorkflowGraph({
  nodes,
  activeNodeId,
  logsPreview,
}: WorkflowGraphProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              LangGraph Workflow Trace
            </h2>
          </div>

          <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
            <div
              className="rounded-xl border border-white/10 bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-emerald-300/90"
              aria-label="Workflow system log preview"
            >
              {logsPreview.map((line) => (
                <p key={line} className="truncate">
                  {line}
                </p>
              ))}
            </div>

            <ol
              className="flex flex-col items-stretch gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between"
              aria-label="Agent workflow graph"
            >
              {nodes.map((node, index) => {
                const isActive = node.id === activeNodeId;

                return (
                  <li
                    key={node.id}
                    className="flex flex-1 flex-col items-center sm:min-w-[96px]"
                  >
                    <motion.div
                      animate={
                        isActive
                          ? { scale: [1, 1.05, 1], opacity: [1, 0.92, 1] }
                          : node.status === "completed"
                            ? { scale: 1, opacity: 1 }
                            : { scale: 1, opacity: 0.85 }
                      }
                      transition={
                        isActive
                          ? { duration: 1.4, repeat: Infinity }
                          : { duration: 0.35 }
                      }
                      className={cn(
                        "w-full rounded-xl border px-3 py-3 text-center text-xs font-semibold tracking-[0.08em] uppercase",
                        nodeTone(node.status, isActive)
                      )}
                      aria-current={isActive ? "step" : undefined}
                    >
                      {node.label}
                    </motion.div>
                    {index < nodes.length - 1 ? (
                      <ArrowDown
                        className="my-1 h-4 w-4 text-muted-foreground sm:hidden"
                        aria-hidden="true"
                      />
                    ) : null}
                    {index < nodes.length - 1 ? (
                      <div
                        className="mt-2 hidden h-px w-full border-t border-dashed border-white/20 sm:block"
                        aria-hidden="true"
                      />
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
