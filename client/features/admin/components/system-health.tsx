"use client";

import { motion } from "framer-motion";
import { HeartPulse } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type {
  ActiveAgentRow,
  ServiceHealthStatus,
  SystemServiceHealth,
} from "@/features/admin/types/admin.types";
import { cn } from "@/lib/utils";

interface SystemHealthProps {
  services: ReadonlyArray<SystemServiceHealth>;
  agents: ReadonlyArray<ActiveAgentRow>;
}

const STATUS_CLASS: Record<ServiceHealthStatus, string> = {
  operational: "border-sky-400/30 bg-sky-500/10 text-sky-200",
  warning: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  offline: "border-destructive/30 bg-destructive/10 text-destructive",
};

export function SystemHealth({ services, agents }: SystemHealthProps) {
  return (
    <div className="grid gap-4">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Active Agents
            </h2>
            <ul className="space-y-3" aria-label="Active agents">
              {agents.map((agent) => (
                <li
                  key={agent.id}
                  className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-white">
                        {agent.name}
                      </p>
                      <p className="text-xs text-muted-foreground">{agent.task}</p>
                    </div>
                    <Badge
                      className={cn(
                        "tracking-normal normal-case uppercase",
                        agent.status === "busy"
                          ? "border-primary/40 bg-primary/15 text-primary"
                          : "border-border/70 bg-muted/30 text-muted-foreground"
                      )}
                    >
                      {agent.status} {agent.busyPercent}%
                    </Badge>
                  </div>
                  <div
                    className="h-1.5 overflow-hidden rounded-full bg-muted"
                    role="progressbar"
                    aria-valuenow={agent.busyPercent}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${agent.name} utilization`}
                  >
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${agent.busyPercent}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.05 }}
        whileHover={{ y: -2 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <HeartPulse className="h-4 w-4 text-primary" aria-hidden="true" />
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Platform Pulse / System Health
              </h2>
            </div>
            <ul className="space-y-3" aria-label="System health services">
              {services.map((service) => (
                <li
                  key={service.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-white/5 bg-[#0f1018] p-3"
                >
                  <div>
                    <p className="text-sm font-medium text-white">{service.name}</p>
                    <p className="text-xs text-muted-foreground">{service.detail}</p>
                  </div>
                  <Badge
                    className={cn(
                      "shrink-0 tracking-normal normal-case capitalize",
                      STATUS_CLASS[service.status]
                    )}
                  >
                    {service.status}
                  </Badge>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
