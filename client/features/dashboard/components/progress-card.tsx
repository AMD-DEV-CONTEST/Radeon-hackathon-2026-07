"use client";

import { motion } from "framer-motion";
import { Gauge } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

interface ProgressCardProps {
  readinessScore: number;
  resumeScore: number;
  successRate: number;
}

export function ProgressCard({
  readinessScore,
  resumeScore,
  successRate,
}: ProgressCardProps) {
  const overall = Math.round((readinessScore + resumeScore + successRate) / 3);

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.16 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            <Gauge className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Overall Progress
            </h2>
          </div>

          <div className="rounded-xl border border-primary/25 bg-primary/5 p-4 text-center">
            <p className="text-[11px] tracking-[0.14em] text-primary uppercase">
              Composite Score
            </p>
            <p
              className="mt-1 text-4xl font-bold text-white"
              aria-label={`Composite progress score ${overall} percent`}
            >
              {overall}%
            </p>
          </div>

          <ul className="space-y-3" aria-label="Progress breakdown">
            <li className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-muted-foreground">Readiness</span>
                <span className="text-white">{readinessScore}%</span>
              </div>
              <Progress value={readinessScore} className="h-1.5" />
            </li>
            <li className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-muted-foreground">Resume</span>
                <span className="text-white">{resumeScore}%</span>
              </div>
              <Progress value={resumeScore} className="h-1.5" />
            </li>
            <li className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-muted-foreground">Success Rate</span>
                <span className="text-white">{successRate}%</span>
              </div>
              <Progress value={successRate} className="h-1.5" />
            </li>
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
