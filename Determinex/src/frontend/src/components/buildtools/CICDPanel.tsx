"use client";
import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Check,
  X,
  Clock,
  Loader2,
  RefreshCw,
  ExternalLink,
  AlertTriangle,
  CircleDashed,
} from "lucide-react";
import { isTauri } from "@/lib/api";

/**
 * Real CI runs for the open workspace, via the `gh` CLI.
 *
 * This panel was `INITIAL_RUNS: Run[] = []` that nothing populated, plus a
 * "Connect a CI provider" note and no way to connect one. It could never show
 * anything.
 *
 * `gh` rather than the GitHub REST API because it already holds the user's
 * auth; a second credential path for the same service would duplicate what
 * Passport and the Device Flow sign-in already do.
 *
 * Read-only: listing runs is not the same authority as re-running or cancelling
 * one. Every empty state names its own reason (no workspace, not a repo, gh not
 * installed, not signed in, no runs yet) rather than showing a bare empty list,
 * which is what this panel did permanently.
 */

type CiRun = {
  databaseId: number;
  displayTitle: string;
  status: string;
  conclusion: string;
  workflowName: string;
  headBranch: string;
  createdAt: string;
  url: string;
};
type CiStatus = { available: boolean; runs: CiRun[]; note?: string | null };

function verdict(run: CiRun) {
  if (run.status !== "completed") {
    return {
      Icon: Loader2,
      cls: "text-amber-400",
      spin: run.status === "in_progress",
      label: run.status,
    };
  }
  switch (run.conclusion) {
    case "success":
      return { Icon: Check, cls: "text-emerald-400", spin: false, label: "success" };
    case "cancelled":
    case "skipped":
      return { Icon: CircleDashed, cls: "text-gray-500", spin: false, label: run.conclusion };
    default:
      // startup_failure, failure, timed_out -- all genuinely bad, and worth
      // showing distinctly rather than flattening to "failed".
      return { Icon: X, cls: "text-red-400", spin: false, label: run.conclusion || "failure" };
  }
}

function ago(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const mins = Math.floor((Date.now() - t) / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function CICDPanel({ workspacePath = "" }: { workspacePath?: string }) {
  const [state, setState] = useState<CiStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!isTauri()) return;
    setLoading(true);
    setError(null);
    try {
      setState(await invoke<CiStatus>("list_ci_runs", { workspace: workspacePath, limit: 20 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [workspacePath]);

  useEffect(() => {
    load();
  }, [load]);

  if (!isTauri()) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-label text-gray-600">CI runs need the desktop runtime.</p>
      </div>
    );
  }

  const runs = state?.runs ?? [];
  const failing = runs.filter(
    (r) => r.status === "completed" && !["success", "skipped", "cancelled"].includes(r.conclusion)
  ).length;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 border-b border-white/8 px-4 py-2.5">
        <span className="text-meta font-black uppercase tracking-widest text-gray-400">CI</span>
        <span className="font-mono text-meta text-gray-600">
          {runs.length} run{runs.length === 1 ? "" : "s"}
          {failing > 0 && ` · ${failing} not passing`}
        </span>
        <div className="flex-1" />
        <button
          onClick={load}
          disabled={loading}
          title="Reload"
          data-testid="cicd-reload"
          className="rounded p-1 text-gray-500 transition-colors hover:text-gray-200 disabled:opacity-40"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && (
        <div className="flex shrink-0 items-start gap-2 border-b border-red-500/25 bg-red-950/20 px-4 py-2">
          <AlertTriangle size={11} className="mt-0.5 shrink-0 text-red-400" />
          <p className="font-mono text-label text-red-300">{error}</p>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-2">
        {runs.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1 py-16">
            <p className="text-label text-gray-500">
              {loading ? "Checking CI…" : "No CI runs to show"}
            </p>
            {/* The backend always explains an empty list; show that verbatim
                rather than inventing a generic message over it. */}
            {state?.note && (
              <p
                data-testid="cicd-empty-reason"
                className="max-w-[320px] text-center text-meta leading-relaxed text-gray-700"
              >
                {state.note}
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-1">
            {runs.map((r) => {
              const v = verdict(r);
              return (
                <div
                  key={r.databaseId}
                  data-testid={`ci-run-${r.databaseId}`}
                  className="flex items-center gap-2.5 rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2"
                >
                  <v.Icon
                    size={12}
                    className={`${v.cls} shrink-0 ${v.spin ? "animate-spin" : ""}`}
                  />
                  <span className="min-w-0 flex-1 truncate text-label text-white/80">
                    {r.displayTitle || `run ${r.databaseId}`}
                  </span>
                  <span className={`shrink-0 font-mono text-meta ${v.cls}`}>{v.label}</span>
                  <span className="w-28 shrink-0 truncate font-mono text-meta text-gray-600">
                    {r.headBranch}
                  </span>
                  <span className="w-16 shrink-0 text-right font-mono text-meta text-gray-700">
                    {ago(r.createdAt)}
                  </span>
                  {r.url && (
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      title="Open on GitHub"
                      className="shrink-0 text-gray-600 transition-colors hover:text-gray-200"
                    >
                      <ExternalLink size={10} />
                    </a>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <p className="flex shrink-0 items-center gap-1.5 border-t border-white/5 px-4 py-1.5 font-mono text-meta text-gray-700">
        <Clock size={9} /> Read-only via the gh CLI. Re-running and cancelling are deliberately not
        exposed here.
      </p>
    </div>
  );
}
