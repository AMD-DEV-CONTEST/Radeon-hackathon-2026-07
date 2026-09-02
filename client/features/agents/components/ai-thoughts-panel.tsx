"use client";

import { motion } from "framer-motion";
import { Brain } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { AiThought } from "@/features/agents/types/orchestration.types";

interface AiThoughtsPanelProps {
  thoughts: ReadonlyArray<AiThought>;
}

export function AiThoughtsPanel({ thoughts }: AiThoughtsPanelProps) {
  const latest = [...thoughts].slice(-6).reverse();

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.05 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Brain className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              AI Thoughts
            </h2>
          </div>

          {latest.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Agent thoughts will appear as the workflow advances.
            </p>
          ) : (
            <ul className="space-y-3" aria-label="AI agent thoughts">
              {latest.map((thought, index) => (
                <motion.li
                  key={thought.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: 0.03 * index }}
                  className="rounded-xl border border-white/10 bg-[#0f1018] px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-white">
                      {thought.agentName}
                    </p>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {new Intl.DateTimeFormat("en-US", {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      }).format(new Date(thought.at))}
                    </p>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {thought.thought}
                  </p>
                </motion.li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
