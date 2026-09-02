/**
 * HiveBuildLoop.tsx — Hive Mind Build Progress Display
 *
 * Shows real-time build progress once a session is running:
 *   - Phase indicator (DAG generation → build execution)
 *   - Per-step status with compiler verdict
 *   - Running API cost counter vs budget cap
 *   - Log stream panel
 *   - Launch build loop button after DAG is ready
 */

"use client";

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  invokeSafe,
  invokeWrite,
  exploreWorkspace,
  diagnoseWorkspace,
  probeHardware,
  recommendedAmplifyK,
} from "@/lib/api";
import {
  CheckCircle2,
  XCircle,
  Clock,
  Zap,
  ChevronDown,
  ChevronRight,
  RotateCcw,
  Play,
  Blocks,
  Terminal,
  DollarSign,
  AlertTriangle,
  Layers,
  FileCode2,
  RefreshCw,
  Stethoscope,
  PlusCircle,
  FolderOpen,
} from "lucide-react";
import {
  getHiveSessionStatus,
  runHiveSession,
  killHiveSession,
  streamHiveSessionLog,
  readHiveWorkspaceFile,
} from "@/lib/api";
import { GlossaryTerm } from "@/components/GlossaryTerm";

// ─────────────────────────────────────────────────────────────────────────────
// COMPILER ERROR TRANSLATION
// ─────────────────────────────────────────────────────────────────────────────

/** Pattern table: maps compiler error fragments → plain-English explanations. */
const ERROR_TRANSLATIONS: { pattern: RegExp; message: string }[] = [
  // Rust
  {
    pattern: /E0308.*mismatched types/i,
    message:
      "The model used the wrong type for a default value — this is a known pattern the system will fix on retry.",
  },
  {
    pattern: /E0382.*use of moved value/i,
    message:
      "A variable was used after its ownership was transferred — the retry will correct the borrow pattern.",
  },
  {
    pattern: /E0502.*cannot borrow.*mutable/i,
    message:
      "The model tried to borrow a variable mutably while it was already borrowed — a common retry-fixable issue.",
  },
  {
    pattern: /E0499.*cannot borrow.*already borrowed/i,
    message:
      "Two mutable borrows of the same value conflict — the retry will restructure the order.",
  },
  {
    pattern: /E0507.*cannot move out of.*behind a shared reference/i,
    message:
      "A value was moved from behind a shared reference — the retry will clone or restructure.",
  },
  {
    pattern: /E0515.*cannot return.*reference.*local/i,
    message:
      "The model returned a reference to a local variable — the retry will return an owned value instead.",
  },
  {
    pattern: /E0412.*cannot find type/i,
    message:
      "An unknown type was referenced — the retry will use the correct type from the project's imports.",
  },
  {
    pattern: /E0425.*cannot find (value|function)/i,
    message:
      "An undefined function or value was called — the retry will use the correct name from the file.",
  },
  {
    pattern: /E0433.*failed to resolve/i,
    message: "A missing import path — the retry will add the correct `use` statement.",
  },
  {
    pattern: /E0277.*the trait.*is not implemented/i,
    message:
      "A trait bound was not satisfied — the retry will implement or derive the required trait.",
  },
  // Python
  {
    pattern: /IndentationError/i,
    message: "Indentation was incorrect — the retry will align the code blocks properly.",
  },
  {
    pattern: /SyntaxError.*invalid syntax/i,
    message: "A syntax error was generated — the retry will produce valid Python.",
  },
  {
    pattern: /ModuleNotFoundError/i,
    message:
      "An import was missing — the retry will reference only modules available in the project.",
  },
  {
    pattern: /AttributeError/i,
    message:
      "An attribute or method that doesn't exist was accessed — the retry will use the correct attribute name.",
  },
  // Go
  {
    pattern: /undefined: /i,
    message:
      "An undefined symbol was referenced — the retry will use the correct identifier from the package.",
  },
  {
    pattern: /cannot use .* as type/i,
    message: "The wrong type was passed to a function — the retry will use the correct type.",
  },
  {
    pattern: /declared (and not used|but not used)/i,
    message:
      "A variable was declared but never used — the retry will either remove it or use it correctly.",
  },
];

/**
 * Given raw compiler output and a language tag, return a single user-friendly
 * explanation. Falls back to a generic message if no pattern matches.
 */
function translateCompilerError(output: string, lang: string): string {
  for (const { pattern, message } of ERROR_TRANSLATIONS) {
    if (pattern.test(output)) return message;
  }
  if (output.trim().length === 0) {
    return "The build loop could not be completed. Retrying will re-run the failed steps from the last known good state.";
  }
  const langLabel = lang ? `${lang} ` : "";
  return `A ${langLabel}compiler error was detected. The model will attempt a different approach on retry.`;
}

// ─────────────────────────────────────────────────────────────────────────────
// FAILURE BANNER
// ─────────────────────────────────────────────────────────────────────────────

interface FailureBannerProps {
  failedSteps: StepStatus[];
  sessionId: string;
  workspacePath: string;
  lang: string;
  onRetry: () => void;
  onNewBuild?: () => void;
}

function FailureBanner({
  failedSteps,
  sessionId,
  workspacePath,
  lang,
  onRetry,
  onNewBuild,
}: FailureBannerProps) {
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagResult, setDiagResult] = useState<string | null>(null);
  const [diagError, setDiagError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [exploring, setExploring] = useState(false);
  const [exploreResult, setExploreResult] = useState<string | null>(null);

  // Find the worst failed step (first failed with compiler output, or just first failed)
  const worst = failedSteps.find((s) => s.compiler_output?.trim()) ?? failedSteps[0];
  const translation = worst ? translateCompilerError(worst.compiler_output ?? "", lang) : "";

  const handleRetry = async () => {
    setRetrying(true);
    setDiagResult(null);
    setDiagError(null);
    try {
      await onRetry();
    } finally {
      // onRetry triggers the build loop, keep retrying=true until phase changes
      setTimeout(() => setRetrying(false), 3000);
    }
  };

  const handleExplore = async () => {
    if (exploring || !workspacePath) return;
    setExploring(true);
    setExploreResult(null);
    try {
      const result = await exploreWorkspace(workspacePath);
      if (result.ok && result.data) {
        const files = result.data.files ?? [];
        const summary =
          `${result.data.file_count ?? files.length} files in workspace:\n` +
          files
            .slice(0, 20)
            .map((f) => `  ${f.path}  (${(f.size_bytes / 1024).toFixed(1)} KB)`)
            .join("\n") +
          (files.length > 20 ? `\n  … and ${files.length - 20} more` : "");
        setExploreResult(summary);
      } else {
        setExploreResult(result.error ?? "No data returned.");
      }
    } catch (e) {
      setExploreResult(String(e));
    } finally {
      setExploring(false);
    }
  };

  // L10: diagnose_workspace is wired (explains errors). fix_workspace (auto-apply fixes)
  // is not yet exposed in this UI — it exists as a backend IPC command but requires
  // a confirmation step before applying diffs to avoid silent overwrites.
  // To add it: add a "Fix" button below the diagnosis result that calls
  // invokeSafe("fix_workspace", { payload: { workspace_path, issue } }) and shows a diff.
  const handleDiagnose = async () => {
    if (diagnosing || !worst) return;
    setDiagnosing(true);
    setDiagResult(null);
    setDiagError(null);
    try {
      const issue = worst.compiler_output || worst.instruction;
      const result = await diagnoseWorkspace(workspacePath, issue);
      if (result.ok && result.data) {
        const d = result.data;
        const explanation = d.explanation ?? d.raw ?? "No explanation returned.";
        const files = d.relevant_files
          ? `\n\nRelevant files:\n${d.relevant_files
              .slice(0, 5)
              .map((f) => `  • ${f}`)
              .join("\n")}`
          : "";
        setDiagResult(explanation + files);
      } else {
        setDiagError(result.error ?? "Diagnosis returned no result.");
      }
    } catch (e) {
      setDiagError(String(e));
    } finally {
      setDiagnosing(false);
    }
  };

  return (
    <div className="flex-shrink-0 border-b border-red-800/50 bg-gradient-to-b from-red-950/60 to-red-950/20">
      {/* Top bar */}
      <div className="flex items-center gap-2.5 px-3 py-2.5 border-b border-red-900/30">
        <XCircle size={14} className="text-red-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-label font-bold text-red-300 leading-tight">
            Build failed on {failedSteps.length} step{failedSteps.length !== 1 ? "s" : ""}
          </p>
          {translation && (
            <p className="text-label text-red-200/70 leading-snug mt-0.5">{translation}</p>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          id="hive-failure-retry-btn"
          onClick={handleRetry}
          disabled={retrying}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-900/40 border border-emerald-600/50 hover:bg-emerald-900/70 text-emerald-300 rounded-lg text-label font-bold transition-colors disabled:opacity-50"
        >
          {retrying ? (
            <div className="w-3 h-3 border border-emerald-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <RefreshCw size={10} />
          )}
          Retry
        </button>

        <button
          id="hive-failure-diagnose-btn"
          onClick={handleDiagnose}
          disabled={diagnosing}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-900/30 border border-cyan-700/40 hover:bg-cyan-900/60 text-cyan-300 rounded-lg text-label font-bold transition-colors disabled:opacity-50"
        >
          {diagnosing ? (
            <div className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Stethoscope size={10} />
          )}
          {diagnosing ? "Diagnosing..." : "Diagnose"}
        </button>

        <button
          id="hive-failure-explore-btn"
          onClick={handleExplore}
          disabled={exploring}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-900/30 border border-violet-700/40 hover:bg-violet-900/60 text-violet-300 rounded-lg text-label font-bold transition-colors disabled:opacity-50"
        >
          {exploring ? (
            <div className="w-3 h-3 border border-violet-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <FolderOpen size={10} />
          )}
          {exploring ? "Loading…" : "Explore"}
        </button>

        {onNewBuild && (
          <button
            id="hive-failure-newbuild-btn"
            onClick={onNewBuild}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--dtx-code-panel)] border border-[var(--dtx-code-border)] hover:border-gray-500 text-gray-400 hover:text-gray-200 rounded-lg text-label font-bold transition-colors"
          >
            <PlusCircle size={10} />
            New Build
          </button>
        )}
      </div>

      {/* Explore result panel */}
      {exploreResult && (
        <div className="mx-3 mb-2.5 rounded-lg border border-violet-800/30 bg-violet-950/30 p-2.5">
          <p className="text-eyebrow font-bold uppercase tracking-wider mb-1 text-violet-400">
            Workspace Files
          </p>
          <pre className="text-label text-gray-300 leading-relaxed whitespace-pre-wrap font-mono">
            {exploreResult}
          </pre>
        </div>
      )}

      {/* Diagnosis result panel */}
      {(diagResult || diagError) && (
        <div
          className={`mx-3 mb-2.5 rounded-lg border p-2.5 ${
            diagError ? "bg-red-950/40 border-red-800/40" : "bg-cyan-950/30 border-cyan-800/30"
          }`}
        >
          <p
            className={`text-eyebrow font-bold uppercase tracking-wider mb-1 ${
              diagError ? "text-red-400" : "text-cyan-400"
            }`}
          >
            {diagError ? "Diagnosis failed" : "Diagnosis"}
          </p>
          <p className="text-label text-gray-300 leading-relaxed whitespace-pre-wrap font-mono">
            {diagError ?? diagResult}
          </p>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

export interface StepStatus {
  id: number;
  instruction: string;
  status: string;
  target_file: string;
  write_mode: string;
  compiler_result: string;
  compiler_output: string;
  monitor_verdict: string;
  adjudication_score: number;
  retries: number;
  quality: string;
}

interface SessionStatus {
  session_id: string;
  lang: string;
  project_root: string;
  steps: StepStatus[];
  api_cost_usd: number;
  session_budget_usd: number;
  budget_exhausted: boolean;
  scaffolding_validated: boolean;
  created_at: string;
  updated_at: string;
  // Set by Rust when run-session process dies while steps are in_progress
  process_crashed?: boolean;
  crash_tail?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP STATUS ICONS + COLORS
// ─────────────────────────────────────────────────────────────────────────────

function StepIcon({ status }: { status: string }) {
  switch (status) {
    case "complete":
      return <CheckCircle2 size={13} className="text-emerald-400 flex-shrink-0" />;
    case "failed":
      return <XCircle size={13} className="text-red-400 flex-shrink-0" />;
    case "in_progress":
      return (
        <div className="w-3.5 h-3.5 border border-cyan-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
      );
    default:
      return <Clock size={13} className="text-gray-600 flex-shrink-0" />;
  }
}

function statusColor(status: string): string {
  switch (status) {
    case "complete":
      return "border-emerald-800/40 bg-emerald-900/10";
    case "failed":
      return "border-red-800/40 bg-red-900/10";
    case "in_progress":
      return "border-cyan-700/40 bg-cyan-900/10";
    default:
      return "border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)]/40";
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP ROW
// ─────────────────────────────────────────────────────────────────────────────

// Memoized: only re-renders when status, compiler_result, or retry count changes.
// Prevents the 2.5s poll from re-rendering 40+ completed cards on every tick.
const StepRow = React.memo(
  function StepRow({ step, sessionId }: { step: StepStatus; sessionId: string }) {
    const [expanded, setExpanded] = useState(false);
    const [fileContent, setFileContent] = useState<string | null>(null);
    const [loadingFile, setLoadingFile] = useState(false);

    const loadFile = async () => {
      if (fileContent !== null || !sessionId || !step.target_file) return;
      setLoadingFile(true);
      const content = await readHiveWorkspaceFile(sessionId, step.target_file);
      setFileContent(content);
      setLoadingFile(false);
    };

    const handleToggle = () => {
      const next = !expanded;
      setExpanded(next);
      if (next && step.status === "complete") loadFile();
    };

    const passed = step.compiler_result === "PASS";
    const failed = step.status === "failed";

    return (
      <div
        className={`border rounded-lg overflow-hidden transition-colors ${statusColor(step.status)}`}
      >
        <button
          onClick={handleToggle}
          className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-white/[0.02] transition-colors"
        >
          <StepIcon status={step.status} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-label font-mono text-gray-500">#{step.id}</span>
              <span className="text-label font-mono text-gray-500">{step.target_file}</span>
              {step.compiler_result && (
                <span
                  className={`text-meta font-bold px-1 rounded ${passed ? "text-emerald-400 bg-emerald-900/30" : "text-red-400 bg-red-900/30"}`}
                >
                  {passed ? "✓" : "✗"}
                </span>
              )}
            </div>
            <p className="text-label text-gray-400 leading-snug truncate">{step.instruction}</p>
          </div>
          {step.retries > 0 && (
            <div className="flex items-center gap-0.5 text-meta text-amber-500 flex-shrink-0">
              <RotateCcw size={9} />
              {step.retries}
            </div>
          )}
          {expanded ? (
            <ChevronDown size={11} className="text-gray-600 flex-shrink-0 mt-0.5" />
          ) : (
            <ChevronRight size={11} className="text-gray-600 flex-shrink-0 mt-0.5" />
          )}
        </button>

        {expanded && (
          <div className="border-t border-[var(--dtx-code-border)]/60">
            {/* Full instruction — visible without truncation when expanded */}
            <div className="px-3 py-2 border-b border-[var(--dtx-code-border)]/40">
              <p className="text-label text-gray-300 leading-relaxed">{step.instruction}</p>
            </div>
            {/* Metadata row */}
            <div className="flex flex-wrap gap-3 text-label px-3 py-2">
              <span className="text-gray-600">
                Compiler:{" "}
                <span className={passed ? "text-emerald-400" : "text-red-400"}>
                  {step.compiler_result || "—"}
                </span>
              </span>
              <span className="text-gray-600">
                Monitor:{" "}
                <span
                  className={
                    step.monitor_verdict === "PASS" ? "text-emerald-400" : "text-amber-400"
                  }
                >
                  {step.monitor_verdict || "—"}
                </span>
              </span>
              {step.adjudication_score > 0 && (
                <span className="text-gray-600">
                  Score: <span className="text-cyan-400">{step.adjudication_score.toFixed(2)}</span>
                </span>
              )}
              {step.quality && (
                <span
                  className={`text-meta font-bold px-1 rounded ${
                    step.quality === "good"
                      ? "text-emerald-400 bg-emerald-900/20"
                      : step.quality === "ok"
                        ? "text-amber-400 bg-amber-900/20"
                        : "text-red-400 bg-red-900/20"
                  }`}
                >
                  {step.quality}
                </span>
              )}
              <span className="text-gray-600 font-mono">{step.write_mode || "—"}</span>
            </div>

            {/* Compiler error */}
            {failed && step.compiler_output && (
              <div className="mx-3 mb-2 rounded-lg bg-red-950/30 border border-red-800/40 p-2">
                <p className="text-eyebrow font-bold text-red-400 uppercase tracking-wider mb-1">
                  Compiler error
                </p>
                <pre className="text-label text-red-300 font-mono whitespace-pre-wrap leading-relaxed overflow-x-auto max-h-32">
                  {step.compiler_output.slice(0, 800)}
                </pre>
              </div>
            )}

            {/* File content preview */}
            {step.status === "complete" && (
              <div className="mx-3 mb-3">
                {loadingFile ? (
                  <div className="flex items-center gap-2 py-2">
                    <div className="w-3 h-3 border border-cyan-500 border-t-transparent rounded-full animate-spin" />
                    <span className="text-label text-gray-600">Loading file...</span>
                  </div>
                ) : fileContent !== null ? (
                  <div className="rounded-lg border border-[var(--dtx-code-border)] overflow-hidden">
                    <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[var(--dtx-code-panel)] border-b border-[var(--dtx-code-border)]">
                      <FileCode2 size={10} className="text-cyan-400" />
                      <span className="text-meta font-mono text-gray-500">{step.target_file}</span>
                      <span className="text-meta text-gray-700 ml-auto">
                        {fileContent.split("\n").length} lines
                      </span>
                    </div>
                    <pre className="text-label font-mono text-gray-300 p-2.5 overflow-x-auto max-h-64 leading-relaxed whitespace-pre bg-[var(--dtx-code-bg)]">
                      {fileContent.slice(0, 4000)}
                      {fileContent.length > 4000 ? "\n\n… (truncated)" : ""}
                    </pre>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        )}
      </div>
    );
  },
  (prev, next) =>
    prev.sessionId === next.sessionId &&
    prev.step.status === next.step.status &&
    prev.step.compiler_result === next.step.compiler_result &&
    prev.step.retries === next.step.retries
);

// ─────────────────────────────────────────────────────────────────────────────
// ACTIVE STEP CARD — shown at top during building phase
// ─────────────────────────────────────────────────────────────────────────────

const STALL_THRESHOLD_S = 45;

function formatElapsed(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function ActiveStepCard({ step, logLines }: { step: StepStatus; logLines: string[] }) {
  const startRef = useRef(Date.now());
  const lastLogCountRef = useRef(logLines.length);
  const lastActivityRef = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);
  const [sinceActivity, setSinceActivity] = useState(0);

  // Tick every second
  useEffect(() => {
    const t = setInterval(() => {
      const now = Date.now();
      setElapsed(Math.floor((now - startRef.current) / 1000));
      setSinceActivity(Math.floor((now - lastActivityRef.current) / 1000));
    }, 1000);
    return () => clearInterval(t);
  }, []);

  // Track new log lines as activity
  useEffect(() => {
    if (logLines.length > lastLogCountRef.current) {
      lastActivityRef.current = Date.now();
      lastLogCountRef.current = logLines.length;
    }
  }, [logLines]);

  const isStalled = sinceActivity >= STALL_THRESHOLD_S;
  const recentLines = [...logLines].reverse().slice(0, 8);

  const borderColor = isStalled ? "border-amber-600/50" : "border-cyan-700/40";
  const bgColor = isStalled ? "bg-amber-900/10" : "bg-cyan-900/10";
  const headerBg = isStalled
    ? "bg-amber-900/20 border-b border-amber-700/30"
    : "bg-cyan-900/20 border-b border-cyan-700/30";
  const spinColor = isStalled ? "border-amber-400" : "border-cyan-400";
  const labelColor = isStalled ? "text-amber-400" : "text-cyan-400";
  const fileColor = isStalled ? "text-amber-700" : "text-cyan-600";

  return (
    <div className={`border ${borderColor} ${bgColor} rounded-xl overflow-hidden mb-3`}>
      {/* Header row */}
      <div className={`flex items-center gap-2 px-3 py-2 ${headerBg}`}>
        <div
          className={`w-3 h-3 border-2 ${spinColor} border-t-transparent rounded-full animate-spin flex-shrink-0`}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-eyebrow font-bold uppercase tracking-widest ${labelColor}`}>
              {isStalled ? "⚠ Waiting for model..." : `Building step #${step.id}`}
            </span>
            <span className={`text-meta font-mono truncate ${fileColor}`}>{step.target_file}</span>
          </div>
        </div>

        {/* Elapsed + last-activity */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Total elapsed */}
          <div
            className={`flex items-center gap-1 text-meta font-mono ${isStalled ? "text-amber-400" : "text-cyan-600"}`}
          >
            <Clock size={8} />
            {formatElapsed(elapsed)}
          </div>
          {/* Last log activity — only shown when stalled */}
          {isStalled && (
            <div className="text-meta font-mono text-amber-500 bg-amber-900/30 border border-amber-700/40 px-1.5 py-0.5 rounded">
              no output {formatElapsed(sinceActivity)}
            </div>
          )}
          {step.retries > 0 && (
            <div className="flex items-center gap-0.5 text-meta text-amber-400">
              <RotateCcw size={9} /> {step.retries}
            </div>
          )}
        </div>
      </div>

      {/* Instruction */}
      <div className="px-3 py-2 border-b border-[var(--dtx-code-border)]/50">
        <p className="text-label text-gray-300 leading-relaxed">{step.instruction}</p>
      </div>

      {/* Live log tail */}
      {recentLines.length > 0 ? (
        <div className="px-3 py-2 font-mono flex flex-col gap-0.5">
          {recentLines.map((line, i) => (
            <div
              key={i}
              className={`text-label leading-relaxed ${
                i === 0 ? "text-gray-300" : "text-gray-600"
              } ${
                line.includes("ERROR") || line.includes("FAIL")
                  ? "!text-red-400"
                  : line.includes("PASS") || line.includes("complete")
                    ? "!text-emerald-400"
                    : line.includes("WARN")
                      ? "!text-amber-400"
                      : ""
              }`}
            >
              {line}
            </div>
          ))}
        </div>
      ) : (
        <div className="px-3 py-2">
          <p className="text-label text-gray-700 font-mono">Waiting for model output...</p>
        </div>
      )}

      {/* Stall warning bar */}
      {isStalled && (
        <div className="px-3 py-2 border-t border-amber-800/30 bg-amber-950/20 flex items-center gap-2">
          <AlertTriangle size={10} className="text-amber-500 flex-shrink-0" />
          <p className="text-meta text-amber-400 font-mono">
            Model is slow — still waiting. Check the Log tab for errors or kill the session if
            stuck.
          </p>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// COST METER
// ─────────────────────────────────────────────────────────────────────────────

function CostMeter({
  cost,
  budget,
  exhausted,
}: {
  cost: number;
  budget: number;
  exhausted: boolean;
}) {
  const pct = budget > 0 ? Math.min((cost / budget) * 100, 100) : 0;
  const color = exhausted ? "bg-red-500" : pct > 80 ? "bg-amber-500" : "bg-emerald-500";

  return (
    <div className="flex items-center gap-2">
      <DollarSign size={11} className={exhausted ? "text-red-400" : "text-emerald-400"} />
      <div className="flex-1 bg-[var(--dtx-code-panel)] rounded-full h-1.5 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-label font-mono text-gray-400 flex-shrink-0">
        ${cost.toFixed(3)} / ${budget.toFixed(2)}
      </span>
      {exhausted && <AlertTriangle size={11} className="text-red-400 flex-shrink-0" />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CORRECTNESS AMPLIFIER — CANDIDATE RACE STRIP
//
// Parses the real per-candidate heartbeat lines VerifiedSearch.solve() already
// prints (determinex_verified_search.py: "[vs] r{r} s{i}/{k} t={temp} gen {s}s
// verify {s}s -> PASS|N fail (score X)") out of the same hive-log stream the
// build log already renders. No separate event/backend change needed for the
// display itself -- only the opt-in DETERMINEX_AMPLIFY/_K env vars (wired via
// run_session) needed adding for this data to exist in the log at all.
// ─────────────────────────────────────────────────────────────────────────────

type CandidateStatus = "running" | "pass" | "fail" | "duplicate";

interface CandidateEntry {
  round: number;
  index: number;
  k: number;
  temp: number;
  status: CandidateStatus;
  detail: string;
}

const CANDIDATE_LINE_RE = /\[vs\]\s+r(\d+)\s+s(\d+)\/(\d+)\s+t=([\d.]+).*?->\s*(.+?)\s*$/;
const CANDIDATE_LETTERS = "ABCDEFGHIJKLMNOP";

function parseCandidateLines(lines: string[]): CandidateEntry[] {
  const parsed: CandidateEntry[] = [];
  for (const line of lines) {
    const m = CANDIDATE_LINE_RE.exec(line);
    if (!m) continue;
    const [, r, i, k, t, outcome] = m;
    const status: CandidateStatus = outcome.startsWith("PASS")
      ? "pass"
      : outcome.startsWith("duplicate")
        ? "duplicate"
        : "fail";
    parsed.push({
      round: Number(r),
      index: Number(i),
      k: Number(k),
      temp: Number(t),
      status,
      detail: outcome,
    });
  }
  if (parsed.length === 0) return [];
  const latestRound = parsed[parsed.length - 1].round;
  const currentK = parsed[parsed.length - 1].k;
  const byIndex = new Map<number, CandidateEntry>();
  for (const entry of parsed) {
    if (entry.round === latestRound) byIndex.set(entry.index, entry);
  }
  return Array.from({ length: currentK }, (_, idx) => {
    const found = byIndex.get(idx + 1);
    return (
      found ?? {
        round: latestRound,
        index: idx + 1,
        k: currentK,
        temp: 0,
        status: "running" as const,
        detail: "sampling…",
      }
    );
  });
}

function CandidateRaceStrip({ lines }: { lines: string[] }) {
  const candidates = useMemo(() => parseCandidateLines(lines), [lines]);
  if (candidates.length === 0) return null;
  const winner = candidates.find((c) => c.status === "pass");
  return (
    <div className="flex-shrink-0 border-b border-[var(--dtx-code-border)] bg-black/30 px-3 py-2">
      <div className="mb-1.5 flex items-center gap-1.5 text-eyebrow font-bold uppercase tracking-widest text-violet-400">
        <Layers size={11} />
        Correctness Amplifier — round {candidates[0].round}, {candidates.length} parallel candidate
        {candidates.length === 1 ? "" : "s"}
        {winner && (
          <span className="ml-auto text-emerald-400">
            winner: candidate {CANDIDATE_LETTERS[winner.index - 1] ?? winner.index}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {candidates.map((c) => (
          <div
            key={c.index}
            title={c.detail}
            className={`flex items-center gap-1 rounded-md border px-2 py-1 text-meta font-mono transition-colors ${
              c.status === "pass"
                ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
                : c.status === "fail"
                  ? "border-red-500/30 bg-red-500/10 text-red-400"
                  : c.status === "duplicate"
                    ? "border-gray-600/30 bg-gray-800/20 text-gray-600"
                    : "border-amber-500/30 bg-amber-500/10 text-amber-300 animate-pulse"
            }`}
          >
            <span className="font-black">{CANDIDATE_LETTERS[c.index - 1] ?? c.index}</span>
            <span>t={c.temp.toFixed(1)}</span>
            {c.status === "pass" && <CheckCircle2 size={10} />}
            {c.status === "fail" && <XCircle size={10} />}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LOG PANEL
// ─────────────────────────────────────────────────────────────────────────────

const LOG_DISPLAY_CAP = 200;

function LogPanel({ lines }: { lines: string[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  const displayLines = lines.length > LOG_DISPLAY_CAP ? lines.slice(-LOG_DISPLAY_CAP) : lines;
  const dropped = lines.length - displayLines.length;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-1.5 border-b border-[var(--dtx-code-border)] flex-shrink-0 flex items-center gap-1.5">
        <Terminal size={11} className="text-gray-500" />
        <span className="text-meta uppercase font-bold tracking-wider text-gray-500">
          Build Log
        </span>
        {lines.length > 0 && (
          <span className="ml-auto text-meta font-mono text-gray-700">{lines.length} lines</span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-2 font-mono">
        {lines.length === 0 ? (
          <p className="text-label text-gray-600 p-1">Waiting for output...</p>
        ) : (
          <>
            {dropped > 0 && (
              <div className="text-meta text-gray-700 font-mono px-1 py-1 mb-1 border-b border-[var(--dtx-code-border)]/40">
                … {dropped} older lines (showing last {LOG_DISPLAY_CAP})
              </div>
            )}
            {displayLines.map((line, i) => (
              <div
                key={i}
                className={`text-label leading-relaxed whitespace-pre-wrap ${
                  line.includes("ERROR") || line.includes("FAIL")
                    ? "text-red-400"
                    : line.includes("PASS") || line.includes("complete")
                      ? "text-emerald-400"
                      : line.includes("WARN")
                        ? "text-amber-400"
                        : "text-gray-400"
                }`}
              >
                {line}
              </div>
            ))}
          </>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FILES PANEL
// ─────────────────────────────────────────────────────────────────────────────

function FilesPanel({ steps, sessionId }: { steps: StepStatus[]; sessionId: string }) {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContents, setFileContents] = useState<Record<string, string | null>>({});
  const [loadingFile, setLoadingFile] = useState<string | null>(null);

  const files = useMemo(() => {
    // For each unique file, keep the most urgent step (in_progress beats failed beats pending beats complete).
    // Then sort the list by the same urgency so active files float to the top during a build.
    const urgency: Record<string, number> = { in_progress: 0, failed: 1, pending: 2, complete: 3 };
    const byFile = new Map<string, StepStatus>();
    for (const s of steps) {
      if (!s.target_file) continue;
      const existing = byFile.get(s.target_file);
      if (!existing || (urgency[s.status] ?? 4) < (urgency[existing.status] ?? 4)) {
        byFile.set(s.target_file, s);
      }
    }
    return [...byFile.values()].sort((a, b) => (urgency[a.status] ?? 4) - (urgency[b.status] ?? 4));
  }, [steps]);

  const loadFile = async (path: string) => {
    if (fileContents[path] !== undefined) return;
    setLoadingFile(path);
    const content = await readHiveWorkspaceFile(sessionId, path);
    setFileContents((prev) => ({ ...prev, [path]: content }));
    setLoadingFile(null);
  };

  const toggleFile = async (path: string) => {
    if (selectedFile === path) {
      setSelectedFile(null);
      return;
    }
    setSelectedFile(path);
    await loadFile(path);
  };

  const refreshFile = async (path: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setFileContents((prev) => {
      const n = { ...prev };
      delete n[path];
      return n;
    });
    setLoadingFile(path);
    const content = await readHiveWorkspaceFile(sessionId, path);
    setFileContents((prev) => ({ ...prev, [path]: content }));
    setLoadingFile(null);
  };

  if (files.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-gray-600">
        <FileCode2 size={22} className="opacity-25" />
        <p className="text-label font-mono">No files yet — build hasn&apos;t started</p>
      </div>
    );
  }

  const builtCount = files.filter((s) => s.status === "complete").length;

  return (
    <div className="h-full flex flex-col">
      <div className="flex-shrink-0 border-b border-[var(--dtx-code-border)] px-3 py-1.5 flex items-center gap-2 bg-[var(--dtx-code-bg)]">
        <FileCode2 size={10} className="text-gray-600" />
        <span className="text-eyebrow uppercase font-bold tracking-wider text-gray-600">
          {builtCount}/{files.length} files built
        </span>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
        {files.map((step) => {
          const isOpen = selectedFile === step.target_file;
          const content = fileContents[step.target_file];
          const isLoading = loadingFile === step.target_file;
          const ext = step.target_file.split(".").pop() ?? "";

          return (
            <div
              key={step.target_file}
              className="rounded-lg border border-[var(--dtx-code-border)] overflow-hidden"
            >
              <button
                onClick={() => toggleFile(step.target_file)}
                className="w-full flex items-center gap-2 px-3 py-2.5 hover:bg-[var(--dtx-code-panel)] transition-colors text-left"
              >
                <FileCode2
                  size={11}
                  className={
                    step.status === "complete"
                      ? "text-emerald-400 flex-shrink-0"
                      : step.status === "failed"
                        ? "text-red-400 flex-shrink-0"
                        : step.status === "in_progress"
                          ? "text-cyan-400 flex-shrink-0"
                          : "text-gray-600 flex-shrink-0"
                  }
                />
                <span className="flex-1 text-label font-mono text-gray-300 truncate min-w-0">
                  {step.target_file}
                </span>
                <span
                  className={`text-eyebrow uppercase font-bold px-1.5 py-0.5 rounded flex-shrink-0 ${
                    step.status === "complete"
                      ? "bg-emerald-950/60 text-emerald-400 border border-emerald-800/40"
                      : step.status === "failed"
                        ? "bg-red-950/60 text-red-400 border border-red-800/40"
                        : step.status === "in_progress"
                          ? "bg-cyan-950/60 text-cyan-400 border border-cyan-800/40 animate-pulse"
                          : "bg-[var(--dtx-code-panel)] text-gray-600 border border-[var(--dtx-code-border)]"
                  }`}
                >
                  {step.status}
                </span>
                <ChevronDown
                  size={10}
                  className={`text-gray-600 flex-shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
                />
              </button>

              {isOpen && (
                <div className="border-t border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)]">
                  <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--dtx-code-border)]/50">
                    <span className="text-meta font-mono text-gray-600">
                      {ext} · {step.write_mode}
                    </span>
                    <button
                      onClick={(e) => refreshFile(step.target_file, e)}
                      className="text-meta text-gray-600 hover:text-gray-400 flex items-center gap-1 transition-colors"
                    >
                      <RefreshCw size={9} className={isLoading ? "animate-spin" : ""} />
                      {isLoading ? "Loading…" : "Refresh"}
                    </button>
                  </div>
                  {isLoading ? (
                    <div className="p-3 text-label text-gray-600 font-mono">Reading file…</div>
                  ) : content !== null && content !== undefined ? (
                    <pre className="p-3 text-label font-mono text-gray-300 leading-relaxed overflow-x-auto max-h-80 whitespace-pre">
                      {content}
                    </pre>
                  ) : (
                    <p className="p-3 text-label text-gray-600 font-mono">
                      {step.status === "complete" || step.status === "failed"
                        ? "File not readable — it may have been cleaned up"
                        : "File will appear here once this step completes"}
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// PHASE HEADER
// ─────────────────────────────────────────────────────────────────────────────

function PhaseHeader({
  phase,
  stepCount,
  completeCount,
  failedCount,
}: {
  phase: "dag" | "building" | "done" | "failed";
  stepCount: number;
  completeCount: number;
  failedCount: number;
}) {
  const [elapsed, setElapsed] = useState(0);
  const isActive = phase === "dag" || phase === "building";

  useEffect(() => {
    // When transitioning to active: reset and start ticking.
    // When transitioning to done/failed: stop but keep the final value visible.
    if (!isActive) return;
    setElapsed(0);
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [isActive]);

  // Projected remaining: only meaningful during building once ≥1 step is done.
  // avg seconds per step × steps still pending.
  const projectedRemaining: number | null = (() => {
    if (phase !== "building" || completeCount < 1 || stepCount <= completeCount) return null;
    const avgPerStep = elapsed / completeCount;
    return Math.round(avgPerStep * (stepCount - completeCount));
  })();

  const phaseLabels: Record<typeof phase, { label: string; color: string }> = {
    dag: { label: "Generating DAG...", color: "text-purple-400" },
    building: { label: "Building", color: "text-cyan-400" },
    done: { label: "Complete", color: "text-emerald-400" },
    failed: { label: "Failed", color: "text-red-400" },
  };

  const { label, color } = phaseLabels[phase];

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)]/50 flex-shrink-0">
      <Blocks size={14} className={color} />
      <div className="flex-1">
        <div className={`text-label font-bold ${color}`}>{label}</div>
        {stepCount > 0 && (
          <div className="text-label text-gray-500">
            {completeCount}/{stepCount} steps complete
            {failedCount > 0 && <span className="text-red-400 ml-2">{failedCount} failed</span>}
          </div>
        )}
      </div>
      {(isActive || elapsed > 0) && (
        <div className="flex flex-col items-end gap-0.5">
          <div className="flex items-center gap-2">
            <span
              className={`text-label font-mono font-bold tabular-nums ${isActive ? color : "text-gray-600"} opacity-70`}
            >
              {formatElapsed(elapsed)}
            </span>
            {isActive && (
              <div className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin opacity-60" />
            )}
          </div>
          {projectedRemaining !== null ? (
            <span className="text-meta font-mono text-gray-600 tabular-nums">
              ~{formatElapsed(projectedRemaining)} left
            </span>
          ) : phase === "building" && completeCount === 0 && stepCount > 0 ? (
            <span className="text-meta font-mono text-gray-700 tabular-nums">estimating…</span>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

interface HiveBuildLoopProps {
  sessionId: string;
  projectName?: string;
  onBack?: () => void;
  /** Set to true when the session was started via start_session (auto-run).
   *  Suppresses the manual "Start Build" button and sets running=true immediately. */
  autoRun?: boolean;
  /** Set to true when resuming a failed session — auto-fires retry once on first
   *  failed phase detection. Used by the Project Library resume flow. */
  autoRetry?: boolean;
  /** Fires exactly once per session when the compiler-oracle-verified build reaches a
   *  terminal state ("done" = every step compiled/passed, "failed" = at least one step
   *  failed with nothing left in_progress). Never fires for the intermediate "dag"/"building"
   *  phases -- this is the ONLY hook that lets a caller (e.g. the Proof rail) learn a REAL,
   *  stable verdict from this component; firing on an intermediate phase would risk reporting
   *  a false-positive/negative before the build has actually settled. */
  onComplete?: (result: HiveBuildCompletionResult) => void;
}

export interface HiveBuildCompletionResult {
  sessionId: string;
  phase: "done" | "failed";
  stepCount: number;
  completeCount: number;
  failedCount: number;
  failedSteps: StepStatus[];
}

export function HiveBuildLoop({
  sessionId,
  projectName,
  onBack,
  autoRun = false,
  autoRetry = false,
  onComplete,
}: HiveBuildLoopProps) {
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  // reveal_session_output is void-returning, so its failure was invisible under
  // invokeSafe; shown in place of "Build complete" in the success banner.
  const [revealError, setRevealError] = useState<string | null>(null);
  const [amplifyEnabled, setAmplifyEnabled] = useState(false);
  const [amplifyKOverride, setAmplifyKOverride] = useState<number | null>(null);
  const [hardwareBudgetMb, setHardwareBudgetMb] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    probeHardware().then((probe) => {
      if (!cancelled && probe) setHardwareBudgetMb(probe.vram_budget_mb);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const recommendedK = recommendedAmplifyK(hardwareBudgetMb);
  const effectiveAmplifyK = amplifyKOverride ?? recommendedK;
  // Batching buffer: accumulate log events and flush into React state every 50ms.
  // Prevents setState per-line during hot compiler loops (100+ lines/sec).
  const pendingLinesRef = useRef<string[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [activeTab, setActiveTab] = useState<"steps" | "log" | "files">("steps");
  const [running, setRunning] = useState(autoRun);
  const [runError, setRunError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [pollErrorCount, setPollErrorCount] = useState(0);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const unlistenRef = useRef<(() => void) | null>(null);
  const autoRetryFiredRef = useRef(false);
  const autoRetryTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [autoRetryCountdown, setAutoRetryCountdown] = useState<number | null>(null);
  const stepCountRef = useRef(0);

  // Poll manifest for status updates
  const pollStatus = useCallback(async () => {
    try {
      const data = (await getHiveSessionStatus(sessionId)) as unknown as SessionStatus;
      setStatus(data);
      setPollError(null);
      setPollErrorCount(0);
    } catch (e) {
      // Manifest may not exist during DAG generation; at 750ms polling that's ~22s before alert
      setPollErrorCount((prev) => {
        const next = prev + 1;
        if (next >= 30) setPollError(String(e));
        return next;
      });
    }
  }, [sessionId]);

  useEffect(() => {
    pollStatus();
    // Start at 750ms during DAG phase so steps appear promptly as Architect writes them.
    // Once any step exists, switch to 2500ms to reduce polling pressure during build.
    pollingRef.current = setInterval(async () => {
      await pollStatus();
      if (stepCountRef.current > 0 && pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = setInterval(pollStatus, 2500);
      }
    }, 750);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [pollStatus]);

  // Subscribe to log events with 50ms batching to prevent setState-per-line floods
  useEffect(() => {
    const eventName = `hive-log-${sessionId}`;
    let unlisten: (() => void) | null = null;

    const flush = () => {
      flushTimerRef.current = null;
      const batch = pendingLinesRef.current.splice(0);
      if (batch.length === 0) return;
      setLogLines((prev) => {
        const next = [...prev, ...batch];
        // Keep last 1000 in state; LogPanel displays last 200
        return next.length > 1000 ? next.slice(-1000) : next;
      });
    };

    (async () => {
      try {
        await streamHiveSessionLog(sessionId);
        unlisten = await listen<{ line: string | null; complete?: boolean }>(eventName, (event) => {
          if (event.payload.line !== null) {
            pendingLinesRef.current.push(event.payload.line as string);
            if (!flushTimerRef.current) {
              flushTimerRef.current = setTimeout(flush, 50);
            }
          } else if (event.payload.complete) {
            flush();
            setRunning(false);
          }
        });
        unlistenRef.current = unlisten;
      } catch {
        // Log streaming is best-effort
      }
    })();

    return () => {
      if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
      pendingLinesRef.current = [];
      unlistenRef.current?.();
    };
  }, [sessionId]);

  const runFiredRef = useRef(false);
  const handleRunSession = async () => {
    if (running || runFiredRef.current) return;
    runFiredRef.current = true;
    setRunning(true);
    setRunError(null);
    try {
      await runHiveSession(
        sessionId,
        amplifyEnabled,
        amplifyEnabled ? effectiveAmplifyK : undefined
      );
      setActiveTab("log");
    } catch (e) {
      setRunError(String(e));
      setRunning(false);
      runFiredRef.current = false;
    }
  };

  // Compute phase — all derived values memoized so polling doesn't cascade renders
  const steps = useMemo(() => status?.steps ?? [], [status?.steps]);
  const stepCount = steps.length;
  stepCountRef.current = stepCount;
  const completeCount = useMemo(() => steps.filter((s) => s.status === "complete").length, [steps]);
  const failedCount = useMemo(() => steps.filter((s) => s.status === "failed").length, [steps]);
  const inProgress = useMemo(() => steps.some((s) => s.status === "in_progress"), [steps]);
  const failedSteps = useMemo(() => steps.filter((s) => s.status === "failed"), [steps]);
  const activeSteps = useMemo(() => steps.filter((s) => s.status === "in_progress"), [steps]);
  const otherSteps = useMemo(() => steps.filter((s) => s.status !== "in_progress"), [steps]);
  const uniqueFileCount = useMemo(
    () => new Set(steps.map((s) => s.target_file).filter(Boolean)).size,
    [steps]
  );

  let phase: "dag" | "building" | "done" | "failed" = "dag";
  if (stepCount > 0) {
    if (failedCount > 0 && !inProgress && completeCount + failedCount === stepCount) {
      phase = "failed";
    } else if (completeCount === stepCount) {
      phase = "done";
    } else if (inProgress || running) {
      phase = "building";
    } else {
      phase = "building"; // steps exist but nothing running yet = ready to launch loop
    }
  }

  // Clear running spinner when phase resolves via polling (safety net for missed complete events)
  // Also reset runFiredRef on failure so the retry button can re-fire handleRunSession.
  useEffect(() => {
    if (phase === "done" || phase === "failed") {
      setRunning(false);
      runFiredRef.current = false;
    }
  }, [phase]);

  // Report the REAL, stable, compiler-oracle-verified verdict to the caller exactly once per
  // session per terminal transition -- never for "dag"/"building" (those aren't verdicts yet).
  // Single ref/effect (not two separate effects) so there's no ordering race between "reset for
  // new session" and "report for this session" within the same render pass.
  const completionReportRef = useRef<{ sessionId: string; reported: boolean }>({
    sessionId: "",
    reported: false,
  });
  useEffect(() => {
    if (completionReportRef.current.sessionId !== sessionId) {
      completionReportRef.current = { sessionId, reported: false };
    }
    if (phase !== "done" && phase !== "failed") return;
    if (completionReportRef.current.reported) return;
    completionReportRef.current.reported = true;
    onComplete?.({
      sessionId,
      phase,
      stepCount,
      completeCount,
      failedCount,
      failedSteps,
    });
  }, [phase, sessionId, stepCount, completeCount, failedCount, failedSteps, onComplete]);

  // Auto-retry with 3-second countdown when resuming a failed session from Project Library.
  // Delay lets the user see the failure state and cancel before the retry fires.
  useEffect(() => {
    if (!autoRetry || phase !== "failed" || autoRetryFiredRef.current || autoRetryTimerRef.current)
      return;

    let tick = 3;
    setAutoRetryCountdown(tick);
    autoRetryTimerRef.current = setInterval(() => {
      tick -= 1;
      if (tick <= 0) {
        clearInterval(autoRetryTimerRef.current!);
        autoRetryTimerRef.current = null;
        setAutoRetryCountdown(null);
        autoRetryFiredRef.current = true;
        handleRunSession();
      } else {
        setAutoRetryCountdown(tick);
      }
    }, 1000);

    return () => {
      if (autoRetryTimerRef.current) {
        clearInterval(autoRetryTimerRef.current);
        autoRetryTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRetry, phase]);

  const dagReady = stepCount > 0 && !running;
  const buildStarted = running || inProgress || completeCount > 0 || failedCount > 0;
  const isActive = phase === "dag" || phase === "building";

  const handleKillSession = async () => {
    try {
      await killHiveSession(sessionId);
      setRunning(false);
      runFiredRef.current = false;
    } catch (e) {
      console.error("kill_session failed:", e);
    }
  };

  const cancelAutoRetry = () => {
    if (autoRetryTimerRef.current) clearInterval(autoRetryTimerRef.current);
    autoRetryTimerRef.current = null;
    setAutoRetryCountdown(null);
    autoRetryFiredRef.current = true;
  };

  return (
    <div className="flex flex-col h-full">
      {/* Back nav */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--dtx-code-border)] flex-shrink-0 bg-[var(--dtx-code-bg)]/60">
        {onBack && !isActive && (
          <button
            onClick={onBack}
            className="text-label text-gray-500 hover:text-gray-300 transition-colors shrink-0 flex items-center gap-1"
          >
            ← New Build
          </button>
        )}
        {isActive && (
          <button
            onClick={handleKillSession}
            className="text-label font-bold text-red-500 hover:text-red-300 border border-red-800/50 hover:border-red-500/60 px-2.5 py-1 rounded transition-all shrink-0 flex items-center gap-1.5"
          >
            <XCircle size={10} />
            Stop
          </button>
        )}
        <div className="flex-1 min-w-0">
          {projectName ? (
            <span className="text-body font-bold text-gray-200 truncate block">{projectName}</span>
          ) : (
            <span className="text-label font-mono text-gray-600 truncate block">
              {sessionId.slice(0, 18)}…
            </span>
          )}
        </div>
      </div>

      {/* Phase header */}
      <PhaseHeader
        phase={phase}
        stepCount={stepCount}
        completeCount={completeCount}
        failedCount={failedCount}
      />

      {/* Run error — shown in retry mode where the "Start Build" button area is hidden */}
      {runError && (
        <div className="flex-shrink-0 border-b border-red-800/40 bg-red-950/20 px-3 py-1.5 flex items-center gap-2">
          <XCircle size={11} className="text-red-400 flex-shrink-0" />
          <span className="text-label text-red-300 flex-1 truncate">{runError}</span>
          <button
            onClick={() => setRunError(null)}
            className="text-gray-700 hover:text-gray-500 flex-shrink-0"
          >
            <XCircle size={9} />
          </button>
        </div>
      )}

      {/* Cost meter — only shown when API models are actually being used (cost > $0) */}
      {status && status.api_cost_usd > 0 && (
        <div className="px-3 py-2 border-b border-[var(--dtx-code-border)] flex-shrink-0">
          <CostMeter
            cost={status.api_cost_usd}
            budget={status.session_budget_usd}
            exhausted={status.budget_exhausted}
          />
        </div>
      )}

      {/* ── SUCCESS BANNER — open output folder when build completes ── */}
      {phase === "done" && (
        <div className="flex-shrink-0 border-b border-emerald-800/40 bg-emerald-950/20 px-3 py-2 flex items-center gap-2">
          <CheckCircle2 size={13} className="text-emerald-400 flex-shrink-0" />
          <span className="text-label text-emerald-300 flex-1">
            {revealError ?? "Build complete"}
          </span>
          <button
            id="reveal-session-output-btn"
            onClick={() =>
              void invokeWrite("reveal_session_output", { sessionId }).catch((e) =>
                // reveal_session_output returns Result<(), String> and Errs when
                // the session dir is missing. Under invokeSafe that rejection
                // became null and the button did nothing, visibly.
                setRevealError(`Could not open the output folder: ${e}`)
              )
            }
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-label font-bold
                       bg-emerald-600/20 border border-emerald-600/40 text-emerald-300
                       hover:bg-emerald-600/40 hover:text-emerald-100 transition-all"
          >
            <FolderOpen size={11} />
            Open Output Folder
          </button>
        </div>
      )}

      {status?.process_crashed && (
        <div className="flex-shrink-0 border-b border-red-800/60 bg-red-950/40 px-3 py-2.5">
          <div className="flex items-start gap-2 mb-1.5">
            <XCircle size={13} className="text-red-400 flex-shrink-0 mt-0.5" />
            <p className="text-label font-bold text-red-400">Build process crashed</p>
          </div>
          {status.crash_tail && (
            <pre className="text-meta font-mono text-red-300/70 leading-relaxed whitespace-pre-wrap overflow-x-auto max-h-28 bg-red-950/40 rounded p-2 border border-red-900/40">
              {status.crash_tail ?? ""}
            </pre>
          )}
          <div className="flex items-center gap-3 mt-2">
            <button
              onClick={handleRunSession}
              className="flex items-center gap-1.5 text-label text-emerald-400 hover:text-emerald-300 border border-emerald-800/50 hover:border-emerald-600/50 px-2.5 py-1 rounded transition-all"
            >
              <RefreshCw size={9} />
              Retry
            </button>
            {onBack && (
              <button
                onClick={onBack}
                className="text-label text-red-400 hover:text-red-300 underline underline-offset-2"
              >
                ← Start new build
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── AUTO-RETRY COUNTDOWN — when resuming a failed session from Project Library ── */}
      {autoRetryCountdown !== null && (
        <div className="flex-shrink-0 border-b border-amber-800/40 bg-amber-950/20 px-3 py-2 flex items-center gap-2">
          <RotateCcw size={11} className="text-amber-400 animate-spin flex-shrink-0" />
          <span className="text-label text-amber-300 flex-1">
            Auto-retrying in {autoRetryCountdown}s…
          </span>
          <button
            onClick={cancelAutoRetry}
            className="text-meta text-gray-500 hover:text-gray-300 border border-[var(--dtx-code-border)] hover:border-gray-500 px-2 py-0.5 rounded transition-colors"
          >
            Cancel
          </button>
        </div>
      )}

      {/* ── FAILURE BANNER — shown when phase resolves to "failed" ── */}
      {phase === "failed" && failedSteps.length > 0 && !status?.process_crashed && (
        <FailureBanner
          failedSteps={failedSteps}
          sessionId={sessionId}
          workspacePath={status?.project_root ?? ""}
          lang={status?.lang ?? ""}
          onRetry={handleRunSession}
          onNewBuild={onBack}
        />
      )}

      {/* Correctness Amplifier candidate race — only appears once real [vs] lines show up in the log */}
      <CandidateRaceStrip lines={logLines} />

      {/* Tab switcher */}
      <div className="flex border-b border-[var(--dtx-code-border)] flex-shrink-0">
        <button
          onClick={() => setActiveTab("steps")}
          className={`px-4 py-1.5 text-meta font-bold uppercase tracking-wider border-b-2 transition-colors ${
            activeTab === "steps"
              ? "border-cyan-500 text-cyan-300"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Steps {stepCount > 0 && `(${stepCount})`}
        </button>
        <button
          onClick={() => setActiveTab("files")}
          className={`px-4 py-1.5 text-meta font-bold uppercase tracking-wider border-b-2 transition-colors ${
            activeTab === "files"
              ? "border-emerald-500 text-emerald-300"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Files {uniqueFileCount > 0 && `(${uniqueFileCount})`}
        </button>
        <button
          onClick={() => setActiveTab("log")}
          className={`px-4 py-1.5 text-meta font-bold uppercase tracking-wider border-b-2 transition-colors ${
            activeTab === "log"
              ? "border-cyan-500 text-cyan-300"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Log {logLines.length > 0 && `(${logLines.length})`}
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === "files" ? (
          <FilesPanel steps={steps} sessionId={sessionId} />
        ) : activeTab === "steps" ? (
          <div className="h-full overflow-y-auto p-3 space-y-1.5">
            {stepCount === 0 ? (
              pollError ? (
                /* ── Hard error state ── */
                <div className="flex flex-col items-center justify-center h-full gap-3 px-4 py-8">
                  <AlertTriangle size={24} className="text-red-500" />
                  <p className="text-body text-red-400 font-bold text-center">
                    Build process stopped
                  </p>
                  <p className="text-label text-gray-500 text-center break-all">{pollError}</p>
                  <p className="text-meta text-gray-700 text-center">
                    Check that hive.py ran and the sessions directory is writable.
                  </p>
                </div>
              ) : (
                /* ── DAG generating — live activity view ── */
                <div className="flex flex-col h-full">
                  {/* Activity header */}
                  <div className="flex items-center gap-3 py-4 px-2">
                    <div className="w-5 h-5 border border-purple-500/60 border-t-purple-400 rounded-full animate-spin flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-label text-gray-300 font-bold">
                        Architect mapping steps...
                      </p>
                      <p className="text-label text-gray-600">
                        Steps will appear here as the plan is written
                      </p>
                    </div>
                  </div>

                  {/* Animated activity bar */}
                  <div className="px-2 mb-4">
                    <div className="h-1 rounded-full bg-[var(--dtx-code-panel)] overflow-hidden">
                      <div className="h-full w-full rounded-full bg-gradient-to-r from-purple-600/70 via-cyan-400/70 to-purple-600/70 animate-pulse" />
                    </div>
                  </div>

                  {/* Live log preview — last 12 lines */}
                  {logLines.length > 0 ? (
                    <div className="flex-1 min-h-0 overflow-hidden mx-2 rounded-xl border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] flex flex-col">
                      <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-[var(--dtx-code-border)] flex-shrink-0">
                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        <span className="text-eyebrow uppercase font-bold tracking-wider text-gray-600">
                          Live output · {logLines.length} lines
                        </span>
                      </div>
                      <div className="flex-1 overflow-y-auto p-2 font-mono flex flex-col-reverse">
                        {[...logLines]
                          .reverse()
                          .slice(0, 12)
                          .map((line, i) => (
                            <div
                              key={i}
                              className={`text-label leading-relaxed whitespace-pre-wrap ${
                                line.includes("ERROR") || line.includes("FAIL")
                                  ? "text-red-400"
                                  : line.includes("PASS") || line.includes("complete")
                                    ? "text-emerald-400"
                                    : line.includes("WARN")
                                      ? "text-amber-400"
                                      : i === 0
                                        ? "text-gray-300"
                                        : "text-gray-600"
                              }`}
                            >
                              {line}
                            </div>
                          ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex-1 mx-2 rounded-xl border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] flex items-center justify-center">
                      <p className="text-label text-gray-700 font-mono">
                        Waiting for process output...
                      </p>
                    </div>
                  )}

                  {/* Bottom hint */}
                  <p className="text-meta text-gray-700 text-center py-3">
                    Switch to <span className="text-gray-500 font-bold">Log</span> tab for full
                    output
                  </p>
                </div>
              )
            ) : (
              <>
                {/* Active step callout */}
                {activeSteps.map((s) => (
                  <ActiveStepCard key={s.id} step={s} logLines={logLines} />
                ))}
                {/* All other steps — memoized, skip re-renders unless status changes */}
                {otherSteps.map((s) => (
                  <StepRow key={s.id} step={s} sessionId={sessionId} />
                ))}
              </>
            )}
          </div>
        ) : (
          <LogPanel lines={logLines} />
        )}
      </div>

      {/* Launch build loop button — shown when DAG is ready but loop not started */}
      {dagReady && !buildStarted && (
        <div className="border-t border-[var(--dtx-code-border)] p-3 flex-shrink-0">
          {runError && (
            <div className="text-label text-red-400 bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2 mb-2">
              {runError}
            </div>
          )}
          <div className="mb-2 flex items-center justify-between rounded-lg border border-[var(--dtx-code-border)] bg-black/20 px-3 py-2">
            <label className="flex items-center gap-2 text-label text-gray-400">
              <input
                type="checkbox"
                checked={amplifyEnabled}
                onChange={(e) => setAmplifyEnabled(e.target.checked)}
                className="accent-violet-500"
              />
              <Layers size={11} className="text-violet-400" />
              Correctness Amplifier — sample multiple candidates per step, keep the first
              oracle-verified pass
            </label>
            {amplifyEnabled && (
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setAmplifyKOverride(Math.max(1, effectiveAmplifyK - 1))}
                  className="h-5 w-5 rounded border border-[var(--dtx-code-border)] text-label text-gray-400 hover:border-violet-500/50 hover:text-violet-300"
                >
                  −
                </button>
                <span className="w-16 text-center text-label font-mono text-violet-300">
                  {effectiveAmplifyK} candidate{effectiveAmplifyK === 1 ? "" : "s"}
                </span>
                <button
                  type="button"
                  onClick={() => setAmplifyKOverride(Math.min(10, effectiveAmplifyK + 1))}
                  className="h-5 w-5 rounded border border-[var(--dtx-code-border)] text-label text-gray-400 hover:border-violet-500/50 hover:text-violet-300"
                >
                  +
                </button>
                {amplifyKOverride === null && (
                  <span
                    className="text-meta text-gray-600"
                    title={`Recommended for this machine (${hardwareBudgetMb ?? "?"}MB budget)`}
                  >
                    (recommended)
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center justify-between">
            <div className="text-label text-gray-500">
              {stepCount} steps ready — Compiler Oracle validates each step
            </div>
            <button
              onClick={handleRunSession}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-500/20 border border-emerald-500/50 text-emerald-300 rounded-lg text-label font-bold hover:bg-emerald-500/30 transition-colors"
            >
              <Play size={11} />
              Start Build
            </button>
          </div>
        </div>
      )}

      {/* Running indicator */}
      {running && !dagReady && (
        <div className="border-t border-[var(--dtx-code-border)] px-3 py-2.5 flex-shrink-0">
          <div className="flex items-center gap-2 text-label text-cyan-400">
            <div className="w-3 h-3 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
            Build loop running —{" "}
            <GlossaryTerm
              term="Builder"
              definition="Third AI role. Executes one step at a time — generates the actual code for each step in the Architect's plan. Works against the current state of the file, not from scratch."
            >
              Builder
            </GlossaryTerm>
            {" → "}
            <GlossaryTerm
              term="Compiler Oracle"
              definition="Not an AI. The actual compiler — rustc, go build, or python. Zero hallucinations. If code doesn't compile, the step fails and retries regardless of what any model says. Final arbiter of correctness."
            >
              Compiler Oracle
            </GlossaryTerm>
            {" → "}
            <GlossaryTerm
              term="Monitor"
              definition="Fourth AI role. Reviews Builder output before it's written to disk. Catches logic errors, hallucinations, and drift from the original spec. Can submit a competing approach."
            >
              Monitor
            </GlossaryTerm>
          </div>
        </div>
      )}
    </div>
  );
}
