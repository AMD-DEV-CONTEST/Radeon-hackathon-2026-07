"use client";

import { motion } from "framer-motion";
import { Award, Flame, Medal, Trophy } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { Achievements } from "@/features/dashboard/types/dashboard.types";

interface AchievementsCardProps {
  achievements: Achievements;
}

export function AchievementsCard({ achievements }: AchievementsCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.14 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            <Trophy className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Achievements
            </h2>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-white/5 bg-[#0f1018] p-3">
              <p className="inline-flex items-center gap-1.5 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                <Medal className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                Highest Score
              </p>
              <p className="mt-2 text-2xl font-bold text-white">
                {achievements.highestScore}
              </p>
            </div>
            <div className="rounded-xl border border-white/5 bg-[#0f1018] p-3">
              <p className="inline-flex items-center gap-1.5 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                <Flame className="h-3.5 w-3.5 text-amber-300" aria-hidden="true" />
                Streak
              </p>
              <p className="mt-2 text-2xl font-bold text-white">
                {achievements.streakDays}
                <span className="text-sm font-medium text-muted-foreground">
                  {" "}
                  days
                </span>
              </p>
            </div>
          </div>

          <div>
            <p className="mb-2 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
              Badges
            </p>
            <ul className="space-y-2" aria-label="Achievement badges">
              {achievements.badges.map((badge) => (
                <li
                  key={badge.id}
                  className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2"
                >
                  <p className="text-sm font-medium text-white">{badge.label}</p>
                  <p className="text-xs text-muted-foreground">
                    {badge.description}
                  </p>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <p className="mb-2 inline-flex items-center gap-1.5 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
              <Award className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              Certifications
            </p>
            <div className="flex flex-wrap gap-2">
              {achievements.certifications.map((cert) => (
                <Badge
                  key={cert}
                  variant="outline"
                  className="tracking-normal normal-case"
                >
                  {cert}
                </Badge>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
