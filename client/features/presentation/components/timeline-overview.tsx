"use client";

import { motion } from "framer-motion";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  EvaluationTimelinePoint,
  SkillBreakdownItem,
  ScoreTrendPoint,
} from "@/features/presentation/types/presentation.types";

interface TimelineOverviewProps {
  skillBreakdown: ReadonlyArray<SkillBreakdownItem>;
  scoreTrend: ReadonlyArray<ScoreTrendPoint>;
  evaluationTimeline: ReadonlyArray<EvaluationTimelinePoint>;
}

export function TimelineOverview({
  skillBreakdown,
  scoreTrend,
  evaluationTimeline,
}: TimelineOverviewProps) {
  const pulseData = evaluationTimeline.map((point) => ({
    ...point,
    label: `${point.minute}m`,
  }));

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.1 }}
        whileHover={{ y: -2 }}
      >
        <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Skill Breakdown
            </h2>
            <ul className="space-y-3" aria-label="Skill breakdown">
              {skillBreakdown.map((item) => (
                <li key={item.label} className="space-y-1.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-white">{item.label}</span>
                    <span className="text-muted-foreground">{item.score}%</span>
                  </div>
                  <Progress value={item.score} className="h-1.5" />
                </li>
              ))}
            </ul>
            <div
              className="mt-4 h-40"
              role="img"
              aria-label="Skill breakdown chart"
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={[...skillBreakdown]}>
                  <XAxis
                    dataKey="label"
                    tick={{ fill: "#94a3b8", fontSize: 9 }}
                    axisLine={false}
                    tickLine={false}
                    interval={0}
                    angle={-20}
                    textAnchor="end"
                    height={50}
                  />
                  <YAxis hide domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{
                      background: "#12121a",
                      border: "1px solid rgba(30,41,59,0.9)",
                      borderRadius: 12,
                      color: "#fff",
                    }}
                  />
                  <Bar
                    dataKey="score"
                    fill="#8b5cf6"
                    radius={[6, 6, 0, 0]}
                    isAnimationActive
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.12 }}
        whileHover={{ y: -2 }}
      >
        <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-3 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Score Trend
            </h2>
            <div className="h-[280px]" role="img" aria-label="Score trend chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={[...scoreTrend]}>
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
                    domain={[60, 100]}
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
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#38bdf8"
                    strokeWidth={2.5}
                    dot={{ r: 3, fill: "#38bdf8" }}
                    isAnimationActive
                    animationDuration={900}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.14 }}
        whileHover={{ y: -2 }}
      >
        <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-3 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Evaluation Timeline
            </h2>
            <div
              className="h-[280px]"
              role="img"
              aria-label="Evaluation timeline chart"
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={pulseData}>
                  <defs>
                    <linearGradient id="engFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.45} />
                      <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="techFill" x1="0" y1="0" x2="0" y2="1">
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
                  <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
                  <Area
                    type="monotone"
                    dataKey="engagement"
                    name="Engagement"
                    stroke="#8b5cf6"
                    fill="url(#engFill)"
                    strokeWidth={2}
                    isAnimationActive
                  />
                  <Area
                    type="monotone"
                    dataKey="technical"
                    name="Technical"
                    stroke="#3b82f6"
                    fill="url(#techFill)"
                    strokeWidth={2}
                    isAnimationActive
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
