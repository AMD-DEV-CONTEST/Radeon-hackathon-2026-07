"use client";

import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { Building2, CalendarDays, Briefcase } from "lucide-react";
import { useEffect } from "react";

import { RecommendationCard } from "@/features/presentation/components/recommendation-card";
import type { PresentationDashboard } from "@/features/presentation/types/presentation.types";

interface PresentationHeaderProps {
  data: PresentationDashboard;
}

function AnimatedScore({ value }: { value: number }) {
  const motionValue = useMotionValue(0);
  const spring = useSpring(motionValue, { stiffness: 90, damping: 18 });
  const display = useTransform(spring, (latest) => Math.round(latest));

  useEffect(() => {
    motionValue.set(value);
  }, [motionValue, value]);

  return <motion.span>{display}</motion.span>;
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function PresentationHeader({ data }: PresentationHeaderProps) {
  const { candidate, scores, recommendation, recommendationExplanation } = data;

  return (
    <motion.header
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]"
    >
      <div className="rounded-2xl border border-white/10 bg-[#12121a]/80 p-5 sm:p-6 backdrop-blur-xl">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-4">
            <div
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 to-blue-500 text-base font-bold text-white"
              aria-hidden="true"
            >
              {candidate.avatarInitials}
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
                {candidate.fullName}
              </h1>
              <p className="mt-1 inline-flex items-center gap-2 text-sm text-muted-foreground">
                <Briefcase className="h-4 w-4 text-primary" aria-hidden="true" />
                {candidate.appliedRole}
              </p>
              <div className="mt-3 flex flex-wrap gap-4 text-sm text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Building2 className="h-4 w-4 text-primary" aria-hidden="true" />
                  {candidate.company}
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <CalendarDays className="h-4 w-4 text-primary" aria-hidden="true" />
                  {formatDate(candidate.interviewDate)}
                </span>
              </div>
            </div>
          </div>

          <div className="text-left sm:text-right">
            <p className="text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
              Overall Score
            </p>
            <p
              className="mt-1 text-5xl font-bold tracking-tight text-white"
              aria-label={`Overall score ${scores.overall} out of 100`}
            >
              <AnimatedScore value={scores.overall} />
              <span className="text-xl font-semibold text-muted-foreground">
                {" "}
                /100
              </span>
            </p>
          </div>
        </div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.06 }}
        whileHover={{ y: -2 }}
      >
        <RecommendationCard
          recommendation={recommendation}
          explanation={recommendationExplanation}
          className="h-full"
        />
      </motion.div>
    </motion.header>
  );
}
