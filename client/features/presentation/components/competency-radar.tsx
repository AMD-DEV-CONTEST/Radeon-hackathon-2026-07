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
import type { CompetencyPoint } from "@/features/presentation/types/presentation.types";

interface CompetencyRadarProps {
  data: ReadonlyArray<CompetencyPoint>;
}

export function CompetencyRadar({ data }: CompetencyRadarProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.08 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-1 flex items-center gap-2">
            <Hexagon className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Competency Radar
            </h2>
          </div>
          <div
            className="mt-2 h-[280px] w-full sm:h-[320px]"
            role="img"
            aria-label="Competency radar chart"
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
                  tick={{ fill: "#94a3b8", fontSize: 11 }}
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
                  fill="#8b5cf6"
                  fillOpacity={0.4}
                  strokeWidth={2}
                  isAnimationActive
                  animationDuration={900}
                />
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
