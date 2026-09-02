"use client";

import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import type { PlatformOverview } from "@/features/admin/types/admin.types";
import { cn } from "@/lib/utils";

interface AdminHeaderProps {
  overview: PlatformOverview;
}

export function AdminHeader({ overview }: AdminHeaderProps) {
  return (
    <motion.header
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between"
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="purple">Platform Real-time Monitor</Badge>
          <Badge variant="outline" className="tracking-normal normal-case">
            Region: {overview.region}
          </Badge>
          <Badge
            className="border-emerald-400/30 bg-emerald-500/10 text-emerald-200 tracking-normal normal-case"
          >
            Health {overview.globalHealthPercent}%
          </Badge>
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Admin Dashboard
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            Monitoring platform throughput, AI agent efficiency, and global
            candidate health.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <Link
          href="/presentation"
          className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11")}
        >
          Export Reports
        </Link>
        <Link
          href="/agents"
          className={cn(buttonVariants({ size: "lg" }), "h-11 glow-purple")}
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          AI Optimization Plan
        </Link>
      </div>
    </motion.header>
  );
}
