"use client";

import { motion } from "framer-motion";
import { Hexagon } from "lucide-react";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart as RechartsRadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import { Card, CardContent } from "@/components/ui/card";
import type { CompetencyRadarPoint } from "@/features/report/types/report.types";

interface ReportRadarChartProps {
  data: ReadonlyArray<CompetencyRadarPoint>;
}

export function ReportRadarChart({ data }: ReportRadarChartProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-1 flex items-center gap-2">
            <Hexagon className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Competency Matrix
            </h3>
          </div>
          <p className="text-sm text-muted-foreground">
            Multi-dimensional interview performance profile
          </p>

          <div
            className="mt-2 h-[280px] w-full sm:h-[320px]"
            role="img"
            aria-label="Competency matrix radar chart"
          >
            <ResponsiveContainer width="100%" height="100%">
              <RechartsRadarChart
                data={[...data]}
                cx="50%"
                cy="50%"
                outerRadius="72%"
              >
                <PolarGrid stroke="rgba(148, 163, 184, 0.25)" />
                <PolarAngleAxis
                  dataKey="subject"
                  tick={{ fill: "#94a3b8", fontSize: 12 }}
                />
                <PolarRadiusAxis
                  angle={30}
                  domain={[0, 100]}
                  tick={{ fill: "#64748b", fontSize: 10 }}
                  axisLine={false}
                />
                <Radar
                  name="Score"
                  dataKey="score"
                  stroke="#8b5cf6"
                  fill="url(#reportRadarFill)"
                  fillOpacity={0.55}
                  strokeWidth={2}
                  isAnimationActive
                  animationDuration={900}
                />
                <defs>
                  <linearGradient id="reportRadarFill" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.7} />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.35} />
                  </linearGradient>
                </defs>
                <Tooltip
                  contentStyle={{
                    background: "#12121a",
                    border: "1px solid rgba(30, 41, 59, 0.9)",
                    borderRadius: "12px",
                    color: "#fff",
                  }}
                />
              </RechartsRadarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
