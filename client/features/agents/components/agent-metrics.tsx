"use client";

import { motion } from "framer-motion";
import {
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
  AgentCardData,
  ResourceSeriesPoint,
} from "@/features/agents/types/agents.types";

interface AgentMetricsProps {
  agents: ReadonlyArray<AgentCardData>;
  resourceSeries: ReadonlyArray<ResourceSeriesPoint>;
}

export function AgentMetrics({ agents, resourceSeries }: AgentMetricsProps) {
  const successData = agents.map((agent) => ({
    name: agent.name.replace(" Agent", "").replace("Fact Checker", "Facts"),
    successRate: agent.successRate,
  }));

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      className="grid gap-4 lg:grid-cols-2"
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-3 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Success Rate
          </h2>
          <div
            className="h-52"
            role="img"
            aria-label="Agent success rate chart"
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={successData}>
                <CartesianGrid
                  stroke="rgba(148,163,184,0.12)"
                  vertical={false}
                />
                <XAxis
                  dataKey="name"
                  tick={{ fill: "#94a3b8", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={[90, 100]}
                  tick={{ fill: "#64748b", fontSize: 10 }}
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
                <Bar
                  dataKey="successRate"
                  fill="#8b5cf6"
                  radius={[8, 8, 0, 0]}
                  isAnimationActive
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-3 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Workflow Performance
          </h2>
          <div
            className="h-52"
            role="img"
            aria-label="Workflow performance chart"
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={[...resourceSeries]}>
                <CartesianGrid
                  stroke="rgba(148,163,184,0.12)"
                  vertical={false}
                />
                <XAxis
                  dataKey="time"
                  tick={{ fill: "#94a3b8", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={[90, 100]}
                  tick={{ fill: "#64748b", fontSize: 10 }}
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
                  dataKey="successRate"
                  name="Success"
                  stroke="#38bdf8"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: "#38bdf8" }}
                  isAnimationActive
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
