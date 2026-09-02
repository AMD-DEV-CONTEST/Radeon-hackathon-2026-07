"use client";

import { motion } from "framer-motion";
import { CircleDot } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { ActivityItem } from "@/features/dashboard/types/dashboard.types";

interface ActivityTimelineProps {
  activities: ReadonlyArray<ActivityItem>;
}

export function ActivityTimeline({ activities }: ActivityTimelineProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.12 }}
      whileHover={{ y: -2 }}
      className="h-full"
    >
      <Card className="h-full rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5">
          <h2 className="mb-4 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            Activity Timeline
          </h2>

          {activities.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Activity will appear as you practice and interview.
            </p>
          ) : (
            <ol className="space-y-4" aria-label="Activity timeline">
              {activities.map((item, index) => (
                <motion.li
                  key={item.id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.22, delay: 0.03 * index }}
                  className="flex gap-3"
                >
                  <div className="mt-0.5 flex flex-col items-center">
                    <CircleDot
                      className="h-4 w-4 text-primary"
                      aria-hidden="true"
                    />
                    {index < activities.length - 1 ? (
                      <div className="mt-1 h-full w-px grow bg-white/10" />
                    ) : null}
                  </div>
                  <div className="pb-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-white">
                        {item.title}
                      </p>
                      <Badge
                        variant="outline"
                        className="tracking-normal normal-case"
                      >
                        {item.category}
                      </Badge>
                    </div>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {item.description}
                    </p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {item.timestamp}
                    </p>
                  </div>
                </motion.li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
