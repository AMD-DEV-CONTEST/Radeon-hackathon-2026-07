"use client";

import { motion } from "framer-motion";
import { Radio, Sparkles } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import type { DashboardCandidate } from "@/features/dashboard/types/dashboard.types";
import { cn } from "@/lib/utils";

interface WelcomeBannerProps {
  candidate: DashboardCandidate;
}

const STATUS_LABEL: Record<DashboardCandidate["aiAssistantStatus"], string> = {
  online: "AI Assistant Online",
  analyzing: "AI Assistant Analyzing",
  idle: "AI Assistant Idle",
};

export function WelcomeBanner({ candidate }: WelcomeBannerProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between"
      aria-label="Welcome banner"
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="purple" className="gap-1.5">
            <Sparkles className="h-3 w-3" aria-hidden="true" />
            Candidate Workspace
          </Badge>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Radio
              className={cn(
                "h-3.5 w-3.5",
                candidate.aiAssistantStatus === "online"
                  ? "text-emerald-400"
                  : candidate.aiAssistantStatus === "analyzing"
                    ? "text-sky-400"
                    : "text-muted-foreground"
              )}
              aria-hidden="true"
            />
            {STATUS_LABEL[candidate.aiAssistantStatus]}
          </span>
        </div>

        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Welcome back, {candidate.fullName.split(" ")[0]}
          </h1>
          <p className="mt-1 text-base text-muted-foreground">
            {candidate.currentRole}
          </p>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            {candidate.greeting}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <Link
          href="/interviews/report"
          className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11")}
        >
          Export Reports
        </Link>
        <Link
          href="/interviews/planning"
          className={cn(buttonVariants({ size: "lg" }), "h-11 glow-purple")}
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          Start Interview Plan
        </Link>
      </div>
    </motion.section>
  );
}
