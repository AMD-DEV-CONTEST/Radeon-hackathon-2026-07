"use client";

import { motion } from "framer-motion";
import { HeartPulse } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type {
  HealthStatus,
  SystemServiceHealth,
} from "@/features/agents/types/agents.types";
import { cn } from "@/lib/utils";

interface SystemHealthProps {
  services: ReadonlyArray<SystemServiceHealth>;
}

const STATUS_CLASS: Record<HealthStatus, string> = {
  operational: "border-sky-400/30 bg-sky-500/10 text-sky-200",
  warning: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  offline: "border-destructive/30 bg-destructive/10 text-destructive",
};

export function SystemHealth({ services }: SystemHealthProps) {
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
          <div className="mb-4 flex items-center gap-2">
            <HeartPulse className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              System Health
            </h2>
          </div>

          <ul className="space-y-3" aria-label="System health services">
            {services.map((service, index) => (
              <motion.li
                key={service.id}
                initial={{ opacity: 0, x: 8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.22, delay: 0.03 * index }}
                className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-white">{service.name}</p>
                  <Badge
                    className={cn(
                      "tracking-normal normal-case capitalize",
                      STATUS_CLASS[service.status]
                    )}
                  >
                    {service.status}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">{service.detail}</p>
              </motion.li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
