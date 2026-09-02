"use client";

import { motion } from "framer-motion";
import { FileBarChart2, Lightbulb } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type {
  AiReportItem,
  StrategyInsights,
  TalentFeedItem,
} from "@/features/admin/types/admin.types";
import { cn } from "@/lib/utils";

interface RecentActivityProps {
  talentFeed: ReadonlyArray<TalentFeedItem>;
  aiReports: ReadonlyArray<AiReportItem>;
  strategy: StrategyInsights;
}

export function RecentActivity({
  talentFeed,
  aiReports,
  strategy,
}: RecentActivityProps) {
  return (
    <section
      className="grid gap-4 lg:grid-cols-3"
      aria-label="Feeds and strategy insights"
    >
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        whileHover={{ y: -2 }}
      >
        <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="flex h-full flex-col p-5">
            <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Top Talent Feed
            </h2>
            <ul className="space-y-3" aria-label="Top talent">
              {talentFeed.map((item) => (
                <li
                  key={item.id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-[#0f1018] p-3"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-white"
                      aria-hidden="true"
                    >
                      {item.initials}
                    </span>
                    <div>
                      <p className="text-sm font-medium text-white">{item.name}</p>
                      <p className="text-xs text-muted-foreground">{item.title}</p>
                    </div>
                  </div>
                  <span className="text-sm font-semibold text-primary">
                    {item.score}%
                  </span>
                </li>
              ))}
            </ul>
            <Link
              href="/candidates/dossier"
              className={cn(
                buttonVariants({ variant: "outline" }),
                "mt-auto h-10 w-full"
              )}
            >
              View Talent Pipeline
            </Link>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.04 }}
        whileHover={{ y: -2 }}
      >
        <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <FileBarChart2 className="h-4 w-4 text-primary" aria-hidden="true" />
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Latest AI Reports
              </h2>
            </div>
            <ul className="space-y-3" aria-label="Latest AI reports">
              {aiReports.map((report) => (
                <li
                  key={report.id}
                  className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
                >
                  <p className="text-sm font-medium text-white">{report.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {report.category} · {report.timestamp}
                  </p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.08 }}
        whileHover={{ y: -2 }}
      >
        <Card className="h-full rounded-2xl border border-primary/30 bg-gradient-to-b from-primary/10 to-[#12121a]/90 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="space-y-4 p-5">
            <div className="flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-primary" aria-hidden="true" />
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Strategy Insights
              </h2>
            </div>
            <div className="rounded-xl border border-primary/25 bg-primary/5 p-3">
              <p className="text-[11px] font-semibold tracking-[0.12em] text-primary uppercase">
                Hot Topic of the Week
              </p>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {strategy.hotTopic}
              </p>
            </div>
            <div>
              <p className="mb-2 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                Most Effective Probes
              </p>
              <ul className="space-y-2">
                {strategy.probes.map((probe) => (
                  <li
                    key={probe}
                    className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2 text-xs text-muted-foreground"
                  >
                    {probe}
                  </li>
                ))}
              </ul>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2">
                <p className="text-[11px] text-muted-foreground uppercase">
                  Question Quality
                </p>
                <p className="font-semibold text-white">
                  {strategy.questionQuality}% Optimal
                </p>
              </div>
              <div className="rounded-lg border border-white/5 bg-[#0f1018] px-3 py-2">
                <p className="text-[11px] text-muted-foreground uppercase">
                  AI Confidence
                </p>
                <p className="font-semibold text-white">
                  {strategy.aiConfidence}%
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </section>
  );
}
