"use client";

import { motion } from "framer-motion";
import { Network } from "lucide-react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from "recharts";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type {
  AgentCommunicationEdge,
  ResourceSeriesPoint,
} from "@/features/agents/types/agents.types";

interface NetworkCardProps {
  series: ReadonlyArray<ResourceSeriesPoint>;
  networkGbps: number;
  communication: ReadonlyArray<AgentCommunicationEdge>;
  clusterNodes: number;
  shard: string;
  optimizationHint: string;
}

export function NetworkCard({
  series,
  networkGbps,
  communication,
  clusterNodes,
  shard,
  optimizationHint,
}: NetworkCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.12 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            <Network className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Network & Communication
            </h2>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Throughput</span>
              <span className="font-semibold text-white">
                {networkGbps.toFixed(1)} GB/s
              </span>
            </div>
            <Progress value={Math.min(networkGbps * 10, 100)} className="h-1.5" />
          </div>

          <div className="h-24" role="img" aria-label="Requests per minute chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={[...series]}>
                <XAxis dataKey="time" hide />
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
                  dataKey="rpm"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div>
            <p className="mb-2 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
              Agent Communication Graph
            </p>
            <ul className="space-y-2" aria-label="Agent communication edges">
              {communication.map((edge) => (
                <li key={`${edge.from}-${edge.to}`} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-white">
                      {edge.from} → {edge.to}
                    </span>
                    <span className="text-muted-foreground">
                      {edge.trafficPercent}%
                    </span>
                  </div>
                  <Progress value={edge.trafficPercent} className="h-1.5" />
                </li>
              ))}
            </ul>
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2">
              <p className="text-muted-foreground">Nodes</p>
              <p className="font-semibold text-white">{clusterNodes} Active</p>
            </div>
            <div className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2">
              <p className="text-muted-foreground">Shard</p>
              <p className="font-semibold text-white">{shard}</p>
            </div>
          </div>

          <div className="rounded-xl border border-primary/25 bg-primary/5 p-3">
            <p className="text-[11px] font-semibold tracking-[0.12em] text-primary uppercase">
              Optimization Hint
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {optimizationHint}
            </p>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
