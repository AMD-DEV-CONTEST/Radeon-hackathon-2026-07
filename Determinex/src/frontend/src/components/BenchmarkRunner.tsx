"use client";

import { useState, useEffect, useRef } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  Play,
  Square,
  BarChart3,
  ChevronDown,
  ChevronRight,
  Loader2,
  Sparkles,
  ShieldCheck,
  ArrowRight,
} from "lucide-react";
import { invokeSafe } from "@/lib/api";
import { useErrorToast } from "@/components/ErrorToast";
import { ProgramBenchCockpit } from "@/components/ProgramBenchCockpit";

interface BenchmarkResult {
  name: string;
  score: number;
  total: number;
  resolved: number;
  timestamp: string;
  status: "pass" | "fail" | "partial";
}

interface BenchmarkConfig {
  id: string;
  label: string;
  description: string;
  accentColor: string;
  scriptName: string;
  args: string[];
  defaultTotal: number;
}

const BENCHMARKS: BenchmarkConfig[] = [
  {
    id: "swebench-lite",
    label: "SWE-bench Lite",
    description: "300-instance bug-fix benchmark. Config D: Claude Architect + DeepSeek Builder.",
    accentColor: "var(--dtx-ok)",
    scriptName: "determinex_swebench_run.py",
    args: ["--config", "d", "--cloak", "--parallel", "4", "--instances", "300"],
    defaultTotal: 300,
  },
  {
    id: "swebench-verified",
    label: "SWE-bench Verified",
    description: "500-instance human-validated split. Harder than Lite.",
    accentColor: "var(--dtx-alt-2)",
    scriptName: "determinex_swebench_run.py",
    args: ["--config", "d", "--cloak", "--parallel", "4", "--split", "verified"],
    defaultTotal: 500,
  },
  {
    id: "livecode",
    label: "LiveCodeBench",
    description: "Write-from-scratch competitive programming (post-May 2023, no contamination).",
    accentColor: "var(--dtx-alt)",
    scriptName: "determinex_livecode_run.py",
    args: ["--n", "200", "--difficulty", "all", "--workers", "4"],
    defaultTotal: 200,
  },
  {
    id: "bigcode",
    label: "BigCodeBench",
    description: "1,140 function-implementation tasks. Requires Docker for execution.",
    accentColor: "var(--dtx-warn)",
    scriptName: "determinex_bigcode_run.py",
    args: ["--n", "500", "--subset", "hard", "--workers", "4"],
    // defaultTotal must match the number of tasks this run ACTUALLY attempts (`--n 500`), not the
    // size of the full benchmark. It was 1140 while `args` launched 500, and score is computed as
    // resolved / defaultTotal -- so a run that solved every task it attempted displayed as 43.9%.
    // The suite's full size stays in `description`, where it is informative rather than load-bearing.
    defaultTotal: 500,
  },
];

type RunStatus = "idle" | "running" | "done" | "error";
type ErrorKind = "launch" | "crash" | "timeout" | "unknown";

interface RunState {
  status: RunStatus;
  errorKind?: ErrorKind;
  log: string[];
  logOffset: number; // total entries ever dropped from the front (for stable keys)
  result?: BenchmarkResult;
  startTime?: number;
  elapsed: number;
}

const makeInitialRun = (): RunState => ({ status: "idle", log: [], logOffset: 0, elapsed: 0 });

function ScoreRing({ resolved, total, color }: { resolved: number; total: number; color: string }) {
  const pct = total > 0 ? resolved / total : 0;
  const radius = 28;
  const circ = 2 * Math.PI * radius;
  const dash = pct * circ;
  return (
    <div className="relative w-16 h-16 flex items-center justify-center">
      <svg className="absolute inset-0 -rotate-90" viewBox="0 0 72 72">
        <circle cx="36" cy="36" r={radius} strokeWidth="5" className="stroke-white/5" fill="none" />
        <circle
          cx="36"
          cy="36"
          r={radius}
          strokeWidth="5"
          fill="none"
          stroke={color}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
          style={{ transition: "stroke-dasharray 0.6s ease" }}
        />
      </svg>
      <span className="text-label font-black text-white leading-none">
        {total > 0 && resolved > 0 ? `${Math.round(pct * 100)}%` : "—"}
      </span>
    </div>
  );
}

function ElapsedTimer({ running, elapsed }: { running: boolean; elapsed: number }) {
  const m = Math.floor(elapsed / 60)
    .toString()
    .padStart(2, "0");
  const s = (elapsed % 60).toString().padStart(2, "0");
  return (
    <span
      className={`text-label font-mono ${running ? "text-amber-400 animate-pulse" : "text-gray-600"}`}
    >
      {m}:{s}
    </span>
  );
}

function LogPane({ lines, logOffset }: { lines: string[]; logOffset: number }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length, logOffset]);

  if (lines.length === 0) return null;
  return (
    <div className="mt-2 bg-black/60 border border-white/5 rounded-lg p-3 max-h-48 overflow-y-auto font-mono text-meta leading-relaxed">
      {lines.map((l, i) => (
        <div
          key={logOffset + i}
          className={`${l.includes("ERROR") || l.includes("FAIL") || l.includes("âœ—") ? "text-red-400" : l.includes("PASS") || l.includes("resolved") || l.includes("âœ“") || l.includes("Predictions written") ? "text-emerald-400" : l.includes("âš ") ? "text-amber-400" : "text-gray-400"}`}
        >
          {l}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

export function BenchmarkRunner() {
  const showError = useErrorToast();
  // Ryan: "programbench is fine and all, but its not the end all be all, its
  // just one bench theres a million and there will be a million more, that
  // needs to be less prominent and easier to understand for the average
  // user who could give two flying fucks about the bench, just that its
  // smart and knows what its doing. like that level of depth should be a
  // sub menu in brain." -- ProgramBench/SWE-bench/LiveCode/BigCode detail
  // (raw scores, per-tool locked-tool rows, live run controls) now lives
  // behind an explicit "Benchmarks" tab; the default view is a plain-
  // language summary with no benchmark jargon.
  const [tab, setTab] = useState<"overview" | "benchmarks">("overview");
  const [runs, setRuns] = useState<Record<string, RunState>>(() =>
    Object.fromEntries(BENCHMARKS.map((b) => [b.id, makeInitialRun()]))
  );
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [history, setHistory] = useState<Record<string, BenchmarkResult[]>>({});

  // Per-benchmark: incrementing generation counter. When stopBenchmark fires, the
  // generation advances. The in-flight listener checks its captured generation against
  // the current one before writing results — if they differ, it's a stale response.
  const generations = useRef<Record<string, number>>(
    Object.fromEntries(BENCHMARKS.map((b) => [b.id, 0]))
  );
  const timers = useRef<Record<string, ReturnType<typeof setInterval>>>({});
  // Per-benchmark event unsubscribe functions for cleanup on stop or unmount.
  const unlisteners = useRef<Record<string, () => void>>({});

  // Clear timers and listeners on unmount.
  useEffect(() => {
    const t = timers.current;
    const u = unlisteners.current;
    return () => {
      Object.values(t).forEach((id) => clearInterval(id));
      Object.values(u).forEach((fn) => fn());
    };
  }, []);

  const setRun = (
    id: string,
    patch: Partial<RunState> | ((prev: RunState) => Partial<RunState>)
  ) => {
    setRuns((prev) => {
      const cur = prev[id];
      const delta = typeof patch === "function" ? patch(cur) : patch;
      return { ...prev, [id]: { ...cur, ...delta } };
    });
  };

  const appendLog = (id: string, line: string) => {
    setRun(id, (prev) => {
      const trimmed = prev.log.slice(-200);
      const dropped = prev.log.length - trimmed.length;
      return { log: [...trimmed, line], logOffset: prev.logOffset + dropped };
    });
  };

  const startBenchmark = async (cfg: BenchmarkConfig) => {
    const id = cfg.id;
    if (runs[id].status === "running") return;

    // Advance generation so any prior in-flight listener discards its result.
    generations.current[id] = (generations.current[id] ?? 0) + 1;
    const myGen = generations.current[id];

    // Clean up any previous listener for this benchmark.
    unlisteners.current[id]?.();
    delete unlisteners.current[id];

    clearInterval(timers.current[id]);
    const startTime = Date.now();
    setRun(id, { status: "running", log: [], result: undefined, startTime, elapsed: 0 });

    timers.current[id] = setInterval(() => {
      setRun(id, (prev) => ({
        elapsed: Math.floor((Date.now() - (prev.startTime ?? Date.now())) / 1000),
      }));
    }, 1000);

    appendLog(id, `[${new Date().toLocaleTimeString()}] Starting ${cfg.label}...`);
    appendLog(id, `> python scripts/${cfg.scriptName} ${cfg.args.join(" ")}`);

    try {
      const launched = await invokeSafe<{
        ok: boolean;
        data?: { run_key: string; pid: number; event: string; log_path: string };
        error?: string;
      }>("launch_benchmark_run", {
        // Tauri looks params up as camelCase (ArgumentCase::Camel default), so
        // snake_case keys arrive missing and these required String params make
        // the command reject outright -- launch/stop never worked.
        benchmarkId: id,
        scriptName: cfg.scriptName,
        args: cfg.args,
      });

      // Stale guard — stop may have fired while invokeSafe was in flight.
      if (generations.current[id] !== myGen) return;

      if (!launched || !launched.ok || !launched.data) {
        clearInterval(timers.current[id]);
        setRun(id, { status: "error", errorKind: "launch" });
        const msg = launched?.error ?? "launch_benchmark_run returned no data";
        appendLog(id, `âœ— Launch failed: ${msg}`);
        appendLog(id, `  Verify script exists: scripts/${cfg.scriptName}`);
        appendLog(id, `  Run directly: python scripts/${cfg.scriptName} ${cfg.args.join(" ")}`);
        return;
      }

      const { event: eventName } = launched.data;
      appendLog(id, `âœ“ Launched (event: ${eventName})`);

      // Subscribe to log events from the benchmark process.
      const unlisten = await listen<{
        line: string | null;
        complete?: boolean;
        resolved?: number;
        predictions_path?: string;
      }>(eventName, (evt) => {
        // Stale generation check — user may have stopped since we subscribed.
        if (generations.current[id] !== myGen) return;

        const { line, complete, resolved } = evt.payload;

        if (line !== null && line !== undefined) {
          appendLog(id, line);
        }

        if (complete) {
          clearInterval(timers.current[id]);
          unlisten();
          delete unlisteners.current[id];

          const total = cfg.defaultTotal;
          const resolvedCount = resolved ?? 0;
          const score = total > 0 ? Math.round((resolvedCount / total) * 1000) / 10 : 0;

          const benchResult: BenchmarkResult = {
            name: cfg.label,
            score,
            total,
            resolved: resolvedCount,
            timestamp: new Date().toISOString(),
            status: score >= 30 ? "pass" : score >= 10 ? "partial" : "fail",
          };

          setRun(id, { status: "done", result: benchResult });
          setHistory((prev) => ({
            ...prev,
            [id]: [benchResult, ...(prev[id] ?? [])].slice(0, 10),
          }));

          if (resolvedCount > 0) {
            appendLog(id, `✓ Generation done — ${resolvedCount}/${total} predictions written`);
          } else {
            appendLog(id, `âœ“ Generation complete (Docker eval pending for score)`);
          }
        }
      });

      unlisteners.current[id] = unlisten;
    } catch (err: unknown) {
      if (generations.current[id] !== myGen) return;
      clearInterval(timers.current[id]);
      const msg = err instanceof Error ? err.message : String(err);
      const isTimeout =
        msg.toLowerCase().includes("timeout") || msg.toLowerCase().includes("timed out");
      setRun(id, { status: "error", errorKind: isTimeout ? "timeout" : "crash" });
      appendLog(id, `âœ— ${isTimeout ? "Timed out" : "Process crashed"}: ${msg}`);
      appendLog(id, `  Run directly: python scripts/${cfg.scriptName} ${cfg.args.join(" ")}`);
    }
  };

  const stopBenchmark = async (id: string) => {
    // Advance generation so the active listener discards any future events.
    generations.current[id] = (generations.current[id] ?? 0) + 1;
    clearInterval(timers.current[id]);
    // Clean up listener.
    unlisteners.current[id]?.();
    delete unlisteners.current[id];
    // Tell Rust to kill the OS process, and report what actually happened.
    //
    // This used to be a fire-and-forget `invokeSafe(...).catch(...)` followed immediately by
    // setRun(idle) and the "Stopped" log below. Two problems: `invokeSafe` never rejects by
    // contract (it resolves to null on failure), so the `.catch` and its showError were dead code;
    // and the state flip plus the log ran synchronously BEFORE the promise settled, so the row went
    // idle and the log asserted the process had stopped regardless of whether Rust killed anything.
    const stopConfirmed = await invokeSafe("stop_benchmark_run", { benchmarkId: id });
    if (stopConfirmed === null) {
      showError(
        "Stop was requested but not confirmed — the benchmark process may still be running."
      );
    }
    setRun(id, { status: "idle" });
    appendLog(id, "âš  Stopped");
  };

  const toggleExpand = (id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)]/60 flex-shrink-0">
        <div className="flex items-center gap-2 mb-1">
          <Sparkles size={14} className="text-orange-400" />
          <span className="text-meta font-black uppercase tracking-widest text-orange-400">
            Brain
          </span>
        </div>
        <p className="text-meta text-gray-500 font-mono leading-relaxed">
          Which models play each role, and how well the system does on real, compiler-verified work.
        </p>
        <div className="mt-3 flex gap-1 rounded-lg border border-white/8 p-0.5 w-fit">
          <button
            onClick={() => setTab("overview")}
            className={`rounded-md px-2.5 py-1 text-eyebrow font-bold uppercase tracking-wide transition-colors ${
              tab === "overview" ? "bg-white/10 text-white" : "text-gray-600 hover:text-gray-400"
            }`}
          >
            Overview
          </button>
          <button
            onClick={() => setTab("benchmarks")}
            className={`rounded-md px-2.5 py-1 text-eyebrow font-bold uppercase tracking-wide transition-colors ${
              tab === "benchmarks" ? "bg-white/10 text-white" : "text-gray-600 hover:text-gray-400"
            }`}
          >
            Benchmarks
          </button>
        </div>
      </div>

      {tab === "overview" && (
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
            <div className="flex items-center gap-2 mb-2">
              <ShieldCheck size={13} className="text-emerald-400" />
              <span className="text-label font-bold text-white">How this stays honest</span>
            </div>
            <p className="text-label text-gray-400 leading-relaxed">
              Brain assigns which AI model plays each role -- Oracle, Architect, and Builder --
              shown in the Role Slots panel. Nothing an agent produces is trusted on its own word:
              every answer is checked by a real compiler or test run before it counts as correct.
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
            <div className="text-eyebrow uppercase tracking-widest text-gray-500 font-bold mb-2">
              Why you don&apos;t see raw scores here
            </div>
            <p className="text-label text-gray-400 leading-relaxed">
              This system is measured against several independent public benchmarks (SWE-bench,
              LiveCodeBench, BigCodeBench, ProgramBench, and more over time) -- no single one of
              them is the whole story, and chasing one number is a distraction from actually being
              useful. The detailed, per-benchmark numbers are one tab away for anyone who wants
              them.
            </p>
          </div>
          <button
            onClick={() => setTab("benchmarks")}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-white/8 px-3 py-2 text-eyebrow font-black uppercase tracking-widest text-gray-400 hover:bg-white/5 hover:text-gray-200 transition-colors"
          >
            View detailed benchmark scores <ArrowRight size={11} />
          </button>
        </div>
      )}

      {tab === "benchmarks" && (
        <>
          <ProgramBenchCockpit />

          {/* Benchmark cards */}
          <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
            {BENCHMARKS.map((cfg) => {
              const run = runs[cfg.id];
              const isExpanded = expanded[cfg.id] ?? false;
              const hist = history[cfg.id] ?? [];
              const isRunning = run.status === "running";

              return (
                <div
                  key={cfg.id}
                  className="bg-[var(--dtx-code-panel)] border border-[var(--dtx-code-border)] rounded-xl overflow-hidden transition-all"
                  style={{ borderColor: isRunning ? cfg.accentColor + "40" : undefined }}
                >
                  {/* Card header */}
                  <div className="p-3 flex items-center gap-3">
                    <ScoreRing
                      resolved={run.result?.resolved ?? 0}
                      total={run.result?.total ?? cfg.defaultTotal}
                      color={cfg.accentColor}
                    />

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-label font-bold text-white truncate">
                          {cfg.label}
                        </span>
                        {run.status === "done" && run.result && (
                          <span
                            className={`text-meta font-mono px-1.5 py-0.5 rounded-full ${
                              run.result.status === "pass"
                                ? "bg-emerald-500/20 text-emerald-400"
                                : run.result.status === "partial"
                                  ? "bg-amber-500/20 text-amber-400"
                                  : "bg-red-500/20 text-red-400"
                            }`}
                          >
                            {run.result.resolved}/{run.result.total}
                          </span>
                        )}
                        {isRunning && <Loader2 size={10} className="text-amber-400 animate-spin" />}
                      </div>
                      <p className="text-meta text-gray-500 leading-relaxed truncate">
                        {cfg.description}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <ElapsedTimer running={isRunning} elapsed={run.elapsed} />
                        {run.status === "error" && (
                          <span className="text-meta text-red-400">
                            {run.errorKind === "launch"
                              ? "launch failed"
                              : run.errorKind === "timeout"
                                ? "timed out"
                                : run.errorKind === "crash"
                                  ? "process crashed"
                                  : "error"}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <button
                        onClick={() => toggleExpand(cfg.id)}
                        className="p-1 text-gray-600 hover:text-gray-300 transition-colors rounded"
                        title="Toggle log"
                      >
                        {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      </button>
                      {isRunning ? (
                        <button
                          onClick={() => stopBenchmark(cfg.id)}
                          className="p-1.5 rounded-lg bg-red-900/30 border border-red-500/30 text-red-400 hover:bg-red-900/60 transition-colors"
                          title="Stop"
                        >
                          <Square size={12} />
                        </button>
                      ) : (
                        <button
                          onClick={() => startBenchmark(cfg)}
                          className="p-1.5 rounded-lg border transition-colors"
                          style={{
                            backgroundColor: cfg.accentColor + "20",
                            borderColor: cfg.accentColor + "40",
                            color: cfg.accentColor,
                          }}
                          title="Run benchmark"
                        >
                          <Play size={12} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Expanded: log + history */}
                  {isExpanded && (
                    <div className="px-3 pb-3 border-t border-[var(--dtx-code-border)]/50">
                      <LogPane lines={run.log} logOffset={run.logOffset} />

                      {hist.length > 0 && (
                        <div className="mt-3">
                          <div className="text-eyebrow uppercase font-bold text-gray-600 tracking-widest mb-1.5">
                            History
                          </div>
                          <div className="flex flex-col gap-1">
                            {hist.map((h, i) => (
                              <div
                                key={i}
                                className="flex items-center justify-between text-meta font-mono text-gray-500"
                              >
                                <span>{new Date(h.timestamp).toLocaleString()}</span>
                                <span
                                  className={`${h.status === "pass" ? "text-emerald-400" : h.status === "partial" ? "text-amber-400" : "text-red-400"}`}
                                >
                                  {h.resolved}/{h.total} ({h.score}%)
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Score delta framework */}
            <div className="mt-2 p-3 bg-[var(--dtx-code-bg)] border border-[var(--dtx-code-border)]/50 rounded-xl">
              <div className="text-eyebrow uppercase font-bold text-gray-600 tracking-widest mb-2">
                Score Delta Framework
              </div>
              <div className="flex flex-col gap-1.5 font-mono text-meta">
                <div className="flex justify-between">
                  <span className="text-gray-500">B-Uncloaked (DeepSeek baseline)</span>
                  <span className="text-gray-400">X%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">B-Cloaked (privacy cost)</span>
                  <span className="text-amber-400">Y% · Y−X = privacy tax</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">D-Cloaked (Claude Architect)</span>
                  <span className="text-emerald-400">Z% · Z−Y = Architect lift</span>
                </div>
                <div className="mt-1 pt-1.5 border-t border-[var(--dtx-code-border)]/50 text-gray-600 leading-relaxed">
                  D-Cloaked broken baseline:{" "}
                  <span className="text-emerald-400">35/300 = 11.7%</span>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
