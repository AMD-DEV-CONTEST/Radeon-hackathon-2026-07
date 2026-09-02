"use client";

import { motion } from "framer-motion";
import { Hexagon } from "lucide-react";

import { CompetencyRadarChart } from "@/components/charts/radar-chart";
import { Card, CardContent } from "@/components/ui/card";
import type { CompetencyScore } from "@/features/candidate/types/candidate.types";

interface CompetencyRadarProps {
  competencies: ReadonlyArray<CompetencyScore>;
}

export function CompetencyRadar({ competencies }: CompetencyRadarProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-2 flex items-center gap-2">
            <Hexagon className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              AI Proficiency Matrix
            </h3>
          </div>
          <p className="text-sm text-muted-foreground">
            Candidate vs. Ideal Role Profile
          </p>

          <CompetencyRadarChart
            data={competencies}
            className="mt-2 h-[300px] w-full sm:h-[340px]"
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}
