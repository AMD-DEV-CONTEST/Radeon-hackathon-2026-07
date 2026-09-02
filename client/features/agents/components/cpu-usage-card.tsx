"use client";

import { motion } from "framer-motion";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from "recharts";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { ResourceSeriesPoint } from "@/features/agents/types/agents.types";

interface CpuUsageCardProps {
  series: ReadonlyArray<ResourceSeriesPoint>;
  cpuPercent: number;
}

export function CpuUsageCard({ series, cpuPercent }: CpuUsageCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              CPU Usage
            </h2>
            <span className="text-sm font-semibold text-white">
              {cpuPercent.toFixed(1)}%
            </span>
          </div>
          <Progress value={cpuPercent} className="mb-3 h-1.5" />
          <div className="h-28" role="img" aria-label="CPU usage chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={[...series]}>
                <XAxis dataKey="time" hide />
                <Tooltip
                  contentStyle={{
                    background: "#12121a",
                    border: "1px solid rgba(30,41,59,0.9)",
                    borderRadius: 12,
                    color: "#fff",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="cpu"
                  stroke="#38bdf8"
                  fill="rgba(56,189,248,0.2)"
                  strokeWidth={2}
                  isAnimationActive
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
