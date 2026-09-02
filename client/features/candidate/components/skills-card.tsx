"use client";

import { motion } from "framer-motion";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { SkillItem } from "@/features/candidate/types/candidate.types";

interface SkillsCardProps {
  skills: ReadonlyArray<SkillItem>;
}

export function SkillsCard({ skills }: SkillsCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.05 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Skills Overview
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Skill distribution by proficiency
          </p>

          {skills.length === 0 ? (
            <p className="mt-4 text-sm text-muted-foreground">
              No skills available yet. Run AI analysis to extract skills.
            </p>
          ) : (
            <ul className="mt-4 space-y-3" aria-label="Skill distribution">
              {skills.map((skill, index) => (
                <motion.li
                  key={skill.name}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: 0.04 * index }}
                  className="space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="font-medium text-white">{skill.name}</span>
                    {typeof skill.proficiency === "number" ? (
                      <span className="text-xs text-muted-foreground">
                        {skill.proficiency}%
                      </span>
                    ) : null}
                  </div>
                  {typeof skill.proficiency === "number" ? (
                    <Progress value={skill.proficiency} className="h-1.5" />
                  ) : null}
                </motion.li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
