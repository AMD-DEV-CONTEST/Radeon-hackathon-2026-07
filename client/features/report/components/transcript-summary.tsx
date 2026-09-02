"use client";

import { motion } from "framer-motion";
import { MessagesSquare } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { TranscriptHighlight } from "@/features/report/types/report.types";
import { cn } from "@/lib/utils";

interface TranscriptSummaryProps {
  highlights: ReadonlyArray<TranscriptHighlight>;
}

export function TranscriptSummary({ highlights }: TranscriptSummaryProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.14 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <MessagesSquare className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Transcript Highlights
            </h3>
          </div>

          <ul className="space-y-3" aria-label="Transcript highlights">
            {highlights.map((item, index) => (
              <motion.li
                key={item.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: 0.03 * index }}
                className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
              >
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Badge
                    variant="outline"
                    className={cn(
                      "tracking-normal normal-case",
                      item.speaker === "ai"
                        ? "border-primary/40 text-primary"
                        : "border-secondary/40 text-secondary"
                    )}
                  >
                    {item.speaker === "ai" ? "AI Agent" : "Candidate"}
                  </Badge>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {item.timestamp}
                  </span>
                  {item.tag ? (
                    <Badge variant="secondary" className="tracking-normal normal-case">
                      {item.tag}
                    </Badge>
                  ) : null}
                </div>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {item.text}
                </p>
              </motion.li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
