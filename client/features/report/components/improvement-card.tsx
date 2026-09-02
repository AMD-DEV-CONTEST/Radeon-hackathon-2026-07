"use client";

import { motion } from "framer-motion";
import { AlertCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { ImprovementItem } from "@/features/report/types/report.types";
import { cn } from "@/lib/utils";

interface ImprovementCardProps {
  improvements: ReadonlyArray<ImprovementItem>;
}

const SEVERITY_CLASS: Record<ImprovementItem["severity"], string> = {
  low: "border-sky-400/30 bg-sky-500/10 text-sky-200",
  medium: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  high: "border-destructive/30 bg-destructive/10 text-destructive",
};

export function ImprovementCard({ improvements }: ImprovementCardProps) {
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
            <AlertCircle className="h-4 w-4 text-amber-300" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Areas for Improvement
            </h3>
          </div>

          <ul className="space-y-4" aria-label="Areas for improvement">
            {improvements.map((item, index) => (
              <motion.li
                key={`${item.category}-${item.title}`}
                initial={{ opacity: 0, x: 8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, delay: 0.04 * index }}
                className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
              >
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                    {item.category}
                  </p>
                  <Badge
                    className={cn(
                      "tracking-normal normal-case",
                      SEVERITY_CLASS[item.severity]
                    )}
                  >
                    {item.severity}
                  </Badge>
                </div>
                <p className="text-sm font-medium text-white">{item.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
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
