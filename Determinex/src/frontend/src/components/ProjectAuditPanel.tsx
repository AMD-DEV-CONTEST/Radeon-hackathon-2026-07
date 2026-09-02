"use client";
import React, { useState } from "react";
import {
  ShieldCheck,
  Play,
  Activity,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { isTauri, invokeSafe } from "@/lib/api";

interface AuditCategory {
  title: string;
  score: number;
  status: "pass" | "warn" | "fail" | "skipped";
  details: string;
}

interface Props {
  workspacePath?: string;
}

export function ProjectAuditPanel({ workspacePath = "" }: Props) {
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<{
    score: number;
    categories: AuditCategory[];
    blockers: string[];
    snykOutput: string;
  } | null>(null);

  const runAudit = async () => {
    setRunning(true);
    setReport(null);

    let tauriAuditData = null;
    try {
      tauriAuditData = await invokeSafe<any>("run_project_audit", { workspacePath: workspacePath });
    } catch (e) {
      console.error("Tauri audit failed:", e);
    }

    if (tauriAuditData) {
      setReport({
        score: tauriAuditData.score,
        categories: tauriAuditData.categories,
        blockers: tauriAuditData.blockers,
        snykOutput: tauriAuditData.snykOutput,
      });
    } else {
      setReport({
        score: 0,
        categories: [],
        blockers: ["Audit command failed or returned null"],
        snykOutput: "Error communicating with backend.",
      });
    }
    setRunning(false);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-[var(--dtx-code-bg)]/90 text-gray-300 font-sans">
      {/* Panel Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-white/5 bg-black/20 shrink-0">
        <ShieldCheck size={20} className="text-[var(--determinex-accent)]" />
        <div>
          <h3 className="text-sm font-black uppercase tracking-wider text-white">
            Shippable Project Audit
          </h3>
          <p className="text-label text-gray-500 font-mono">
            Scan code, dependencies, security, and release blockers
          </p>
        </div>
      </div>

      {/* Main Panel Content */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5 no-scrollbar">
        {!report && !running && (
          <div className="flex flex-col items-center justify-center py-12 text-center border border-white/5 bg-white/[0.02] rounded-2xl p-6">
            <div className="h-14 w-14 rounded-full border border-white/10 bg-white/[0.04] flex items-center justify-center mb-4">
              <ShieldCheck size={26} className="text-gray-600 animate-pulse" />
            </div>
            <h4 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">
              Audit Scorecard Ready
            </h4>
            <p className="text-label text-gray-500 max-w-[280px] leading-relaxed mb-5">
              Run a complete security, compile, and release readiness audit of the current
              workspace.
            </p>
            <button
              onClick={runAudit}
              className="flex items-center gap-2 px-5 py-2.5 bg-[var(--determinex-accent)] text-white text-xs font-black uppercase tracking-wider rounded-lg shadow-lg hover:shadow-[var(--determinex-accent)]/20 transition-all cursor-pointer"
            >
              <Play size={12} /> Run Audit Scan
            </button>
          </div>
        )}

        {running && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-8 h-8 border-2 border-[var(--determinex-accent)] border-t-transparent rounded-full animate-spin mb-4" />
            <span className="text-meta font-mono text-gray-500 animate-pulse uppercase tracking-widest">
              Scanning codebase workspace…
            </span>
          </div>
        )}

        {report && (
          <div className="space-y-5 animate-in fade-in slide-in-from-bottom-2 duration-300">
            {/* Headline Score */}
            <div className="flex items-center justify-between border border-white/10 bg-[var(--dtx-code-panel)]/40 rounded-2xl p-4 shadow-xl">
              <div>
                <span className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
                  Shippable Status Score
                </span>
                <div className="text-2xl font-black text-white flex items-center gap-1.5 mt-0.5">
                  <span>{report.score}/100</span>
                  {report.score >= 90 && <Sparkles size={16} className="text-yellow-400" />}
                </div>
              </div>
              <div
                className={`text-meta font-black uppercase tracking-widest px-3 py-1.5 rounded-full border ${
                  report.score >= 90
                    ? "border-emerald-500/25 bg-emerald-950/20 text-emerald-400"
                    : "border-amber-500/25 bg-amber-950/20 text-amber-400"
                }`}
              >
                {report.score >= 90 ? "PASSED AUDIT" : "WARN"}
              </div>
            </div>

            {/* Audit Categories */}
            <div className="space-y-2">
              <span className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
                Audit Scorecard
              </span>
              {report.categories.map((c, i) => (
                <div
                  key={i}
                  className="border border-white/5 bg-[var(--dtx-code-panel)]/20 rounded-xl p-3.5 space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white">{c.title}</span>
                    <span
                      className={`text-eyebrow font-black uppercase px-2 py-0.5 rounded ${
                        c.status === "pass"
                          ? "text-emerald-400 bg-emerald-950/40"
                          : "text-amber-400 bg-amber-950/40"
                      }`}
                    >
                      {c.status.toUpperCase()} ({c.score}%)
                    </span>
                  </div>
                  <p className="text-label text-gray-500 leading-relaxed font-mono">{c.details}</p>
                </div>
              ))}
            </div>

            {/* Blockers / Warnings */}
            {report.blockers.length > 0 && (
              <div className="space-y-2">
                <span className="text-eyebrow font-black uppercase tracking-widest text-red-400">
                  Release Warnings & Blockers
                </span>
                <div className="border border-red-500/10 bg-red-950/5 rounded-xl p-3.5 space-y-1.5">
                  {report.blockers.map((b, i) => (
                    <div key={i} className="flex gap-2 text-label text-red-300 font-mono">
                      <AlertCircle size={12} className="shrink-0 mt-0.5" />
                      <span>{b}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Snyk detailed logs */}
            <div className="space-y-2">
              <span className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
                Security Audit Logs
              </span>
              <pre className="text-label text-gray-400 font-mono bg-black/60 border border-white/5 rounded-xl p-3 overflow-x-auto max-h-48 whitespace-pre leading-relaxed">
                {report.snykOutput}
              </pre>
            </div>

            <button
              onClick={runAudit}
              className="w-full flex items-center justify-center gap-1.5 px-4 py-2 border border-white/10 hover:border-white/20 rounded-lg text-xs font-bold transition-all hover:bg-white/[0.02]"
            >
              <RefreshCw size={11} /> Re-run Full Audit
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
