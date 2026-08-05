"use client";
import { useCallback, useEffect, useState } from "react";
import { AlertCircle, AlertTriangle, Info, FileCode, X, Loader2 } from "lucide-react";
import { invokeSafe } from "@/lib/api";

type Severity = "error" | "warning" | "info";
type Problem = {
  id: string;
  severity: Severity;
  file: string;
  line: number;
  col: number;
  message: string;
  source: string;
};

type LspDiagnostic = {
  line: number;
  column: number;
  severity: string;
  message: string;
  file: string;
};

const SEV_CONFIG = {
  error: {
    icon: AlertCircle,
    color: "text-red-400",
    bg: "bg-red-950/20",
    border: "border-red-500/20",
    label: "error",
  },
  warning: {
    icon: AlertTriangle,
    color: "text-amber-400",
    bg: "bg-amber-950/10",
    border: "border-amber-500/15",
    label: "warning",
  },
  info: {
    icon: Info,
    color: "text-blue-400",
    bg: "bg-blue-950/10",
    border: "border-blue-500/15",
    label: "info",
  },
};

type Props = { workspacePath?: string };

export function ProblemsPanel({ workspacePath = "" }: Props) {
  const [problems, setProblems] = useState<Problem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Severity | "all">("all");
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    if (!workspacePath) {
      setProblems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    // LSP diagnostics only -- a "Problems" panel should feel instant, like
    // any editor's. Full dependency/security/release audits are a separate,
    // deliberately expensive operation the user opts into from the Audit
    // panel (a real scan of this repo takes over a minute); running that on
    // every mount AND every 60s forever here made Problems look permanently
    // stuck loading, and could stack overlapping scans if one run outlasted
    // the interval.
    const diags = await invokeSafe<LspDiagnostic[]>("get_lsp_diagnostics", {
      fileName: "",
      workspacePath,
    });
    const next: Problem[] = (diags ?? []).map((d, i) => {
      const severity: Severity =
        d.severity === "error" || d.severity === "warning" ? d.severity : "info";
      return {
        id: `diag-${d.file}-${d.line}-${d.column}-${i}`,
        severity,
        file: d.file || "workspace",
        line: d.line,
        col: d.column,
        message: d.message,
        source: "cargo check",
      };
    });

    setProblems(next);
    setLoading(false);
  }, [workspacePath]);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    const tick = async () => {
      if (inFlight || cancelled) return;
      inFlight = true;
      try {
        await refresh();
      } finally {
        inFlight = false;
      }
    };
    void tick();
    const id = setInterval(tick, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refresh]);

  const visible = problems.filter(
    (p) => !dismissed.has(p.id) && (filter === "all" || p.severity === filter)
  );
  const byFile = visible.reduce<Record<string, Problem[]>>((acc, p) => {
    (acc[p.file] = acc[p.file] ?? []).push(p);
    return acc;
  }, {});

  const counts = {
    error: problems.filter((p) => p.severity === "error" && !dismissed.has(p.id)).length,
    warning: problems.filter((p) => p.severity === "warning" && !dismissed.has(p.id)).length,
    info: problems.filter((p) => p.severity === "info" && !dismissed.has(p.id)).length,
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Filter bar */}
      <div
        className="shrink-0 flex items-center gap-1 border-b px-4 py-2"
        style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.2)" }}
      >
        {(["all", "error", "warning", "info"] as const).map((f) => {
          const count = f === "all" ? counts.error + counts.warning + counts.info : counts[f];
          return (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-eyebrow font-black uppercase tracking-widest transition-all ${filter === f ? "bg-white/[0.08] text-white" : "text-gray-600 hover:text-gray-400"}`}
            >
              {f !== "all" &&
                (() => {
                  const { icon: Icon, color } = SEV_CONFIG[f];
                  return <Icon size={10} className={color} />;
                })()}
              {f === "all" ? "All" : f} <span className="font-mono text-gray-700">{count}</span>
            </button>
          );
        })}
        <button
          onClick={() => void refresh()}
          className={`ml-auto text-gray-600 hover:text-gray-400 ${loading ? "animate-spin" : ""}`}
          title="Rescan"
        >
          <Loader2 size={11} />
        </button>
        <span className="text-meta text-gray-700 font-mono">{visible.length} problems</span>
      </div>

      {/* Problem list */}
      <div className="flex-1 overflow-y-auto no-scrollbar">
        {loading && problems.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 opacity-40">
            <Loader2 size={20} className="animate-spin text-gray-600" />
            {/* This really is a live `cargo check`, not a hung UI -- a cold or
                lock-contended check can legitimately take up to 90s (bounded
                server-side). A bare spinner with no explanation read as
                "stuck" during testing; say what's actually happening. */}
            <p className="text-meta text-gray-600 font-mono">
              Running cargo check… first run can take up to 90s
            </p>
          </div>
        ) : Object.keys(byFile).length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 opacity-30">
            <AlertCircle size={24} className="text-gray-600" />
            <p className="text-label text-gray-600">No diagnostics reported</p>
            {/* This used to read "Real cargo check results. Nothing wrong right now, or no
                workspace is open." -- an affirmative claim that a check had run and found the
                build clean. It cannot know that. get_lsp_symbols wraps cargo in
                `if let Ok(output)`, so a spawn failure (no Rust toolchain installed) or the 90 s
                timeout falls through and returns an empty diagnostic list, indistinguishable from
                a genuinely clean workspace. And for .ts/.tsx it returns empty BY DESIGN -- no
                TypeScript analysis is wired at all -- so an empty list there certified nothing
                whatsoever. Stating the scope instead of asserting a result. */}
            <p className="max-w-xs text-center text-meta text-gray-700 font-mono">
              Rust workspaces are analysed with cargo check. Other languages are not analysed yet,
              and a missing toolchain also reports nothing here.
            </p>
          </div>
        ) : (
          Object.entries(byFile).map(([file, fileProblems]) => (
            <div key={file} className="border-b border-white/[0.03]">
              <div className="flex items-center gap-2 px-4 py-2 bg-white/[0.02]">
                <FileCode size={11} className="text-gray-600 shrink-0" />
                <span className="text-label font-mono text-gray-500 truncate">{file}</span>
                <span className="ml-auto text-meta font-mono text-gray-700">
                  {fileProblems.length}
                </span>
              </div>
              {fileProblems.map((p) => {
                const { icon: Icon, color, bg, border } = SEV_CONFIG[p.severity];
                return (
                  <div
                    key={p.id}
                    className={`group flex items-start gap-3 px-4 py-2.5 border-l-2 ${border} ${bg} hover:brightness-110 transition-all`}
                  >
                    <Icon size={12} className={`${color} shrink-0 mt-0.5`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-label text-gray-300 leading-relaxed">{p.message}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        {p.line > 0 && (
                          <span className="text-meta font-mono text-gray-700">
                            {p.file}:{p.line}:{p.col}
                          </span>
                        )}
                        <span className="text-meta text-gray-700 border border-white/8 rounded px-1">
                          {p.source}
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={() => setDismissed((s) => new Set([...s, p.id]))}
                      className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-700 hover:text-gray-400"
                    >
                      <X size={11} />
                    </button>
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
