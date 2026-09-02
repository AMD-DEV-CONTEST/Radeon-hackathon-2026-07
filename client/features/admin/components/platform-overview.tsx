"use client";

import { motion } from "framer-motion";
import { Bot, Users, Video } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { PlatformOverview } from "@/features/admin/types/admin.types";

interface PlatformOverviewProps {
  overview: PlatformOverview;
}

const ITEMS = [
  { key: "totalUsers", label: "Total Users", icon: Users },
  { key: "activeCandidates", label: "Active Candidates", icon: Users },
  { key: "activeInterviews", label: "Active Interviews", icon: Video },
  { key: "aiAgentsRunning", label: "AI Agents Running", icon: Bot },
] as const;

export function PlatformOverview({ overview }: PlatformOverviewProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.04 }}
      aria-label="Platform overview"
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Platform Overview
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {ITEMS.map((item) => {
              const Icon = item.icon;
              const value = overview[item.key];
              return (
                <div
                  key={item.key}
                  className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
                >
                  <p className="inline-flex items-center gap-1.5 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                    <Icon className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                    {item.label}
                  </p>
                  <p className="mt-2 text-2xl font-bold text-white">
                    {value.toLocaleString()}
                  </p>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </motion.section>
  );
}
