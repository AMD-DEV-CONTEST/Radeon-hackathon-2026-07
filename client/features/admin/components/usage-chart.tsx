"use client";

import { motion } from "framer-motion";
import { useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { InterviewTrendPoint } from "@/features/admin/types/admin.types";
import { cn } from "@/lib/utils";

type RangeKey = "1W" | "1M" | "ALL";

interface UsageChartProps {
  trends: ReadonlyArray<InterviewTrendPoint>;
}

export function UsageChart({ trends }: UsageChartProps) {
  const [range, setRange] = useState<RangeKey>("ALL");
  const data =
    range === "1W"
      ? trends.slice(-2)
      : range === "1M"
        ? trends.slice(-4)
        : trends;

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Interview Velocity & Quality
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Interview trends and quality over time
              </p>
            </div>
            <div
              className="flex items-center gap-1 rounded-xl border border-white/10 p-1"
              role="group"
              aria-label="Trend range"
            >
              {(["1W", "1M", "ALL"] as const).map((key) => (
                <Button
                  key={key}
                  type="button"
                  size="sm"
                  variant={range === key ? "default" : "ghost"}
                  className={cn(
                    "h-8 px-3",
                    range === key ? "glow-purple" : "text-muted-foreground"
                  )}
                  aria-pressed={range === key}
                  onClick={() => setRange(key)}
                >
                  {key}
                </Button>
              ))}
            </div>
          </div>

          <div
            className="h-[280px] w-full"
            role="img"
            aria-label="Interview velocity and quality chart"
          >
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={[...data]}>
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
                  yAxisId="left"
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
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
                <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
                <Bar
                  yAxisId="left"
                  dataKey="volume"
                  name="Volume"
                  fill="#8b5cf6"
                  radius={[8, 8, 0, 0]}
                  isAnimationActive
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="quality"
                  name="Quality"
                  stroke="#38bdf8"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: "#38bdf8" }}
                  isAnimationActive
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
