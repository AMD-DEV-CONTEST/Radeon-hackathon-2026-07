"use client";

import { motion } from "framer-motion";
import { Clock3, Flame } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { InterviewDifficulty } from "@/features/interview/types/interview.types";

interface InterviewProgressProps {
  progressPercent: number;
  difficulty: InterviewDifficulty;
  estimatedRemainingLabel: string;
}

export function InterviewProgress({
  progressPercent,
  difficulty,
  estimatedRemainingLabel,
}: InterviewProgressProps) {
  const difficultyLabel =
    difficulty === "hard" || difficulty === "extreme" ? "High" : difficulty;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.05 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/85 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5">
          <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Session Status
          </h2>

          <div>
            <div className="mb-2 flex items-center justify-between gap-3 text-sm">
              <span className="text-muted-foreground">Interview Progress</span>
              <span className="font-semibold text-white">
                {progressPercent}%
              </span>
            </div>
            <Progress value={progressPercent} className="h-2" />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl border border-border/70 bg-[#0f1018] p-3">
              <p className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                Difficulty
              </p>
              <Badge
                variant="outline"
                className="mt-2 border-destructive/40 bg-destructive/10 text-destructive"
              >
                <Flame className="h-3.5 w-3.5" aria-hidden="true" />
                {difficultyLabel}
              </Badge>
            </div>
            <div className="rounded-xl border border-border/70 bg-[#0f1018] p-3">
              <p className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                Estimated Rem.
              </p>
              <p className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-white">
                <Clock3 className="h-3.5 w-3.5 text-muted-foreground" />
                {estimatedRemainingLabel}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
