"use client";

import { motion } from "framer-motion";
import { History } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { InterviewHistoryItem } from "@/features/dashboard/types/dashboard.types";

interface InterviewHistoryProps {
  history: ReadonlyArray<InterviewHistoryItem>;
}

export function InterviewHistory({ history }: InterviewHistoryProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.12 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <History className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview History
            </h2>
          </div>

          {history.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No interview history available yet.
            </p>
          ) : (
            <ul className="space-y-3" aria-label="Interview history">
              {history.map((item, index) => (
                <motion.li
                  key={item.id}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.22, delay: 0.03 * index }}
                  className="flex items-start justify-between gap-3 rounded-xl border border-white/5 bg-[#0f1018] p-3"
                >
                  <div>
                    <p className="text-sm font-medium text-white">{item.title}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {item.date} · {item.durationMinutes}m
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold text-white">
                      {item.score}
                    </p>
                    <Badge
                      variant="secondary"
                      className="mt-1 tracking-normal normal-case capitalize"
                    >
                      {item.status}
                    </Badge>
                  </div>
                </motion.li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
