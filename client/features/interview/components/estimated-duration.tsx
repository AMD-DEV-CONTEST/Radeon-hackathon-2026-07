"use client";

import { motion } from "framer-motion";
import { Clock3 } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

interface EstimatedDurationProps {
  minutes: number;
  questionCount: number;
}

export function EstimatedDuration({
  minutes,
  questionCount,
}: EstimatedDurationProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.07 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Clock3 className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Estimated Duration
            </h2>
          </div>
          <p className="text-3xl font-bold text-white">{minutes} min</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Across {questionCount} adaptive questions with live evaluation.
          </p>
        </CardContent>
      </Card>
    </motion.div>
  );
}
