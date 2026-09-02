"use client";

import { motion } from "framer-motion";
import {
  AlertTriangle,
  Eye,
  Sparkles,
  ThumbsUp,
} from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { AiInsights as AiInsightsData } from "@/features/presentation/types/presentation.types";

interface AiInsightsProps {
  insights: AiInsightsData;
}

function InsightList({
  title,
  icon: Icon,
  items,
  tone,
}: {
  title: string;
  icon: typeof Sparkles;
  items: ReadonlyArray<string>;
  tone: "positive" | "caution" | "neutral";
}) {
  const toneClass =
    tone === "positive"
      ? "border-emerald-400/20 bg-emerald-500/5"
      : tone === "caution"
        ? "border-amber-400/20 bg-amber-500/5"
        : "border-white/5 bg-[#0f1018]";

  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      <div className="mb-2 flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
        <h3 className="text-xs font-semibold tracking-[0.12em] text-muted-foreground uppercase">
          {title}
        </h3>
      </div>
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item} className="text-sm leading-relaxed text-muted-foreground">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AiInsights({ insights }: AiInsightsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5 sm:p-6">
          <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            AI Insights
          </h2>
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            <InsightList
              title="Strengths"
              icon={Sparkles}
              items={insights.strengths}
              tone="positive"
            />
            <InsightList
              title="Weaknesses"
              icon={AlertTriangle}
              items={insights.weaknesses}
              tone="caution"
            />
            <InsightList
              title="Key Observations"
              icon={Eye}
              items={insights.keyObservations}
              tone="neutral"
            />
            <InsightList
              title="Red Flags"
              icon={AlertTriangle}
              items={insights.redFlags}
              tone="caution"
            />
            <InsightList
              title="Positive Signals"
              icon={ThumbsUp}
              items={insights.positiveSignals}
              tone="positive"
            />
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
