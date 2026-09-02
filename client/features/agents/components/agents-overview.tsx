"use client";

import { motion } from "framer-motion";
import {
  Activity,
  Command,
  Pause,
  Radio,
  RotateCcw,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ActiveAgentCard } from "@/features/agents/components/active-agent-card";
import type { AgentsOverview as AgentsOverviewData } from "@/features/agents/types/agents.types";
import { cn } from "@/lib/utils";

interface AgentsOverviewProps {
  data: AgentsOverviewData;
  onResetMetrics?: () => void;
}

export function AgentsOverview({ data, onResetMetrics }: AgentsOverviewProps) {
  const [isLive, setIsLive] = useState(data.isLive);

  return (
    <section className="space-y-5" aria-label="Multi-agent status overview">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between"
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="purple">Real-time Observability</Badge>
            <Badge
              className={cn(
                "gap-1.5 tracking-normal normal-case",
                isLive
                  ? "border-sky-400/30 bg-sky-500/15 text-sky-200"
                  : "border-amber-400/30 bg-amber-500/10 text-amber-200"
              )}
            >
              <Radio className="h-3 w-3" aria-hidden="true" />
              {isLive ? "Live Syncing" : "Paused"}
            </Badge>
            <Badge variant="outline" className="font-mono tracking-normal">
              ID: {data.monitorId}
            </Badge>
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Agent Monitoring
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
              Monitoring multi-agent orchestration, resource allocation, and
              workflow state transitions.
            </p>
          </div>
          <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
            <span>
              Active Agents:{" "}
              <strong className="text-white">
                {data.session.totalActiveAgents}
              </strong>
            </span>
            <span>
              Workflow:{" "}
              <strong className="text-white">
                {data.session.currentWorkflow}
              </strong>
            </span>
            <span>
              Uptime:{" "}
              <strong className="font-mono text-white">
                {data.session.uptime}
              </strong>
            </span>
            <span>
              Sessions:{" "}
              <strong className="text-white">
                {data.session.activeSessions}
              </strong>
            </span>
          </div>
        </div>

        <div
          className="flex flex-wrap gap-2"
          role="group"
          aria-label="Monitoring controls"
        >
          <Button
            type="button"
            variant={isLive ? "default" : "outline"}
            className={cn("h-10", isLive && "glow-purple")}
            aria-pressed={isLive}
            onClick={() => setIsLive(true)}
          >
            <Activity className="h-4 w-4" aria-hidden="true" />
            Live
          </Button>
          <Button
            type="button"
            variant={!isLive ? "default" : "outline"}
            className="h-10"
            aria-pressed={!isLive}
            onClick={() => setIsLive(false)}
          >
            <Pause className="h-4 w-4" aria-hidden="true" />
            Paused
          </Button>
          <Button
            type="button"
            variant="outline"
            className="h-10"
            onClick={onResetMetrics}
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Reset Metrics
          </Button>
          <Button type="button" className="h-10 glow-purple">
            <Command className="h-4 w-4" aria-hidden="true" />
            Command Panel
          </Button>
        </div>
      </motion.div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        {data.agents.map((agent, index) => (
          <div
            key={agent.id}
            className={cn(
              "xl:col-span-1",
              index === 0 ? "2xl:col-span-1" : "2xl:col-span-1"
            )}
          >
            <ActiveAgentCard
              agent={agent}
              index={index}
              isActive={agent.id === data.activeNodeId}
            />
          </div>
        ))}

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.28 }}
          whileHover={{ y: -2 }}
          className="sm:col-span-2 xl:col-span-4 2xl:col-span-1"
        >
          <Card className="h-full rounded-2xl border border-primary/30 bg-gradient-to-b from-primary/20 to-[#12121a]/90 py-0 ring-0 backdrop-blur-xl">
            <CardContent className="flex h-full flex-col justify-between p-5">
              <div>
                <p className="text-[11px] font-semibold tracking-[0.14em] text-primary uppercase">
                  Global Health
                </p>
                <p
                  className="mt-3 text-4xl font-bold text-white"
                  aria-label={`Global health ${data.globalHealth.score} percent`}
                >
                  {data.globalHealth.score.toFixed(2)}%
                </p>
              </div>
              <div className="mt-6 space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Load</span>
                  <span className="text-white">
                    {data.globalHealth.loadPercent}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Latency</span>
                  <span className="text-white">
                    {data.globalHealth.latencyMs}ms
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </section>
  );
}
