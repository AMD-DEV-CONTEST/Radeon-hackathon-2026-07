"use client";

import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import {
  Bot,
  Briefcase,
  Star,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
  Video,
} from "lucide-react";
import { useEffect } from "react";

import { Card, CardContent } from "@/components/ui/card";
import type { AdminKpi } from "@/features/admin/types/admin.types";
import { cn } from "@/lib/utils";

const ICON_MAP = {
  interviews: Video,
  active: Briefcase,
  score: Star,
  hire: Target,
  users: Users,
  agents: Bot,
} as const;

interface AnalyticsCardsProps {
  kpis: ReadonlyArray<AdminKpi>;
}

function AnimatedValue({
  value,
  suffix,
}: {
  value: number;
  suffix?: string;
}) {
  const motionValue = useMotionValue(0);
  const spring = useSpring(motionValue, { stiffness: 90, damping: 18 });
  const display = useTransform(spring, (latest) => {
    const rounded =
      Number.isInteger(value) && !String(value).includes(".")
        ? Math.round(latest)
        : Number(latest.toFixed(1));
    return `${rounded}${suffix ?? ""}`;
  });

  useEffect(() => {
    motionValue.set(value);
  }, [motionValue, value]);

  return <motion.span>{display}</motion.span>;
}

export function AnalyticsCards({ kpis }: AnalyticsCardsProps) {
  return (
    <section
      className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
      aria-label="Platform analytics cards"
    >
      {kpis.map((kpi, index) => {
        const Icon = ICON_MAP[kpi.icon];
        const isPositive = kpi.delta >= 0;

        return (
          <motion.div
            key={kpi.id}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: 0.04 * index }}
            whileHover={{ y: -2 }}
          >
            <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
              <CardContent className="p-5">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/15 text-primary">
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </div>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
                      isPositive
                        ? "bg-sky-500/15 text-sky-300"
                        : "bg-destructive/15 text-destructive"
                    )}
                  >
                    {isPositive ? (
                      <TrendingUp className="h-3 w-3" aria-hidden="true" />
                    ) : (
                      <TrendingDown className="h-3 w-3" aria-hidden="true" />
                    )}
                    {isPositive ? "+" : ""}
                    {kpi.delta}%
                  </span>
                </div>
                <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                  {kpi.label}
                </p>
                <p
                  className="mt-2 text-3xl font-bold tracking-tight text-white"
                  aria-label={`${kpi.label}: ${kpi.value}${kpi.suffix ?? ""}`}
                >
                  <AnimatedValue value={kpi.value} suffix={kpi.suffix} />
                </p>
              </CardContent>
            </Card>
          </motion.div>
        );
      })}
    </section>
  );
}
