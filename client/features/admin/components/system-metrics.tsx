"use client";

import { motion } from "framer-motion";
import type { ReactElement } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent } from "@/components/ui/card";
import type {
  AgentUsagePoint,
  PlatformUsagePoint,
  SkillTrendPoint,
  SystemPerformancePoint,
  UserGrowthPoint,
} from "@/features/admin/types/admin.types";

interface SystemMetricsProps {
  userGrowth: ReadonlyArray<UserGrowthPoint>;
  agentUsage: ReadonlyArray<AgentUsagePoint>;
  platformUsage: ReadonlyArray<PlatformUsagePoint>;
  systemPerformance: ReadonlyArray<SystemPerformancePoint>;
  skillTrends: ReadonlyArray<SkillTrendPoint>;
}

export function SystemMetrics({
  userGrowth,
  agentUsage,
  platformUsage,
  systemPerformance,
  skillTrends,
}: SystemMetricsProps) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <MetricChartCard title="User Growth" label="User growth chart">
        <LineChart data={[...userGrowth]}>
          <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} />
          <Line type="monotone" dataKey="users" stroke="#8b5cf6" strokeWidth={2.5} dot={false} isAnimationActive />
        </LineChart>
      </MetricChartCard>

      <MetricChartCard title="AI Agent Usage" label="AI agent usage chart">
        <BarChart data={[...agentUsage]}>
          <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} />
          <Bar dataKey="usage" fill="#38bdf8" radius={[8, 8, 0, 0]} isAnimationActive />
        </BarChart>
      </MetricChartCard>

      <MetricChartCard title="Platform Usage" label="Platform usage chart">
        <AreaChart data={[...platformUsage]}>
          <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} />
          <Area type="monotone" dataKey="sessions" stroke="#8b5cf6" fill="rgba(139,92,246,0.25)" isAnimationActive />
          <Area type="monotone" dataKey="apiCalls" stroke="#38bdf8" fill="rgba(56,189,248,0.12)" isAnimationActive />
        </AreaChart>
      </MetricChartCard>

      <MetricChartCard title="System Performance" label="System performance chart">
        <LineChart data={[...systemPerformance]}>
          <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} />
          <Line type="monotone" dataKey="cpu" name="CPU" stroke="#38bdf8" strokeWidth={2} dot={false} isAnimationActive />
          <Line type="monotone" dataKey="memory" name="Memory" stroke="#8b5cf6" strokeWidth={2} dot={false} isAnimationActive />
          <Line type="monotone" dataKey="latencyMs" name="Latency" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive />
        </LineChart>
      </MetricChartCard>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.1 }}
        whileHover={{ y: -2 }}
        className="xl:col-span-2"
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-1 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Emerging Skill Trends
            </h2>
            <p className="mb-4 text-sm text-muted-foreground">
              In-Demand: Rust & AI Ops
            </p>
            <ul className="space-y-3" aria-label="Skill demand versus supply">
              {skillTrends.map((item) => (
                <li key={item.skill} className="space-y-1.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-white">{item.skill}</span>
                    <span className="text-xs text-muted-foreground">
                      Demand {item.demand}% · Supply {item.supply}%
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="h-2 rounded-full bg-primary/20">
                      <div
                        className="h-2 rounded-full bg-primary"
                        style={{ width: `${item.demand}%` }}
                      />
                    </div>
                    <div className="h-2 rounded-full bg-sky-500/20">
                      <div
                        className="h-2 rounded-full bg-sky-400"
                        style={{ width: `${item.supply}%` }}
                      />
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}

const tooltipStyle = {
  background: "#12121a",
  border: "1px solid rgba(30,41,59,0.9)",
  borderRadius: 12,
  color: "#fff",
} as const;

function MetricChartCard({
  title,
  label,
  children,
}: {
  title: string;
  label: string;
  children: ReactElement;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-3 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            {title}
          </h2>
          <div className="h-52" role="img" aria-label={label}>
            <ResponsiveContainer width="100%" height="100%">
              {children}
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
