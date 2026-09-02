"use client";

import { motion } from "framer-motion";
import { Check, Circle, ListChecks } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { ChecklistItem } from "@/features/interview/types/interview.types";
import { cn } from "@/lib/utils";

interface InterviewChecklistProps {
  items: ReadonlyArray<ChecklistItem>;
}

export function InterviewChecklist({ items }: InterviewChecklistProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Pre-Interview Checklist
            </h2>
          </div>

          <ul className="space-y-2.5" aria-label="Interview readiness checklist">
            {items.map((item) => (
              <li
                key={item.id}
                className="flex items-center gap-3 rounded-xl border border-border/70 bg-[#0f1018] px-3 py-2.5"
              >
                <span
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded-full border",
                    item.completed
                      ? "border-emerald-400/40 bg-emerald-400/15 text-emerald-300"
                      : "border-border text-muted-foreground"
                  )}
                  aria-hidden="true"
                >
                  {item.completed ? (
                    <Check className="h-3 w-3" />
                  ) : (
                    <Circle className="h-3 w-3" />
                  )}
                </span>
                <span
                  className={cn(
                    "text-sm",
                    item.completed ? "text-white" : "text-muted-foreground"
                  )}
                >
                  {item.label}
                </span>
                <span className="sr-only">
                  {item.completed ? "Completed" : "Incomplete"}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
