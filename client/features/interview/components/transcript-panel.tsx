"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useTranscript } from "@/features/interview/hooks/use-transcript";
import { cn } from "@/lib/utils";

export function TranscriptPanel() {
  const { transcript } = useTranscript();
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [transcript]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.05 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/85 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Live Transcription Stream
            </h2>
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/30 bg-sky-400/10 px-2.5 py-1 text-[11px] font-semibold tracking-[0.12em] text-sky-300 uppercase">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-400" />
              Syncing In Real-Time
            </div>
          </div>

          <div
            className="max-h-[340px] space-y-3 overflow-y-auto pr-1 scrollbar-thin"
            role="log"
            aria-live="polite"
            aria-relevant="additions"
            aria-label="Live interview transcript"
          >
            <AnimatePresence initial={false}>
              {transcript.map((entry) => {
                const isAi = entry.speaker === "ai";

                return (
                  <motion.article
                    key={entry.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25 }}
                    className={cn(
                      "rounded-xl border px-3 py-3",
                      isAi
                        ? "border-sky-400/20 bg-sky-400/5"
                        : "border-primary/20 bg-primary/5"
                    )}
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <p
                        className={cn(
                          "text-[11px] font-semibold tracking-[0.12em] uppercase",
                          isAi ? "text-sky-300" : "text-primary"
                        )}
                      >
                        {entry.speakerLabel}
                      </p>
                      <span className="text-[11px] text-muted-foreground">
                        {entry.timestamp}
                      </span>
                      {typeof entry.accuracy === "number" ? (
                        <Badge variant="secondary" className="normal-case">
                          Accuracy: {entry.accuracy}%
                        </Badge>
                      ) : null}
                    </div>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {entry.content}
                    </p>
                  </motion.article>
                );
              })}
            </AnimatePresence>
            <div ref={endRef} />
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
