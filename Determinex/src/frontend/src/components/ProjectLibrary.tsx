/**
 * ProjectLibrary.tsx — Past Session Browser
 *
 * Displays all Hive build sessions on disk, grouped by date:
 *   Today / This Week / Older
 *
 * Each card shows: project name, language, status, step completion, date.
 * Two resume actions:
 *   Resume         → load the session in HiveBuildLoop as-is
 *   Resume & Retry → load + autoRetry flag (for failed sessions)
 */

"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  RefreshCw,
  BookOpen,
  Zap,
  RotateCcw,
  AlertTriangle,
  ChevronRight,
} from "lucide-react";
import { listHiveSessions, HiveSessionSummary } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

export interface ProjectLibraryProps {
  /** Called when the user clicks Resume. shouldRetry=true when "Resume & Retry" clicked. */
  onResume: (sessionId: string, projectName: string, shouldRetry: boolean) => void;
  onClose: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

const LANG_COLORS: Record<string, string> = {
  rust: "text-orange-400 bg-orange-950/40 border-orange-800/40",
  python: "text-blue-400 bg-blue-950/40 border-blue-800/40",
  go: "text-cyan-400 bg-cyan-950/40 border-cyan-800/40",
  typescript: "text-sky-400 bg-sky-950/40 border-sky-800/40",
  javascript: "text-yellow-400 bg-yellow-950/40 border-yellow-800/40",
  java: "text-red-400 bg-red-950/40 border-red-800/40",
  csharp: "text-purple-400 bg-purple-950/40 border-purple-800/40",
  cpp: "text-emerald-400 bg-emerald-950/40 border-emerald-800/40",
};

function langBadge(lang: string): string {
  return LANG_COLORS[lang.toLowerCase()] ?? "text-gray-400 bg-gray-800/40 border-gray-700/40";
}

const STATUS_CONFIGS = {
  complete: {
    label: "Complete",
    icon: CheckCircle2,
    color: "text-emerald-400",
    bgBorder: "border-emerald-800/30 bg-emerald-950/20",
    badgeBg: "text-emerald-400 bg-emerald-950/40 border-emerald-800/40",
  },
  failed: {
    label: "Failed",
    icon: XCircle,
    color: "text-red-400",
    bgBorder: "border-red-800/30 bg-red-950/10",
    badgeBg: "text-red-400 bg-red-950/40 border-red-800/40",
  },
  in_progress: {
    label: "In Progress",
    icon: Loader2,
    color: "text-cyan-400",
    bgBorder: "border-cyan-800/30 bg-cyan-950/10",
    badgeBg: "text-cyan-400 bg-cyan-950/40 border-cyan-800/40",
  },
  pending: {
    label: "Pending",
    icon: Clock,
    color: "text-gray-500",
    bgBorder: "border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)]/60",
    badgeBg: "text-gray-500 bg-[var(--dtx-code-panel)] border-[var(--dtx-code-border)]",
  },
};

function formatDate(iso: string): string {
  if (!iso) return "Unknown date";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso.slice(0, 16).replace("T", " ");
  }
}

function groupByDate(sessions: HiveSessionSummary[]): Record<string, HiveSessionSummary[]> {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const weekStart = todayStart - 6 * 24 * 60 * 60 * 1000;

  const groups: Record<string, HiveSessionSummary[]> = {
    Today: [],
    "This Week": [],
    Older: [],
  };

  for (const s of sessions) {
    const ts = s.created_at ? new Date(s.created_at).getTime() : 0;
    if (ts >= todayStart) groups["Today"].push(s);
    else if (ts >= weekStart) groups["This Week"].push(s);
    else groups["Older"].push(s);
  }

  // Remove empty groups
  Object.keys(groups).forEach((k) => {
    if (groups[k].length === 0) delete groups[k];
  });

  return groups;
}

// ─────────────────────────────────────────────────────────────────────────────
// SESSION CARD
// ─────────────────────────────────────────────────────────────────────────────

function SessionCard({
  session,
  onResume,
}: {
  session: HiveSessionSummary;
  onResume: (id: string, name: string, retry: boolean) => void;
}) {
  const cfg = STATUS_CONFIGS[session.status] ?? STATUS_CONFIGS.pending;
  const StatusIcon = cfg.icon;
  const pct =
    session.step_count > 0 ? Math.round((session.complete_count / session.step_count) * 100) : 0;

  return (
    <div
      className={`rounded-xl border overflow-hidden transition-all hover:border-opacity-60 group ${cfg.bgBorder}`}
    >
      {/* Card header */}
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <StatusIcon
          size={13}
          className={`${cfg.color} flex-shrink-0 mt-0.5 ${session.status === "in_progress" ? "animate-spin" : ""}`}
        />
        <div className="flex-1 min-w-0">
          <p className="text-body font-bold text-gray-200 truncate leading-tight">
            {session.project_name}
          </p>
          <p className="text-meta font-mono text-gray-600 mt-0.5 truncate">
            {session.session_id.slice(0, 18)}…
          </p>
        </div>
        {/* Language badge */}
        <span
          className={`text-eyebrow font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border flex-shrink-0 ${langBadge(session.lang)}`}
        >
          {session.lang}
        </span>
      </div>

      {/* Progress bar + metadata */}
      <div className="px-3 pb-2 space-y-1.5">
        {/* Step progress bar */}
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1 rounded-full bg-[var(--dtx-code-panel)] overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                session.status === "complete"
                  ? "bg-emerald-500"
                  : session.status === "failed"
                    ? "bg-red-500"
                    : session.status === "in_progress"
                      ? "bg-cyan-500"
                      : "bg-gray-600"
              }`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-meta font-mono text-gray-500 flex-shrink-0">
            {session.complete_count}/{session.step_count}
          </span>
        </div>

        {/* Meta row */}
        <div className="flex items-center justify-between">
          <span className={`text-meta font-bold px-1.5 py-0.5 rounded border ${cfg.badgeBg}`}>
            {cfg.label}
            {session.status === "failed" &&
              session.failed_count > 0 &&
              ` (${session.failed_count} step${session.failed_count !== 1 ? "s" : ""})`}
          </span>
          <span className="text-meta text-gray-600 font-mono">
            {formatDate(session.created_at)}
          </span>
        </div>
      </div>

      {/* Action row — revealed on hover */}
      <div className="flex border-t border-[var(--dtx-code-border)]/50 divide-x divide-[var(--dtx-code-border)]/50 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          id={`lib-resume-${session.session_id.slice(0, 8)}`}
          onClick={() => onResume(session.session_id, session.project_name, false)}
          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-meta font-bold text-gray-400 hover:text-gray-200 hover:bg-white/[0.03] transition-colors"
        >
          <ChevronRight size={10} />
          Resume
        </button>

        {session.status === "failed" && (
          <button
            id={`lib-retry-${session.session_id.slice(0, 8)}`}
            onClick={() => onResume(session.session_id, session.project_name, true)}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-meta font-bold text-emerald-500 hover:text-emerald-400 hover:bg-emerald-950/30 transition-colors"
          >
            <RotateCcw size={10} />
            Resume & Retry
          </button>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

export function ProjectLibrary({ onResume, onClose }: ProjectLibraryProps) {
  const [sessions, setSessions] = useState<HiveSessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "complete" | "failed" | "in_progress">("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listHiveSessions();
      setSessions(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = filter === "all" ? sessions : sessions.filter((s) => s.status === filter);
  const groups = groupByDate(filtered);

  const counts = {
    all: sessions.length,
    complete: sessions.filter((s) => s.status === "complete").length,
    failed: sessions.filter((s) => s.status === "failed").length,
    in_progress: sessions.filter((s) => s.status === "in_progress").length,
  };

  return (
    <div className="flex flex-col h-full bg-[var(--dtx-code-bg)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)]/60 flex-shrink-0">
        <BookOpen size={14} className="text-emerald-400" />
        <div className="flex-1 min-w-0">
          <span className="text-body font-black text-gray-200 tracking-tight">Project Library</span>
          <span className="text-label text-gray-600 ml-2 font-mono">
            {sessions.length} session{sessions.length !== 1 ? "s" : ""}
          </span>
        </div>
        <button
          onClick={load}
          disabled={loading}
          title="Refresh"
          className="p-1.5 rounded-lg border border-[var(--dtx-code-border)] text-gray-500 hover:text-gray-300 hover:border-gray-500 transition-colors disabled:opacity-40"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
        <button
          onClick={onClose}
          title="Close library"
          className="p-1.5 rounded-lg border border-[var(--dtx-code-border)] text-gray-500 hover:text-gray-300 hover:border-gray-500 transition-colors"
        >
          <span className="text-body leading-none">✕</span>
        </button>
      </div>

      {/* Filter chips */}
      <div className="flex gap-1.5 px-4 py-2 border-b border-[var(--dtx-code-border)] flex-shrink-0 overflow-x-auto">
        {(["all", "complete", "failed", "in_progress"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`flex-shrink-0 text-eyebrow font-bold uppercase tracking-wider px-2 py-1 rounded-full border transition-all ${
              filter === f
                ? f === "complete"
                  ? "border-emerald-600 bg-emerald-950/40 text-emerald-300"
                  : f === "failed"
                    ? "border-red-700 bg-red-950/40 text-red-300"
                    : f === "in_progress"
                      ? "border-cyan-700 bg-cyan-950/40 text-cyan-300"
                      : "border-gray-500 bg-[var(--dtx-code-panel)] text-gray-300"
                : "border-[var(--dtx-code-border)] text-gray-600 hover:text-gray-400 hover:border-gray-600"
            }`}
          >
            {f === "in_progress" ? "Running" : f.charAt(0).toUpperCase() + f.slice(1)}{" "}
            <span className="opacity-60">({counts[f]})</span>
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-5">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-label text-gray-500 font-mono">Scanning sessions...</p>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <AlertTriangle size={22} className="text-red-500" />
            <p className="text-label text-red-400 font-bold">Could not load sessions</p>
            <p className="text-label text-gray-600 font-mono text-center break-all">{error}</p>
            <button
              onClick={load}
              className="text-label text-cyan-400 hover:text-cyan-300 underline underline-offset-2"
            >
              Try again
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <Zap size={22} className="text-gray-700" />
            <p className="text-label text-gray-600 font-mono">
              {filter === "all"
                ? "No build sessions yet."
                : `No ${filter.replace("_", " ")} sessions.`}
            </p>
          </div>
        ) : (
          Object.entries(groups).map(([group, items]) => (
            <div key={group}>
              <p className="text-eyebrow uppercase font-black tracking-widest text-gray-600 mb-2">
                {group}
              </p>
              <div className="space-y-2">
                {items.map((s) => (
                  <SessionCard key={s.session_id} session={s} onResume={onResume} />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
