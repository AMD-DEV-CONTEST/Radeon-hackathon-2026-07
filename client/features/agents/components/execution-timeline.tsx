"use client";

import { motion } from "framer-motion";
import { Timer } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { TimelineLane } from "@/features/agents/types/agents.types";
import { cn } from "@/lib/utils";

interface ExecutionTimelineProps {
  lanes: ReadonlyArray<TimelineLane>;
}

const PHASE_CLASS: Record<TimelineLane["phase"], string> = {
  done: "bg-slate-500/70",
  active: "bg-primary shadow-[0_0_16px_rgba(139,92,246,0.55)]",
  waiting: "border border-sky-400/40 bg-sky-500/10",
};

export function ExecutionTimeline({ lanes }: ExecutionTimelineProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.06 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Timer className="h-4 w-4 text-primary" aria-hidden="true" />
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Execution Timeline
              </h2>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary" className="tracking-normal normal-case">
                Done
              </Badge>
              <Badge
                className="border-primary/40 bg-primary/15 text-primary tracking-normal normal-case"
              >
                Active
              </Badge>
              <Badge
                className="border-sky-400/40 bg-sky-500/10 text-sky-200 tracking-normal normal-case"
              >
                Waiting
              </Badge>
            </div>
          </div>

          <ul className="space-y-3" aria-label="Execution timeline lanes">
            {lanes.map((lane, index) => {
              const width = Math.max(lane.end - lane.start, 4);
              return (
                <li key={lane.id} className="grid grid-cols-[140px_1fr] gap-3">
                  <p className="truncate font-mono text-[11px] text-muted-foreground">
                    {lane.label}
                  </p>
                  <div className="relative h-6 rounded-md bg-white/5">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${width}%` }}
                      transition={{ duration: 0.7, delay: 0.05 * index }}
                      className={cn(
                        "absolute top-1 h-4 rounded-sm",
                        PHASE_CLASS[lane.phase]
                      )}
                      style={{ left: `${lane.start}%` }}
                      role="img"
                      aria-label={`${lane.label} ${lane.phase} from ${lane.start} to ${lane.end}`}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
