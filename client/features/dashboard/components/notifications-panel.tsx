"use client";

import { motion } from "framer-motion";
import { Bell, Lightbulb, CalendarClock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { DashboardNotification } from "@/features/dashboard/types/dashboard.types";
import { cn } from "@/lib/utils";

interface NotificationsPanelProps {
  notifications: ReadonlyArray<DashboardNotification>;
}

const KIND_META: Record<
  DashboardNotification["kind"],
  { label: string; icon: typeof Bell; className: string }
> = {
  activity: {
    label: "Activity",
    icon: Bell,
    className: "border-sky-400/30 bg-sky-500/10 text-sky-200",
  },
  suggestion: {
    label: "AI Suggestion",
    icon: Lightbulb,
    className: "border-primary/30 bg-primary/10 text-primary",
  },
  reminder: {
    label: "Reminder",
    icon: CalendarClock,
    className: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  },
};

export function NotificationsPanel({
  notifications,
}: NotificationsPanelProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.14 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Notifications
          </h2>

          {notifications.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              You are all caught up.
            </p>
          ) : (
            <ul className="space-y-3" aria-label="Notifications">
              {notifications.map((item, index) => {
                const meta = KIND_META[item.kind];
                const Icon = meta.icon;

                return (
                  <motion.li
                    key={item.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.22, delay: 0.03 * index }}
                    className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <Badge
                        className={cn(
                          "gap-1 tracking-normal normal-case",
                          meta.className
                        )}
                      >
                        <Icon className="h-3 w-3" aria-hidden="true" />
                        {meta.label}
                      </Badge>
                      <span className="text-[11px] text-muted-foreground">
                        {item.timestamp}
                      </span>
                    </div>
                    <p className="text-sm font-medium text-white">{item.title}</p>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                      {item.message}
                    </p>
                  </motion.li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
