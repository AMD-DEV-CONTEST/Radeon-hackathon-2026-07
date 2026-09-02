"use client";

import { motion } from "framer-motion";
import { FolderKanban } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { ProjectItem } from "@/features/candidate/types/candidate.types";

interface ProjectsCardProps {
  projects: ReadonlyArray<ProjectItem>;
}

export function ProjectsCard({ projects }: ProjectsCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <FolderKanban className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Projects
            </h3>
          </div>

          {projects.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No projects available yet.
            </p>
          ) : null}

          <ul className="space-y-3">
            {projects.map((project, index) => (
              <motion.li
                key={project.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: 0.04 * index }}
                className="rounded-xl border border-border/70 bg-[#0f1018] p-3 transition-colors hover:border-primary/30"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-sm font-semibold text-white">
                    {project.name}
                  </h4>
                  <span className="text-xs text-primary">{project.role}</span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {project.description}
                </p>
                <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Technologies">
                  {project.technologies.map((tech) => (
                    <li
                      key={tech}
                      className="rounded-md border border-border/70 px-2 py-0.5 text-[11px] text-muted-foreground"
                    >
                      {tech}
                    </li>
                  ))}
                </ul>
              </motion.li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
