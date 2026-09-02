"use client";

import { motion } from "framer-motion";
import { TriangleAlert } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { MetricItem } from "@/features/candidate/types/candidate.types";

interface WeaknessesCardProps {
  weaknesses: ReadonlyArray<MetricItem>;
}

export function WeaknessesCard({ weaknesses }: WeaknessesCardProps) {
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
            <TriangleAlert
              className="h-4 w-4 text-destructive"
              aria-hidden="true"
            />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Identified Gaps
            </h3>
          </div>

          <ul className="space-y-4">
            {weaknesses.map((item, index) => (
              <motion.li
                key={item.label}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, delay: 0.05 * index }}
                className="space-y-2"
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-white">{item.label}</p>
                  <span className="text-xs font-semibold text-destructive">
                    {item.score}%
                  </span>
                </div>
                <Progress
                  value={item.score}
                  className="h-1.5"
                  indicatorClassName="bg-destructive"
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
