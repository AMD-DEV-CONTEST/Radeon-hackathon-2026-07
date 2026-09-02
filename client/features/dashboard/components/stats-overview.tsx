"use client";

import { MetricCard } from "@/features/dashboard/components/metric-card";
import type { DashboardMetric } from "@/features/dashboard/types/dashboard.types";

interface StatsOverviewProps {
  metrics: ReadonlyArray<DashboardMetric>;
}

export function StatsOverview({ metrics }: StatsOverviewProps) {
  if (metrics.length === 0) {
    return (
      <section
        className="rounded-2xl border border-white/10 bg-[#12121a]/80 px-5 py-8 text-sm text-muted-foreground"
        aria-label="Dashboard statistics"
      >
        No dashboard metrics available yet.
      </section>
    );
  }

  return (
    <section
      className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
      aria-label="Dashboard statistics"
    >
      {metrics.map((metric, index) => (
        <MetricCard key={metric.id} metric={metric} index={index} />
      ))}
    </section>
  );
}
