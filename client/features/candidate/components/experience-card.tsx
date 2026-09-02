"use client";

import { motion } from "framer-motion";
import { Briefcase } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { ExperienceItem } from "@/features/candidate/types/candidate.types";

interface ExperienceCardProps {
  experience: ReadonlyArray<ExperienceItem>;
}

export function ExperienceCard({ experience }: ExperienceCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Briefcase className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Experience
            </h3>
          </div>

          {experience.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No experience records available yet.
            </p>
          ) : (
            <ol className="relative space-y-5 border-l border-border/70 pl-4">
              {experience.map((item, index) => (
                <motion.li
                  key={item.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: 0.05 * index }}
                  className="relative"
                >
                  <span
                    aria-hidden="true"
                    className="absolute top-1.5 -left-[21px] h-2.5 w-2.5 rounded-full bg-primary shadow-[0_0_0_4px_rgba(139,92,246,0.15)]"
                  />
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h4 className="text-sm font-semibold text-white">
                      {item.role}
                    </h4>
                    <span className="text-xs text-muted-foreground">
                      {item.startDate} - {item.endDate}
                    </span>
                  </div>
                  <p className="mt-0.5 text-sm text-primary">{item.company}</p>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {item.description}
                  </p>
                  <ul className="mt-2 space-y-1">
                    {item.highlights.map((highlight) => (
                      <li
                        key={highlight}
                        className="text-xs leading-relaxed text-muted-foreground"
                      >
                        • {highlight}
                      </li>
                    ))}
                  </ul>
                </motion.li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
