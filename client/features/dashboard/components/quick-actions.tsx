"use client";

import { motion } from "framer-motion";
import {
  FileBarChart2,
  Play,
  Settings,
  Upload,
} from "lucide-react";
import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";
import type { QuickAction } from "@/features/dashboard/types/dashboard.types";
import { cn } from "@/lib/utils";

interface QuickActionsProps {
  actions: ReadonlyArray<QuickAction>;
}

const ACTION_ICON: Record<string, typeof Upload> = {
  "qa-resume": Upload,
  "qa-mock": Play,
  "qa-reports": FileBarChart2,
  "qa-settings": Settings,
};

export function QuickActions({ actions }: QuickActionsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.1 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Quick Actions
          </h2>

          <ul
            className="grid gap-3 sm:grid-cols-2"
            aria-label="Quick actions"
          >
            {actions.map((action, index) => {
              const Icon = ACTION_ICON[action.id] ?? Play;
              const isPrimary = action.id === "qa-mock";

              return (
                <motion.li
                  key={action.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.22, delay: 0.03 * index }}
                >
                  <Link
                    href={action.href}
                    className={cn(
                      "flex h-full flex-col rounded-xl border px-3 py-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
                      isPrimary
                        ? "border-primary/40 bg-primary/15 hover:bg-primary/20"
                        : "border-white/10 bg-[#0f1018] hover:border-white/20 hover:bg-white/5"
                    )}
                  >
                    <span className="mb-2 inline-flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-primary">
                      <Icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <span className="text-sm font-semibold text-white">
                      {action.label}
                    </span>
                    <span className="mt-1 text-xs text-muted-foreground">
                      {action.description}
                    </span>
                  </Link>
                </motion.li>
              );
            })}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
