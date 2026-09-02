"use client";

import { motion } from "framer-motion";
import { Gauge } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

interface ReadinessCardProps {
  score: number;
  candidateName: string;
}

export function ReadinessCard({ score, candidateName }: ReadinessCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.05 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <Gauge className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Readiness
            </h2>
          </div>
          <p className="text-3xl font-bold text-white">{score}%</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {candidateName} is ready for a high-depth session.
          </p>
          <Progress value={score} className="mt-4 h-2" />
        </CardContent>
      </Card>
    </motion.div>
  );
}
