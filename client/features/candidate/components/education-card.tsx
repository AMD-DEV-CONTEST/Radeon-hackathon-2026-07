"use client";

import { motion } from "framer-motion";
import { Award, GraduationCap } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type {
  CertificationItem,
  EducationItem,
} from "@/features/candidate/types/candidate.types";

interface EducationCardProps {
  education: ReadonlyArray<EducationItem>;
  certifications: ReadonlyArray<CertificationItem>;
}

export function EducationCard({
  education,
  certifications,
}: EducationCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.12 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-5 p-5">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <GraduationCap className="h-4 w-4 text-primary" aria-hidden="true" />
              <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Education
              </h3>
            </div>
            {education.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No education records available yet.
              </p>
            ) : (
              <ul className="space-y-3">
                {education.map((item) => (
                  <li
                    key={item.id}
                    className="rounded-xl border border-border/70 bg-[#0f1018] p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-semibold text-white">
                        {item.degree}
                      </p>
                      <span className="text-xs text-muted-foreground">
                        {item.year}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-primary">{item.institution}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {item.details}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {certifications.length > 0 ? (
            <div>
              <div className="mb-3 flex items-center gap-2">
                <Award className="h-4 w-4 text-primary" aria-hidden="true" />
                <h3 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                  Certifications
                </h3>
              </div>
              <ul className="space-y-2">
                {certifications.map((cert) => (
                  <li
                    key={cert.id}
                    className="flex items-start justify-between gap-3 rounded-xl border border-border/70 bg-[#0f1018] px-3 py-2.5"
                  >
                    <div>
                      <p className="text-sm font-medium text-white">
                        {cert.name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {cert.issuer}
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {cert.year}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </motion.div>
  );
}
