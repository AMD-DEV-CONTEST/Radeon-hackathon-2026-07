"use client";

import { motion } from "framer-motion";
import { FileText } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { RecentInterview } from "@/features/dashboard/types/dashboard.types";
import { cn } from "@/lib/utils";

interface RecentInterviewsProps {
  interviews: ReadonlyArray<RecentInterview>;
}

function formatInterviewDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function RecentInterviews({ interviews }: RecentInterviewsProps) {
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
            Recent Interviews
          </h2>

          {interviews.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No interviews found. Complete a mock interview to see recent
              results.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table
                className="w-full min-w-[720px] text-left"
                aria-label="Recent interviews"
              >
                <thead>
                  <tr className="border-b border-white/10 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                    <th className="pb-3 pr-3 font-semibold">Company</th>
                    <th className="pb-3 pr-3 font-semibold">Position</th>
                    <th className="pb-3 pr-3 font-semibold">Date</th>
                    <th className="pb-3 pr-3 font-semibold">Status</th>
                    <th className="pb-3 pr-3 font-semibold">Score</th>
                    <th className="pb-3 font-semibold">Report</th>
                  </tr>
                </thead>
                <tbody>
                  {interviews.map((item, index) => (
                    <motion.tr
                      key={item.id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.22, delay: 0.03 * index }}
                      className="border-b border-white/5 last:border-b-0"
                    >
                      <td className="py-3 pr-3 align-middle text-sm text-white">
                        {item.company}
                      </td>
                      <td className="py-3 pr-3 align-middle">
                        <p className="text-sm font-medium text-white">
                          {item.position || item.name}
                        </p>
                      </td>
                      <td className="py-3 pr-3 align-middle text-xs text-muted-foreground">
                        {formatInterviewDate(item.completedAt)}
                      </td>
                      <td className="py-3 pr-3 align-middle">
                        <Badge
                          variant="purple"
                          className="capitalize tracking-normal normal-case"
                        >
                          {item.status}
                        </Badge>
                      </td>
                      <td className="py-3 pr-3 align-middle">
                        <div className="min-w-[120px] space-y-1.5">
                          <span className="text-sm font-semibold text-white">
                            {item.score}
                          </span>
                          <Progress value={item.score} className="h-1.5" />
                        </div>
                      </td>
                      <td className="py-3 align-middle">
                        <Link
                          href={`/interviews/report?id=${item.reportId}`}
                          className={cn(
                            buttonVariants({ variant: "outline", size: "sm" }),
                            "h-8"
                          )}
                          aria-label={`View report for ${item.position || item.name}`}
                        >
                          <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                          View Report
                        </Link>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
