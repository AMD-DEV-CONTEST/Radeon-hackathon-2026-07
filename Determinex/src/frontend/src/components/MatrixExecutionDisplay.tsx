"use client";

import React, { useEffect, useRef, useState } from "react";
import { XOctagon, Cpu, Code2, Eye, CheckCircle2, AlertTriangle } from "lucide-react";
import { VanguardToggle } from "@/components/VanguardToggle";

// ─── Agent definitions — maps to the 3 sequential MoA stages ─────────────────
//
// Model tags corrected 2026-07-29. These named determinex-sentinel-v3 /
// engineer-v10-dsl / observer-v5-dsl -- one whole generation behind what
// scripts/hive/ctx_config.py actually assigns (v5-dsl / v11-dsl / v6-dsl) and behind
// model_router.CURRENT_MODEL_IDS. Same family of error as the Proof Center table that
// credited shipped models with their predecessors' scores.
//
// Pinned against CURRENT_MODEL_IDS by tests/test_ui_names_current_models.py so the tags
// cannot drift again.
//
// HISTORY WORTH KNOWING: this file used to contain ONLY these constants, the AgentStatus
// type and a props interface -- no component. React hooks, four icons and VanguardToggle
// were imported and unused. The body had been deleted and the scaffolding left, so
// page.tsx imported the TYPE alone and the three-agent pipeline was never rendered
// anywhere, while every input it needs (agentStatus, matrixLogs, executeAbort,
// retryCount) already existed and was live. Implemented 2026-07-29 against the props
// interface that survived.
const AGENTS = [
  {
    id: "sentinel",
    label: "SENTINEL",
    model: "determinex-sentinel-v5-dsl",
    role: "Architect & Planner",
    color: "var(--dtx-alt-2)", // cyan
    glow: "rgba(0,229,255,0.6)",
    icon: Cpu,
  },
  {
    id: "engineer",
    label: "ENGINEER",
    model: "determinex-engineer-v11-dsl",
    role: "Code Synthesis",
    color: "var(--dtx-alt)", // violet
    glow: "rgba(167,139,250,0.6)",
    icon: Code2,
  },
  {
    id: "observer",
    label: "OBSERVER",
    model: "determinex-observer-v6-dsl",
    role: "Audit & Verdict",
    color: "var(--dtx-warn)", // amber-orange
    glow: "rgba(249,115,22,0.6)",
    icon: Eye,
  },
] as const;

type AgentId = (typeof AGENTS)[number]["id"];

export interface AgentStatus {
  /** Which agent currently holds the VRAM tollbooth. null = idle. */
  currentAgent: AgentId | null;
  /** Whether the full pipeline is running */
  isExecuting: boolean;
  /** CLEAN | HALLUCINATION | PARTIAL — populated after Observer completes */
  verdict: string | null;
  /** Observer confidence 0–1 */
  confidence: number | null;
  /** True if accepted (CLEAN + confidence >= 0.75) */
  accepted: boolean | null;
  /** Structured error if the pipeline hard-aborted */
  error: { stage: string; message: string } | null;
}

interface MatrixExecutionDisplayProps {
  agentStatus: AgentStatus;
  logs: string[];
  onAbort: () => void;
  retryCount?: number;
}

const STAGE_ORDER: readonly AgentId[] = AGENTS.map((a) => a.id) as unknown as AgentId[];

/** Where a stage sits relative to the one currently running. */
function stageState(id: AgentId, status: AgentStatus): "idle" | "active" | "done" | "failed" {
  if (status.error && status.error.stage.toLowerCase().includes(id)) return "failed";
  if (status.currentAgent === id) return "active";

  const current = status.currentAgent ? STAGE_ORDER.indexOf(status.currentAgent) : -1;
  const mine = STAGE_ORDER.indexOf(id);
  // Once a verdict exists the run finished, so every stage is done unless it failed.
  if (!status.isExecuting && status.verdict) return "done";
  if (current > mine) return "done";
  return "idle";
}

export function MatrixExecutionDisplay({
  agentStatus,
  logs,
  onAbort,
  retryCount = 0,
}: MatrixExecutionDisplayProps) {
  const logRef = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(true);

  // Follow the tail while running, but stop fighting the user the moment they scroll up.
  useEffect(() => {
    if (!pinned || !logRef.current) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs, pinned]);

  const verdictAccepted = agentStatus.accepted === true;
  const verdictRejected = agentStatus.verdict !== null && agentStatus.accepted === false;

  return (
    <div
      className="overflow-hidden rounded-2xl border"
      style={{
        borderColor: "var(--dtx-code-border)",
        background: "var(--dtx-code-panel)",
        fontFamily: "var(--determinex-font-sans)",
      }}
      data-testid="matrix-execution-display"
    >
      {/* header */}
      <div
        className="flex items-center gap-3 border-b px-4 py-2.5"
        style={{ borderColor: "var(--dtx-code-border-subtle)" }}
      >
        <span className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
          MoA Pipeline
        </span>
        {agentStatus.isExecuting && (
          <span
            className="text-eyebrow font-black uppercase tracking-widest"
            style={{ color: "var(--dtx-alt-2)" }}
          >
            running
          </span>
        )}
        {retryCount > 0 && (
          <span className="text-meta font-mono" style={{ color: "var(--dtx-warn)" }}>
            {retryCount} {retryCount === 1 ? "retry" : "retries"}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <VanguardToggle />
          {agentStatus.isExecuting && (
            <button
              type="button"
              onClick={onAbort}
              title="Abort the running pipeline"
              className="inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-eyebrow font-black uppercase tracking-widest transition-colors"
              style={{ borderColor: "var(--dtx-fail)", color: "var(--dtx-fail)" }}
            >
              <XOctagon size={11} /> Abort
            </button>
          )}
        </div>
      </div>

      {/* the three stages */}
      <div className="grid grid-cols-3 gap-2 p-3">
        {AGENTS.map((agent) => {
          const state = stageState(agent.id, agentStatus);
          const Icon = agent.icon;
          const lit = state === "active";
          return (
            <div
              key={agent.id}
              data-testid={`matrix-stage-${agent.id}`}
              data-state={state}
              className="rounded-xl border px-3 py-2.5 transition-all duration-300"
              style={{
                borderColor: lit ? agent.color : "var(--dtx-code-border-subtle)",
                background: lit ? "var(--dtx-code-raised)" : "transparent",
                boxShadow: lit ? `0 0 18px ${agent.glow}` : "none",
                opacity: state === "idle" ? 0.45 : 1,
              }}
            >
              <div className="flex items-center gap-2">
                <Icon size={13} style={{ color: agent.color }} />
                <span
                  className="text-eyebrow font-black uppercase tracking-widest"
                  style={{ color: agent.color }}
                >
                  {agent.label}
                </span>
                {state === "done" && (
                  <CheckCircle2 size={12} style={{ color: "var(--dtx-ok)" }} className="ml-auto" />
                )}
                {state === "failed" && (
                  <AlertTriangle
                    size={12}
                    style={{ color: "var(--dtx-fail)" }}
                    className="ml-auto"
                  />
                )}
              </div>
              <div className="mt-1 text-meta text-gray-500">{agent.role}</div>
              {/* The model tag is shown because "which agent" is only half the question --
                  "running which model" is the half that makes a run reproducible. */}
              <div className="text-meta font-mono text-gray-600 truncate" title={agent.model}>
                {agent.model}
              </div>
            </div>
          );
        })}
      </div>

      {/* verdict */}
      {agentStatus.verdict && (
        <div
          className="flex items-center gap-2 border-t px-4 py-2"
          style={{ borderColor: "var(--dtx-code-border-subtle)" }}
        >
          <span className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
            Verdict
          </span>
          <span
            className="text-label font-black font-mono"
            style={{
              color: verdictAccepted
                ? "var(--dtx-ok)"
                : verdictRejected
                  ? "var(--dtx-fail)"
                  : "var(--dtx-warn)",
            }}
          >
            {agentStatus.verdict}
          </span>
          {agentStatus.confidence !== null && (
            <span className="text-meta font-mono text-gray-600">
              {(agentStatus.confidence * 100).toFixed(0)}% confidence
            </span>
          )}
          {/* accepted === null means the verdict arrived without an acceptance decision --
              rendered as neither pass nor fail rather than defaulting to one. */}
          {agentStatus.accepted === null && (
            <span className="text-meta text-gray-600">acceptance not recorded</span>
          )}
        </div>
      )}

      {/* hard abort / error */}
      {agentStatus.error && (
        <div
          className="border-t px-4 py-2"
          style={{ borderColor: "var(--dtx-code-border-subtle)" }}
        >
          <span
            className="text-meta font-black uppercase tracking-widest"
            style={{ color: "var(--dtx-fail)" }}
          >
            {agentStatus.error.stage}
          </span>
          <span className="ml-2 text-label font-mono text-gray-400">
            {agentStatus.error.message}
          </span>
        </div>
      )}

      {/* bounded log tail -- the full list can run to thousands of lines */}
      {logs.length > 0 && (
        <div
          ref={logRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
          }}
          className="max-h-32 overflow-y-auto border-t px-4 py-2 font-mono text-meta leading-relaxed"
          style={{ borderColor: "var(--dtx-code-border-subtle)", color: "var(--dtx-code-muted)" }}
        >
          {logs.slice(-40).map((line, i) => (
            <div
              key={i}
              style={line.includes("[ERROR]") ? { color: "var(--dtx-fail)" } : undefined}
            >
              {line}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
