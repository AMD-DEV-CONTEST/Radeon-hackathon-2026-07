"use client";

import { useLaunchStore } from "@/stores/launchStore";
import { Badge } from "@/components/ui/Badge";
import { Clock, Activity, CheckCircle2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export function ExecutionTimeline() {
  const timeline = useLaunchStore((state) => state.timeline);
  const events =
    timeline.length > 0
      ? timeline
      : [
          { id: "1", timestamp: "10:05:22", agent: "Marketplace Syndication Engine", status: "completed", duration: 1.2 },
          { id: "2", timestamp: "10:05:20", agent: "Compliance & Policy Guard", status: "completed", duration: 4.5 },
          { id: "3", timestamp: "10:05:15", agent: "Multi-Channel Catalog Builder", status: "completed", duration: 8.7 },
          { id: "4", timestamp: "10:05:10", agent: "SEO & Keyword Generator", status: "completed", duration: 3.2 },
          { id: "5", timestamp: "10:05:08", agent: "Dynamic Pricing & Margin Agent", status: "completed", duration: 2.1 },
          { id: "6", timestamp: "10:05:06", agent: "Market Demand Analyzer", status: "completed", duration: 12.4 },
          { id: "7", timestamp: "10:04:50", agent: "Visual Intelligence Engine", status: "completed", duration: 5.8 },
          { id: "8", timestamp: "10:04:45", agent: "AI Launch Planner", status: "completed", duration: 2.3 },
        ];

  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl p-6 h-[680px] overflow-y-auto shadow-2xl relative transition-colors duration-200">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-[var(--color-border)]">
        <h3 className="text-base font-bold text-[var(--color-foreground)] flex items-center tracking-tight">
          <Clock className="w-5 h-5 mr-2.5 text-[var(--color-brand-primary)] animate-pulse" />
          Real-Time Execution Log
        </h3>
        <span className="px-3 py-1 rounded-full bg-[var(--color-brand-primary)]/15 border border-[var(--color-brand-primary)]/40 text-[var(--color-brand-primary)] text-[10px] font-bold uppercase tracking-wider shadow-[0_0_12px_rgba(237,28,36,0.2)]">
          ● Live Telemetry
        </span>
      </div>

      <div className="relative border-l-2 border-[var(--color-border)] ml-3 space-y-4">
        <AnimatePresence>
          {events.map((event: any, index) => (
            <motion.div
              key={event.id}
              initial={{ opacity: 0, x: -15 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.06 }}
              className="relative pl-6 group"
            >
              {/* Timeline Dot */}
              <span
                className={`absolute -left-[7px] top-2 h-3.5 w-3.5 rounded-full ring-4 ring-[var(--color-surface)] transition-transform group-hover:scale-125 ${
                  event.status === "completed"
                    ? "bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)]"
                    : "bg-[var(--color-brand-primary)] animate-pulse shadow-[0_0_10px_rgba(237,28,36,0.6)]"
                }`}
              />

              <div className="bg-[var(--color-surface-hover)]/60 border border-[var(--color-border)] group-hover:border-[var(--color-muted)] rounded-xl p-3.5 transition-all shadow-md backdrop-blur-md hover:bg-[var(--color-surface-hover)]">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-1.5 gap-1">
                  <h4 className="text-xs font-bold text-[var(--color-foreground)] flex items-center gap-1.5 tracking-tight">
                    {event.status === "completed" ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 inline" />
                    ) : (
                      <Activity className="w-3.5 h-3.5 text-amber-500 inline animate-spin" />
                    )}
                    {event.agent}
                  </h4>
                  <time className="text-[11px] text-[var(--color-muted)] font-medium">
                    {event.timestamp}
                  </time>
                </div>

                <div className="flex items-center justify-between mt-2 pt-2 border-t border-[var(--color-border)]">
                  <Badge
                    variant={event.status === "completed" ? "success" : "warning"}
                    className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 shadow-sm"
                  >
                    {event.status.toUpperCase()}
                  </Badge>
                  {event.duration && (
                    <span className="text-[11px] font-semibold text-neutral-300 bg-white/5 px-2.5 py-0.5 rounded-lg border border-white/10 shadow-inner">
                      ⏱️ {event.duration}s
                    </span>
                  )}
                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
