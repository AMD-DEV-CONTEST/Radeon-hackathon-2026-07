"use client";

import { motion } from "framer-motion";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, CircleDot } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type {
  PulsePoint,
  TimelineEvent,
} from "@/features/report/types/report.types";

interface TimelineCardProps {
  pulse: ReadonlyArray<PulsePoint>;
  events: ReadonlyArray<TimelineEvent>;
  durationMinutes: number;
}

export function TimelineCard({
  pulse,
  events,
  durationMinutes,
}: TimelineCardProps) {
  const chartData = pulse.map((point) => ({
    ...point,
    label: `${point.minute}m`,
  }));

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-5 p-5 sm:p-6">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" aria-hidden="true" />
              <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Interview Pulse
              </h3>
            </div>
            <p className="text-sm text-muted-foreground">
              Sentiment and technical engagement over {durationMinutes} minutes
            </p>
          </div>

          <div
            className="h-[260px] w-full sm:h-[300px]"
            role="img"
            aria-label="Interview pulse performance timeline chart"
          >
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="engagementFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.45} />
                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient
                    id="technicalFill"
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  stroke="rgba(148,163,184,0.12)"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fill: "#94a3b8", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "#12121a",
                    border: "1px solid rgba(30,41,59,0.9)",
                    borderRadius: 12,
                    color: "#fff",
                  }}
                />
                <Legend
                  wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }}
                />
                <Area
                  type="monotone"
                  dataKey="engagement"
                  name="Engagement"
                  stroke="#8b5cf6"
                  fill="url(#engagementFill)"
                  strokeWidth={2}
                  isAnimationActive
                  animationDuration={1000}
                />
                <Area
                  type="monotone"
                  dataKey="technicalDepth"
                  name="Technical Depth"
                  stroke="#3b82f6"
                  fill="url(#technicalFill)"
                  strokeWidth={2}
                  isAnimationActive
                  animationDuration={1100}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div>
            <h4 className="mb-3 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Events
            </h4>
            <ol className="space-y-3" aria-label="Question and speaking timeline">
              {events.map((event, index) => (
                <motion.li
                  key={event.id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.22, delay: 0.03 * index }}
                  className="flex gap-3"
                >
                  <div className="mt-0.5 flex flex-col items-center">
                    <CircleDot
                      className="h-4 w-4 text-primary"
                      aria-hidden="true"
                    />
                    {index < events.length - 1 ? (
                      <div className="mt-1 h-full w-px grow bg-white/10" />
                    ) : null}
                  </div>
                  <div className="pb-2">
                    <p className="text-xs text-primary">{event.atMinute}m</p>
                    <p className="text-sm font-medium text-white">{event.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {event.description}
                    </p>
                  </div>
                </motion.li>
              ))}
            </ol>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
