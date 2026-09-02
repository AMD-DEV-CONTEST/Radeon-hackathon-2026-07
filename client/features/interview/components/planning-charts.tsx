"use client";

import { motion } from "framer-motion";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  CoveragePoint,
  MetricBar,
} from "@/features/interview/types/interview.types";

interface PlanningChartsProps {
  skillDistribution: ReadonlyArray<MetricBar>;
  interviewCoverage: ReadonlyArray<CoveragePoint>;
  readinessScore: number;
}

export function PlanningCharts({
  skillDistribution,
  interviewCoverage,
  readinessScore,
}: PlanningChartsProps) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.1 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Skill Distribution
            </h2>
            <div className="mt-3 h-56" role="img" aria-label="Skill distribution chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={[...skillDistribution]}>
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
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
                  <Bar dataKey="value" fill="#8b5cf6" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.14 }}
        whileHover={{ y: -2 }}
        className="space-y-4"
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Coverage
            </h2>
            <ul className="space-y-3" aria-label="Interview coverage">
              {interviewCoverage.map((item) => (
                <li key={item.label} className="space-y-1.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-white">{item.label}</span>
                    <span className="text-muted-foreground">
                      {item.coverage}%
                    </span>
                  </div>
                  <Progress value={item.coverage} className="h-1.5" />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-2 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Readiness Progress
            </h2>
            <div className="flex items-end justify-between gap-3">
              <p className="text-3xl font-bold text-white">{readinessScore}%</p>
              <p className="text-xs text-muted-foreground">Session readiness</p>
            </div>
            <Progress value={readinessScore} className="mt-3 h-2" />
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
