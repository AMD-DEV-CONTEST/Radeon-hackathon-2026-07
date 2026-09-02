"use client";

import { motion } from "framer-motion";
import { Clock3 } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { LiveInterviewSession } from "@/features/admin/types/admin.types";
import { cn } from "@/lib/utils";

interface ActiveInterviewsProps {
  sessions: ReadonlyArray<LiveInterviewSession>;
}

export function ActiveInterviews({ sessions }: ActiveInterviewsProps) {
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
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Live Interview Sessions
            </h2>
            <Link
              href="/agents"
              className={cn(
                buttonVariants({ variant: "link" }),
                "h-auto p-0 text-xs text-primary"
              )}
            >
              View Live Map
            </Link>
          </div>

          {sessions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No live sessions.</p>
          ) : (
            <div className="overflow-x-auto">
              <table
                className="w-full min-w-[720px] text-left"
                aria-label="Live interview sessions"
              >
                <thead>
                  <tr className="border-b border-white/10 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                    <th className="pb-3 pr-3 font-semibold">Session</th>
                    <th className="pb-3 pr-3 font-semibold">Candidate</th>
                    <th className="pb-3 pr-3 font-semibold">Role</th>
                    <th className="pb-3 pr-3 font-semibold">Score</th>
                    <th className="pb-3 font-semibold">Elapsed</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((session, index) => (
                    <motion.tr
                      key={session.id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.2, delay: 0.02 * index }}
                      className="border-b border-white/5 last:border-b-0"
                    >
                      <td className="py-3 pr-3 align-middle">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-muted-foreground">
                            {session.id}
                          </span>
                          {session.status === "live" ? (
                            <Badge className="border-sky-400/30 bg-sky-500/15 text-sky-200 tracking-normal normal-case">
                              Live
                            </Badge>
                          ) : (
                            <Badge variant="secondary" className="tracking-normal normal-case capitalize">
                              {session.status}
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="py-3 pr-3 align-middle">
                        <div className="flex items-center gap-2">
                          <span
                            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-white"
                            aria-hidden="true"
                          >
                            {session.candidateInitials}
                          </span>
                          <span className="text-sm font-medium text-white">
                            {session.candidateName}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 pr-3 text-sm text-muted-foreground">
                        {session.role}
                      </td>
                      <td className="py-3 pr-3 align-middle">
                        <div className="min-w-[110px] space-y-1.5">
                          <span className="text-sm font-semibold text-white">
                            {session.score}
                          </span>
                          <Progress value={session.score} className="h-1.5" />
                        </div>
                      </td>
                      <td className="py-3 align-middle">
                        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                          <Clock3 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                          {session.elapsed}
                        </span>
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
