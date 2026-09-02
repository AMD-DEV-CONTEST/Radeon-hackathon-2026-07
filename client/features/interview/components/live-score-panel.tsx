"use client";

import { motion } from "framer-motion";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import {
  Brain,
  MessageSquare,
  Monitor,
  Shield,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  LiveMetric,
  LiveMetricPoint,
} from "@/features/interview/types/interview.types";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<LiveMetric["icon"], LucideIcon> = {
  technical: Monitor,
  communication: MessageSquare,
  confidence: Sparkles,
  leadership: Shield,
  quality: Brain,
};

interface LiveScorePanelProps {
  metrics: ReadonlyArray<LiveMetric>;
  series: ReadonlyArray<LiveMetricPoint>;
  speakingSpeedWpm: number;
  sentiment: "positive" | "neutral" | "cautious";
  aiNotes: string;
}

export function LiveScorePanel({
  metrics,
  series,
  speakingSpeedWpm,
  sentiment,
  aiNotes,
}: LiveScorePanelProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
      className="space-y-4"
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/85 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Performance Matrix
          </h2>
          <ul className="space-y-4" aria-label="Live evaluation metrics">
            {metrics.map((metric, index) => {
              const Icon = ICON_MAP[metric.icon];
              const isNegative = metric.delta < 0;

              return (
                <motion.li
                  key={metric.id}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: index * 0.04 }}
                  className="space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Icon
                        className="h-4 w-4 text-primary"
                        aria-hidden="true"
                      />
                      <span className="text-sm text-white">{metric.label}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-semibold text-white">
                        {metric.score}%
                      </span>
                      <span
                        className={cn(
                          isNegative ? "text-destructive" : "text-sky-300"
                        )}
                      >
                        {isNegative ? "" : "+"}
                        {metric.delta.toFixed(1)}%
                      </span>
                    </div>
                  </div>
                  <Progress value={metric.score} className="h-1.5" />
                </motion.li>
              );
            })}
          </ul>
        </CardContent>
      </Card>

      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/85 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-3 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Live Evaluation Trends
          </h2>
          <div className="h-28" role="img" aria-label="Live metrics mini chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={[...series]}>
                <Tooltip
                  contentStyle={{
                    background: "#12121a",
                    border: "1px solid rgba(30,41,59,0.9)",
                    borderRadius: 12,
                    color: "#fff",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="technical"
                  stroke="#8b5cf6"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="confidence"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="communication"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
            <div className="rounded-xl border border-border/70 bg-[#0f1018] p-3">
              <dt className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                Speaking Speed
              </dt>
              <dd className="mt-1 font-semibold text-white">
                {speakingSpeedWpm} wpm
              </dd>
            </div>
            <div className="rounded-xl border border-border/70 bg-[#0f1018] p-3">
              <dt className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                Sentiment
              </dt>
              <dd className="mt-1 font-semibold capitalize text-white">
                {sentiment}
              </dd>
            </div>
          </dl>

          <div className="mt-3 rounded-xl border border-primary/25 bg-primary/5 p-3">
            <p className="text-[11px] font-semibold tracking-[0.12em] text-primary uppercase">
              AI Notes
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
              {aiNotes}
            </p>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
