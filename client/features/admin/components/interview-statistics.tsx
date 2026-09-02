"use client";

import { motion } from "framer-motion";
import { Activity } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { InterviewStatistics } from "@/features/admin/types/admin.types";

interface InterviewStatisticsProps {
  statistics: InterviewStatistics;
}

export function InterviewStatistics({ statistics }: InterviewStatisticsProps) {
  const items = [
    { label: "Daily Interviews", value: statistics.daily.toLocaleString() },
    { label: "Weekly Interviews", value: statistics.weekly.toLocaleString() },
    { label: "Monthly Interviews", value: statistics.monthly.toLocaleString() },
    {
      label: "Average Candidate Score",
      value: statistics.averageScore.toFixed(1),
    },
    {
      label: "Hiring Success Rate",
      value: `${statistics.hiringSuccessRate}%`,
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.06 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Statistics
            </h2>
          </div>
          <ul
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"
            aria-label="Interview statistics"
          >
            {items.map((item) => (
              <li
                key={item.label}
                className="rounded-xl border border-white/5 bg-[#0f1018] px-3 py-3"
              >
                <p className="text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                  {item.label}
                </p>
                <p className="mt-2 text-xl font-bold text-white">{item.value}</p>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
