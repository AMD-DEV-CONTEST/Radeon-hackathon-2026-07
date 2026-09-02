"use client";

import { motion } from "framer-motion";
import { Download, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type {
  ExecutionLogEntry,
  LogLevel,
} from "@/features/agents/types/agents.types";
import { cn } from "@/lib/utils";

interface LogsPanelProps {
  logs: ReadonlyArray<ExecutionLogEntry>;
}

const STATUS_CLASS: Record<LogLevel, string> = {
  info: "border-border/70 bg-muted/30 text-muted-foreground",
  success: "border-cyan-400/30 bg-cyan-500/10 text-cyan-200",
  pending: "border-primary/30 bg-primary/10 text-primary",
  retry: "border-amber-400/30 bg-amber-500/10 text-amber-200",
  error: "border-destructive/30 bg-destructive/10 text-destructive",
};

type FilterKey = "all" | LogLevel;

export function LogsPanel({ logs }: LogsPanelProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  const filteredLogs = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return logs.filter((entry) => {
      const matchesFilter = filter === "all" || entry.status === filter;
      const matchesQuery =
        normalized.length === 0 ||
        entry.agent.toLowerCase().includes(normalized) ||
        entry.action.toLowerCase().includes(normalized);
      return matchesFilter && matchesQuery;
    });
  }, [filter, logs, query]);

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
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Multi-Agent Execution Log
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[200px] flex-1">
                <Search
                  className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                  aria-hidden="true"
                />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search logs..."
                  className="h-9 pl-9"
                  aria-label="Search execution logs"
                />
              </div>
              <div
                className="flex flex-wrap gap-1"
                role="group"
                aria-label="Filter logs by status"
              >
                {(
                  ["all", "success", "pending", "retry", "error", "info"] as const
                ).map((key) => (
                  <Button
                    key={key}
                    type="button"
                    size="sm"
                    variant={filter === key ? "default" : "outline"}
                    className="h-8 capitalize"
                    aria-pressed={filter === key}
                    onClick={() => setFilter(key)}
                  >
                    {key}
                  </Button>
                ))}
              </div>
              <Button
                type="button"
                variant="outline"
                className="h-9"
                onClick={() =>
                  setExportMessage(`Exported ${filteredLogs.length} log entries`)
                }
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                Export Logs
              </Button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table
              className="w-full min-w-[720px] text-left"
              aria-label="Execution logs"
            >
              <thead>
                <tr className="border-b border-white/10 text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
                  <th className="pb-3 pr-3 font-semibold">Timestamp</th>
                  <th className="pb-3 pr-3 font-semibold">Agent</th>
                  <th className="pb-3 pr-3 font-semibold">Action</th>
                  <th className="pb-3 pr-3 font-semibold">Status</th>
                  <th className="pb-3 font-semibold">Latency</th>
                </tr>
              </thead>
              <tbody>
                {filteredLogs.length === 0 ? (
                  <tr>
                    <td
                      colSpan={5}
                      className="py-8 text-center text-sm text-muted-foreground"
                    >
                      No logs match the current filters.
                    </td>
                  </tr>
                ) : (
                  filteredLogs.map((entry, index) => (
                    <motion.tr
                      key={entry.id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.2, delay: 0.02 * index }}
                      className="border-b border-white/5 last:border-b-0"
                    >
                      <td className="py-3 pr-3 font-mono text-xs text-muted-foreground">
                        {entry.timestamp}
                      </td>
                      <td className="py-3 pr-3 text-sm font-medium text-primary">
                        {entry.agent}
                      </td>
                      <td className="py-3 pr-3 text-sm text-muted-foreground">
                        {entry.action}
                      </td>
                      <td className="py-3 pr-3">
                        <Badge
                          className={cn(
                            "tracking-normal normal-case capitalize",
                            STATUS_CLASS[entry.status]
                          )}
                        >
                          {entry.status}
                        </Badge>
                      </td>
                      <td className="py-3 font-mono text-xs text-white">
                        {entry.latencyMs}ms
                      </td>
                    </motion.tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <p className="sr-only" role="status" aria-live="polite">
            {exportMessage}
          </p>
          {exportMessage ? (
            <p className="mt-3 text-xs text-muted-foreground">{exportMessage}</p>
          ) : null}
        </CardContent>
      </Card>
    </motion.div>
  );
}
