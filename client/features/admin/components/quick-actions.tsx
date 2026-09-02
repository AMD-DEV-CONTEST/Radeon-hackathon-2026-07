"use client";

import { motion } from "framer-motion";
import {
  FileBarChart2,
  Play,
  ScrollText,
  Share2,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { AdminQuickAction } from "@/features/admin/types/admin.types";
import { cn } from "@/lib/utils";

interface QuickActionsProps {
  actions: ReadonlyArray<AdminQuickAction>;
}

const ICONS: Record<string, typeof Play> = {
  "qa-demo": Play,
  "qa-report": FileBarChart2,
  "qa-export": Share2,
  "qa-logs": ScrollText,
  "qa-users": Users,
};

export function QuickActions({ actions }: QuickActionsProps) {
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Quick Actions
          </h2>
          <ul
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"
            aria-label="Admin quick actions"
          >
            {actions.map((action, index) => {
              const Icon = ICONS[action.id] ?? Play;
              const isExport = action.id === "qa-export";

              return (
                <motion.li
                  key={action.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: 0.03 * index }}
                >
                  {isExport ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="h-auto w-full flex-col items-start gap-2 px-3 py-3 text-left"
                      onClick={() =>
                        setStatusMessage("Analytics export prepared (mock)")
                      }
                    >
                      <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                      <span className="text-sm font-semibold text-white">
                        {action.label}
                      </span>
                      <span className="text-xs font-normal text-muted-foreground">
                        {action.description}
                      </span>
                    </Button>
                  ) : (
                    <Link
                      href={action.href}
                      className={cn(
                        "flex h-full flex-col rounded-xl border border-white/10 bg-[#0f1018] px-3 py-3 transition-colors hover:border-white/20 hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                      )}
                    >
                      <Icon className="mb-2 h-4 w-4 text-primary" aria-hidden="true" />
                      <span className="text-sm font-semibold text-white">
                        {action.label}
                      </span>
                      <span className="mt-1 text-xs text-muted-foreground">
                        {action.description}
                      </span>
                    </Link>
                  )}
                </motion.li>
              );
            })}
          </ul>
          <p className="sr-only" role="status" aria-live="polite">
            {statusMessage}
          </p>
          {statusMessage ? (
            <p className="mt-3 text-xs text-muted-foreground">{statusMessage}</p>
          ) : null}
        </CardContent>
      </Card>
    </motion.div>
  );
}
