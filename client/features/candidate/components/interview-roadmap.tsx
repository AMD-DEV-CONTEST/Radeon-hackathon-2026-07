"use client";

import { motion } from "framer-motion";
import { Flame, Star } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type {
  InterviewRoadmap as InterviewRoadmapData,
  RoadmapDifficulty,
} from "@/features/candidate/types/candidate.types";
import { cn } from "@/lib/utils";

interface InterviewRoadmapProps {
  roadmap: InterviewRoadmapData;
}

function difficultyClass(difficulty: RoadmapDifficulty): string {
  if (difficulty === "High") {
    return "border-destructive/40 bg-destructive/10 text-destructive";
  }
  if (difficulty === "Med") {
    return "border-amber-400/40 bg-amber-400/10 text-amber-300";
  }
  return "border-secondary/40 bg-secondary/10 text-secondary";
}

export function InterviewRoadmap({ roadmap }: InterviewRoadmapProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.08 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Star className="h-4 w-4 text-primary" aria-hidden="true" />
              <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Session Roadmap
              </h3>
            </div>
            <Badge variant="purple" className="normal-case tracking-normal">
              {roadmap.durationMinutes} Min
            </Badge>
          </div>

          <div className="mb-5 grid grid-cols-2 gap-2">
            <div className="rounded-xl border border-border/70 bg-[#0f1018] p-3">
              <p className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                Target Role
              </p>
              <p className="mt-1 text-sm font-semibold text-white">
                {roadmap.targetRole}
              </p>
            </div>
            <div className="rounded-xl border border-border/70 bg-[#0f1018] p-3">
              <p className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                Complexity
              </p>
              <p className="mt-1 inline-flex items-center gap-1 text-sm font-semibold text-white">
                <Flame className="h-3.5 w-3.5 text-destructive" aria-hidden="true" />
                {roadmap.complexity}
              </p>
            </div>
          </div>

          <div className="space-y-5">
            {roadmap.sections.map((section, sectionIndex) => (
              <section key={section.id} aria-labelledby={`roadmap-${section.id}`}>
                <h4
                  id={`roadmap-${section.id}`}
                  className="mb-3 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase"
                >
                  {section.title}
                </h4>
                <ul className="space-y-3">
                  {section.questions.map((question, questionIndex) => (
                    <motion.li
                      key={question.id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        duration: 0.25,
                        delay: 0.05 * (sectionIndex + questionIndex),
                      }}
                      className="rounded-xl border border-border/70 bg-[#0f1018] p-3 transition-colors hover:border-primary/30"
                    >
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <p className="text-[11px] font-semibold tracking-[0.12em] text-primary uppercase">
                          {question.category}
                        </p>
                        <span
                          className={cn(
                            "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase",
                            difficultyClass(question.difficulty)
                          )}
                        >
                          {question.difficulty}
                        </span>
                      </div>
                      <p className="text-sm leading-relaxed text-muted-foreground">
                        “{question.prompt}”
                      </p>
                    </motion.li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
