"use client";

import { motion } from "framer-motion";
import { Building2, CalendarDays, Clock3 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { UpcomingInterview } from "@/features/dashboard/types/dashboard.types";
import { cn } from "@/lib/utils";

interface UpcomingInterviewsProps {
  interviews: ReadonlyArray<UpcomingInterview>;
}

const STATUS_CLASS: Record<UpcomingInterview["status"], string> = {
  scheduled: "border-sky-400/30 bg-sky-500/10 text-sky-200",
  confirmed: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
  live: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  completed: "border-primary/30 bg-primary/10 text-primary",
  cancelled: "border-destructive/30 bg-destructive/10 text-destructive",
};

function formatDate(isoDate: string): string {
  const value = isoDate.includes("T") ? isoDate : `${isoDate}T00:00:00`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return isoDate;
  }
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function UpcomingInterviews({ interviews }: UpcomingInterviewsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.08 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Upcoming Interviews
          </h2>

          {interviews.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No upcoming interviews scheduled.
            </p>
          ) : (
            <ul className="space-y-3" aria-label="Upcoming interviews">
              {interviews.map((item, index) => (
                <motion.li
                  key={item.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: 0.04 * index }}
                  className="rounded-xl border border-white/5 bg-[#0f1018] p-3"
                >
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <p className="font-mono text-xs text-muted-foreground">
                      {item.id}
                    </p>
                    <Badge
                      className={cn(
                        "tracking-normal normal-case capitalize",
                        STATUS_CLASS[item.status]
                      )}
                    >
                      {item.status}
                    </Badge>
                  </div>
                  <p className="text-sm font-semibold text-white">
                    {item.position}
                  </p>
                  <p className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Building2 className="h-3.5 w-3.5" aria-hidden="true" />
                    {item.company}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <CalendarDays className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                      {formatDate(item.date)}
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Clock3 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                      {item.time}
                    </span>
                  </div>
                </motion.li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
