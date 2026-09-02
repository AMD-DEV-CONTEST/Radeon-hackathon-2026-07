"use client";

import { motion } from "framer-motion";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent } from "@/components/ui/card";
import type { LatencyPoint } from "@/features/agents/types/agents.types";

interface LatencyCardProps {
  series: ReadonlyArray<LatencyPoint>;
  avgLatencyMs: number;
  p99LatencyMs: number;
}

export function LatencyCard({
  series,
  avgLatencyMs,
  p99LatencyMs,
}: LatencyCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Execution Latency
          </h2>
          <div
            className="mt-3 h-40"
            role="img"
            aria-label="Agent latency chart"
          >
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={[...series]}>
                <defs>
                  <linearGradient id="latencyFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.5} />
                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="time"
                  tick={{ fill: "#94a3b8", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis hide />
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
                  dataKey="latencyMs"
                  stroke="#8b5cf6"
                  fill="url(#latencyFill)"
                  strokeWidth={2}
                  isAnimationActive
                  animationDuration={900}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2">
              <p className="text-[11px] text-muted-foreground uppercase">
                Avg Latency
              </p>
              <p className="font-semibold text-white">{avgLatencyMs}ms</p>
            </div>
            <div className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2">
              <p className="text-[11px] text-muted-foreground uppercase">P99</p>
              <p className="font-semibold text-white">
                {(p99LatencyMs / 1000).toFixed(1)}s
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
