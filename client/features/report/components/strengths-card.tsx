"use client";

import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { StrengthItem } from "@/features/report/types/report.types";

interface StrengthsCardProps {
  strengths: ReadonlyArray<StrengthItem>;
}

export function StrengthsCard({ strengths }: StrengthsCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-secondary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Strengths
            </h3>
          </div>

          <ul className="space-y-4" aria-label="Candidate strengths">
            {strengths.map((item, index) => (
              <motion.li
                key={`${item.category}-${item.title}`}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, delay: 0.04 * index }}
                className="space-y-2"
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[11px] tracking-[0.12em] text-primary uppercase">
                      {item.category}
                    </p>
                    <p className="text-sm font-medium text-white">{item.title}</p>
                  </div>
                  <span className="text-xs font-semibold text-secondary">
                    {item.score}%
                  </span>
                </div>
                <Progress
                  value={item.score}
                  className="h-1.5"
                  indicatorClassName="bg-secondary"
                />
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {item.description}
                </p>
              </motion.li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
