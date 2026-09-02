"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, Gauge, RefreshCw, Target, TrendingUp } from "lucide-react";
import { getProgramBenchSnapshot, type ProgramBenchSnapshot } from "@/lib/api";

function pct(n?: number) {
  return typeof n === "number" ? `${n.toFixed(1)}%` : "0.0%";
}

// How many locked-tool rows to render in the drilldown. The true total is
// always shown in the header so truncation is explicit, never silent.
const DRILLDOWN_LIMIT = 12;

export function ProgramBenchCockpit() {
  const [snap, setSnap] = useState<ProgramBenchSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await getProgramBenchSnapshot();
      setSnap(next);
      if (!next) setError("Tauri cockpit unavailable in browser mode.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, []);

  const progress = snap?.progress?.pct_done ?? 0;
  const topFamily = snap?.top_families?.[0];
  const patch = snap?.recommended_patch;
  const lockedTools = snap?.locked_tools ?? [];
  const lockedCount = snap?.locked_count ?? lockedTools.length;
  const shownTools = lockedTools.slice(0, DRILLDOWN_LIMIT);

  return (
    <div className="border-b border-[var(--dtx-code-border)] bg-[#090d12]">
      <div className="p-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Target size={13} className="text-orange-400 shrink-0" />
          <div className="min-w-0">
            <div className="text-eyebrow uppercase tracking-widest font-black text-orange-400">
              ProgramBench Cockpit
            </div>
            <div className="text-meta text-gray-500 font-mono truncate">
              {snap
                ? `${snap.run_id} - ${snap.n_completed_tasks}/${snap.progress?.expected_total ?? 115} tools`
                : "Waiting for ledger snapshot"}
            </div>
          </div>
        </div>
        <button
          onClick={refresh}
          className="p-1.5 rounded-lg border border-white/10 text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
          title="Refresh cockpit"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="px-3 pb-3">
        <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
          <div
            className="h-full bg-orange-400 transition-all"
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>

        {error ? (
          <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-950/20 p-2 text-meta text-amber-300">
            <AlertTriangle size={12} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        ) : (
          <div className="mt-3 grid grid-cols-3 gap-2">
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
              <div className="flex items-center gap-1.5 text-eyebrow uppercase tracking-widest text-gray-500 font-bold">
                <Gauge size={10} /> Avg
              </div>
              <div className="mt-1 text-title font-black text-white">
                {snap?.rolling_avg_score?.toFixed(1) ?? "0.0"}
              </div>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
              <div className="flex items-center gap-1.5 text-eyebrow uppercase tracking-widest text-gray-500 font-bold">
                <Activity size={10} /> Tests
              </div>
              <div className="mt-1 text-title font-black text-white">
                {pct(snap?.pct_tests_passing)}
              </div>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
              <div className="flex items-center gap-1.5 text-eyebrow uppercase tracking-widest text-gray-500 font-bold">
                <TrendingUp size={10} /> Perfect (Live)
              </div>
              <div
                className="mt-1 text-title font-black text-white"
                title="Perfect (100%) scores in this run snapshot -- not the same count as the archived Locked Tools list below, which is not provenance-gated."
              >
                {snap?.perfect_scores ?? 0}
              </div>
            </div>
          </div>
        )}

        {(topFamily || patch) && (
          <div className="mt-3 rounded-lg border border-orange-500/20 bg-orange-950/10 p-2.5">
            {topFamily && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-meta text-gray-500 font-mono">Top family</span>
                <span className="text-meta text-orange-300 font-mono truncate">
                  {topFamily.family} - {topFamily.failures.toLocaleString()} failures
                </span>
              </div>
            )}
            {patch && (
              <div className="mt-2 border-t border-white/10 pt-2">
                <div className="text-eyebrow uppercase tracking-widest text-orange-400 font-black">
                  Advisor
                </div>
                <div className="mt-1 text-label text-gray-300 leading-relaxed">
                  {patch.title ?? patch.status ?? "No patch recommendation yet"}
                </div>
                {typeof patch.estimated_lift_pp === "number" && (
                  <div className="mt-1 text-meta font-mono text-emerald-400">
                    expected lift +{patch.estimated_lift_pp.toFixed(2)}pp
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        <section
          data-testid="programbench-tool-drilldown"
          className="mt-3 rounded-lg border border-white/10 bg-white/[0.03] p-2.5"
        >
          <div className="flex items-center justify-between gap-2">
            <div className="text-eyebrow uppercase tracking-widest text-orange-400 font-black">
              Archived Eval Runs
            </div>
            <div
              data-testid="programbench-lock-count"
              className="text-meta font-mono text-gray-500"
            >
              {shownTools.length < lockedCount
                ? `showing ${shownTools.length} of ${lockedCount}`
                : `${lockedCount} archived`}
            </div>
          </div>
          <div className="mt-1.5 mb-1 rounded border border-amber-500/20 bg-amber-950/10 px-2 py-1.5 text-meta leading-relaxed text-amber-300/90">
            Scores below are real archived pass-rates for each tool&apos;s own test suite -- not a
            claim that the tool was legitimately reimplemented. A 2026-06-30 provenance audit found
            most of this archive was upstream source builds rather than model reimplementations
            (honest count: 0/200 legitimate native locks). See
            docs/architecture/NATIVE_REIMPL_LOOP.md.
          </div>
          <div className="mt-2 grid gap-1.5">
            {shownTools.length === 0 ? (
              <div
                data-testid="programbench-no-locks"
                className="text-meta text-gray-500 font-mono"
              >
                No archived locks in snapshot.
              </div>
            ) : (
              shownTools.map((tool) => (
                <div
                  key={tool.name}
                  data-testid={`programbench-tool-${tool.name}`}
                  className="grid grid-cols-4 gap-2 rounded border border-white/10 px-2 py-1 text-meta font-mono text-gray-300"
                >
                  <span data-testid="programbench-tool-name" className="truncate">
                    {tool.name}
                  </span>
                  <span data-testid="programbench-tool-score" className="text-emerald-400">
                    {pct(tool.score)}
                  </span>
                  <span data-testid="programbench-tool-tests">
                    {tool.passed ?? "?"}/{tool.runnable_total ?? "?"}
                  </span>
                  <span
                    data-testid="programbench-tool-evidence"
                    className="truncate"
                    title={tool.evidence_path}
                  >
                    {tool.evidence_path}
                  </span>
                </div>
              ))
            )}
          </div>
          <div data-testid="programbench-boundary" className="mt-2 text-meta text-gray-500">
            Live from the lock board: each row is an archived eval at passed == runnable. No
            benchmark supremacy or completion claim. No unbounded benchmark run.
          </div>
        </section>
      </div>
    </div>
  );
}
