"use client";

import { motion } from "framer-motion";

import { Card, CardContent } from "@/components/ui/card";
import type {
  ResourceSaturation as ResourceSaturationData,
  SessionStats,
} from "@/features/agents/types/agents.types";

interface ResourceSaturationProps {
  resources: ResourceSaturationData;
  session: SessionStats;
}

export function ResourceSaturation({
  resources,
  session,
}: ResourceSaturationProps) {
  return (
    <div className="grid gap-4">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.14 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="space-y-4 p-5">
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Resource Saturation
            </h2>
            <div className="space-y-3">
              <div>
                <div className="mb-1 flex justify-between text-xs">
                  <span className="text-muted-foreground">Compute (CPU)</span>
                  <span className="text-white">
                    {resources.cpuPercent.toFixed(1)}%
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-sky-400"
                    style={{ width: `${resources.cpuPercent}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="mb-1 flex justify-between text-xs">
                  <span className="text-muted-foreground">
                    Neural Memory (VRAM)
                  </span>
                  <span className="text-primary">
                    {resources.memoryPercent.toFixed(1)}%
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary shadow-[0_0_12px_rgba(139,92,246,0.55)]"
                    style={{ width: `${resources.memoryPercent}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="mb-1 flex justify-between text-xs">
                  <span className="text-muted-foreground">
                    Network Throughput
                  </span>
                  <span className="text-white">
                    {resources.networkGbps.toFixed(1)} GB/s
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-cyan-400"
                    style={{
                      width: `${Math.min(resources.networkGbps * 10, 100)}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.16 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Session Stats
            </h2>
            <p
              className="mt-3 font-mono text-4xl font-bold tracking-tight text-white"
              aria-label={`Session uptime ${session.uptime}`}
            >
              {session.uptime}
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2">
                <p className="text-xs text-muted-foreground">Agent Cycles</p>
                <p className="font-semibold text-white">
                  {session.agentCycles.toLocaleString()}
                </p>
              </div>
              <div className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2">
                <p className="text-xs text-muted-foreground">Tasks Resolved</p>
                <p className="font-semibold text-white">
                  {session.tasksResolved.toLocaleString()}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
