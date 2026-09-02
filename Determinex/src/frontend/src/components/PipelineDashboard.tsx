import React, { useState, useEffect, useCallback } from "react";
import {
  Activity,
  Check,
  Play,
  Target,
  Cpu,
  Smartphone,
  Server,
  Globe,
  Database,
  Layers,
  Edit2,
  FileCode2,
} from "lucide-react";
import { getHiveSessionStatus } from "@/lib/api";
import { useErrorToast } from "@/components/ErrorToast";

// Color profiles per topology type
const TOPO_COLORS: Record<string, { accent: string; glow: string; border: string; bg: string }> = {
  mobile_app: {
    accent: "text-emerald-400",
    glow: "shadow-[0_0_8px_rgba(52,211,153,0.5)]",
    border: "border-emerald-500",
    bg: "bg-emerald-950/20",
  },
  web_app: {
    accent: "text-cyan-400",
    glow: "shadow-[0_0_8px_rgba(0,229,255,0.5)]",
    border: "border-cyan-500",
    bg: "bg-cyan-950/20",
  },
  backend_service: {
    accent: "text-amber-400",
    glow: "shadow-[0_0_8px_rgba(245,158,11,0.5)]",
    border: "border-amber-500",
    bg: "bg-amber-950/20",
  },
  full_stack: {
    accent: "text-purple-400",
    glow: "shadow-[0_0_8px_rgba(168,85,247,0.5)]",
    border: "border-purple-500",
    bg: "bg-purple-950/20",
  },
  ml_pipeline: {
    accent: "text-rose-400",
    glow: "shadow-[0_0_8px_rgba(251,113,133,0.5)]",
    border: "border-rose-500",
    bg: "bg-rose-950/20",
  },
  devops_infra: {
    accent: "text-orange-400",
    glow: "shadow-[0_0_8px_rgba(251,146,60,0.5)]",
    border: "border-orange-500",
    bg: "bg-orange-950/20",
  },
};

const TOPO_ICONS: Record<string, React.ReactNode> = {
  mobile_app: <Smartphone size={12} />,
  web_app: <Globe size={12} />,
  backend_service: <Server size={12} />,
  full_stack: <Layers size={12} />,
  ml_pipeline: <Cpu size={12} />,
  devops_infra: <Database size={12} />,
};

interface TopoPhase {
  name: string;
  desc: string;
  tasks: string[];
}

interface Topology {
  id: string;
  label: string;
  phases: TopoPhase[];
}

interface LiveStep {
  id: number;
  status: string;
  target_file: string;
  instruction: string;
  compiler_result?: string;
}

interface LiveStatus {
  session_id: string;
  lang: string;
  steps: LiveStep[];
  api_cost_usd: number;
  project_root?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// WAR ROOM — live session monitor
// ─────────────────────────────────────────────────────────────────────────────

function WarRoom({ sessionId }: { sessionId?: string | null }) {
  const [status, setStatus] = useState<LiveStatus | null>(null);

  const poll = useCallback(async () => {
    if (!sessionId) return;
    try {
      const data = (await getHiveSessionStatus(sessionId)) as unknown as LiveStatus;
      setStatus(data);
    } catch {
      // session may not exist yet during DAG gen — silent
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setStatus(null);
      return;
    }
    poll();
    const t = setInterval(poll, 2500);
    return () => clearInterval(t);
  }, [sessionId, poll]);

  if (!sessionId) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 px-6 text-center">
        <Activity size={24} className="text-gray-700 opacity-40" />
        <p className="text-label font-bold text-gray-600">No Active Build</p>
        <p className="text-label text-gray-700 leading-relaxed">
          Start a build from the Concept Lab — live session data will appear here.
        </p>
      </div>
    );
  }

  const steps = status?.steps ?? [];
  const total = steps.length;
  const complete = steps.filter((s) => s.status === "complete").length;
  const failed = steps.filter((s) => s.status === "failed").length;
  const inProgress = steps.find((s) => s.status === "in_progress");

  let phase: "dag" | "building" | "done" | "failed" = "dag";
  if (total > 0) {
    if (complete === total) phase = "done";
    else if (failed > 0 && !inProgress && complete + failed === total) phase = "failed";
    else phase = "building";
  }

  const phaseColor = {
    dag: "text-purple-400",
    building: "text-cyan-400",
    done: "text-emerald-400",
    failed: "text-red-400",
  }[phase];

  const phaseLabel = {
    dag: "Generating Plan",
    building: "Building",
    done: "Complete",
    failed: "Failed",
  }[phase];

  return (
    <div className="flex flex-col h-full overflow-hidden bg-[var(--dtx-code-bg-deep)]">
      {/* Phase header */}
      <div className="px-4 py-3 border-b border-[var(--dtx-code-border)] flex-shrink-0 bg-[var(--dtx-code-bg)]/60">
        <div className="flex items-center gap-2">
          <Activity size={11} className={phaseColor} />
          <span className={`text-eyebrow font-bold uppercase tracking-widest ${phaseColor}`}>
            {phaseLabel}
          </span>
          {(phase === "dag" || phase === "building") && (
            <div
              className={`w-2.5 h-2.5 border border-current border-t-transparent rounded-full animate-spin opacity-60 ${phaseColor}`}
            />
          )}
        </div>

        {total > 0 && (
          <>
            <div className="mt-2 h-1 bg-[var(--dtx-code-panel)] rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${Math.round((complete / total) * 100)}%`,
                  background:
                    phase === "failed" ? "#ef4444" : phase === "done" ? "#10b981" : "#06b6d4",
                }}
              />
            </div>
            <p className="text-label text-gray-600 mt-1">
              {complete}/{total} steps
              {failed > 0 && <span className="text-red-400 ml-2">{failed} failed</span>}
            </p>
          </>
        )}

        {status && status.api_cost_usd > 0 && (
          <p className="text-meta text-amber-400/70 mt-1.5">
            ${status.api_cost_usd.toFixed(4)} API cost
          </p>
        )}
      </div>

      {/* Active step callout */}
      {inProgress && (
        <div className="px-4 py-2.5 border-b border-[var(--dtx-code-border)] flex-shrink-0 bg-cyan-950/10">
          <p className="text-eyebrow text-gray-600 uppercase font-bold tracking-widest mb-1">
            Active Step
          </p>
          <div className="flex items-center gap-1.5 mb-0.5">
            <div className="w-2 h-2 border border-cyan-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
            <span className="text-label font-mono text-cyan-400 truncate">
              {inProgress.target_file}
            </span>
          </div>
          <p className="text-label text-gray-400 leading-snug line-clamp-2">
            {inProgress.instruction}
          </p>
        </div>
      )}

      {/* Step list */}
      <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar">
        {total === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <div className="w-5 h-5 border border-purple-500/60 border-t-purple-400 rounded-full animate-spin" />
            <p className="text-label text-gray-600">Parsing spec…</p>
          </div>
        ) : (
          <div className="p-3 space-y-0.5">
            {steps.map((s) => (
              <div
                key={s.id}
                className="flex items-center gap-2 py-1.5 px-2 rounded hover:bg-[var(--dtx-code-panel)] transition-colors"
              >
                {s.status === "complete" ? (
                  <Check size={10} className="text-emerald-400 flex-shrink-0" />
                ) : s.status === "failed" ? (
                  <span className="text-meta text-red-400 flex-shrink-0 font-bold">✕</span>
                ) : s.status === "in_progress" ? (
                  <div className="w-2.5 h-2.5 border border-cyan-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                ) : (
                  <div className="w-2.5 h-2.5 rounded-full border border-gray-700 flex-shrink-0" />
                )}
                <span className="text-meta font-mono text-gray-700 flex-shrink-0">#{s.id}</span>
                <span className="text-meta font-mono text-gray-500 truncate min-w-0 flex-1">
                  {s.target_file}
                </span>
                {s.compiler_result === "PASS" && (
                  <span className="text-meta font-bold text-emerald-600 flex-shrink-0">PASS</span>
                )}
                {s.compiler_result === "FAIL" && (
                  <span className="text-meta font-bold text-red-600 flex-shrink-0">FAIL</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5 border-t border-[var(--dtx-code-border)] flex-shrink-0 flex items-center gap-2">
        <FileCode2 size={9} className="text-gray-700 flex-shrink-0" />
        <p className="text-meta text-gray-700 font-mono truncate">{sessionId.slice(0, 20)}…</p>
        <p className="text-meta text-gray-700 ml-auto flex-shrink-0">Full view in center →</p>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// PIPELINE DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────

export const PipelineDashboard = ({
  showWarRoom,
  setShowWarRoom,
  lastPrompt,
  sessionId,
}: {
  showWarRoom: boolean;
  setShowWarRoom: (val: boolean) => void;
  lastPrompt?: string;
  sessionId?: string | null;
}) => {
  const showError = useErrorToast();
  const [topology, setTopology] = useState<Topology | null>(null);

  // Topology is derived from the active session's DAG when a session is running.
  // Without an active session, phases fall back to the static Determinex pipeline description below.

  // Auto-switch to War Room when a session becomes active
  useEffect(() => {
    if (sessionId) setShowWarRoom(true);
  }, [sessionId, setShowWarRoom]);

  const colors = TOPO_COLORS[topology?.id || "web_app"] || TOPO_COLORS.web_app;
  const icon = TOPO_ICONS[topology?.id || "web_app"] || TOPO_ICONS.web_app;

  const phases: TopoPhase[] = topology?.phases || [
    {
      name: "Phase 1: Architect Sentinel",
      desc: "Mapping context from Left Brain into a structured execution plan. Analyzing exact requirements.",
      tasks: ["Parse Prompt", "Generate Plan"],
    },
    {
      name: "Phase 2: Code Generation",
      desc: "The Pack Engineer physically writes the syntax based on the architecture.",
      tasks: ["Synthesize Code"],
    },
    {
      name: "Phase 3: The Crucible",
      desc: "Final gauntlet stabilization. Build is analyzed for type integrity and syntax crashes.",
      tasks: ["Hydrate Test"],
    },
  ];

  return (
    <div className="flex flex-col h-full w-full bg-transparent">
      <div className="p-3 border-b border-[var(--dtx-code-border)] flex flex-col gap-3 bg-[var(--dtx-code-panel)]">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-4">
            <span
              onClick={() => setShowWarRoom(false)}
              className={`text-meta font-black tracking-widest uppercase cursor-pointer transition-colors flex items-center gap-1 ${!showWarRoom ? "text-amber-500 drop-shadow-[0_0_5px_rgba(245,158,11,0.8)]" : "text-gray-500 hover:text-amber-500"}`}
            >
              <Target size={12} /> Book of Operations
            </span>
            <span
              onClick={() => setShowWarRoom(true)}
              className={`text-meta font-black tracking-widest uppercase cursor-pointer transition-colors flex items-center gap-1 ${showWarRoom ? "text-red-500 drop-shadow-[0_0_5px_rgba(239,68,68,0.8)]" : "text-gray-500 hover:text-red-500"}`}
            >
              <Activity size={12} />
              WAR ROOM
              {sessionId && (
                <span className="ml-1 w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse inline-block" />
              )}
            </span>
          </div>
          {topology && (
            <div
              className={`flex items-center gap-1.5 px-2 py-1 rounded border ${colors.border}/30 ${colors.bg} ${colors.accent}`}
            >
              {icon}
              <span className="text-eyebrow font-black uppercase tracking-widest">
                {topology.label}
              </span>
            </div>
          )}
        </div>
      </div>

      {showWarRoom ? (
        <WarRoom sessionId={sessionId} />
      ) : (
        <div className="flex flex-col flex-1 overflow-y-auto no-scrollbar p-6 bg-[var(--dtx-code-bg-deep)]">
          {phases.map((phase, phaseIdx) => {
            const isFirst = phaseIdx === 0;
            const isLast = phaseIdx === phases.length - 1;
            const phaseColor = isLast
              ? "text-red-500/70"
              : isFirst
                ? colors.accent
                : "text-gray-400";

            return (
              <div
                key={phaseIdx}
                className={`flex w-full mb-10 relative ${phaseIdx > 0 ? "opacity-50" : ""}`}
              >
                <div className="w-1/2 pr-8 text-right flex flex-col justify-center">
                  <h4
                    className={`${phaseColor} font-black uppercase text-meta tracking-widest mb-2 ${isFirst ? "drop-shadow-sm" : ""}`}
                  >
                    {phase.name}
                  </h4>
                  <p className="text-gray-400 text-label leading-relaxed">{phase.desc}</p>
                </div>
                <div
                  className={`absolute left-1/2 top-0 ${isLast ? "h-full" : "bottom-[-2.5rem]"} w-[2px] bg-gradient-to-b ${isFirst ? "from-cyan-500 via-[var(--dtx-code-border)] to-[var(--dtx-code-border)]" : "from-[var(--dtx-code-border)] to-transparent"} -translate-x-1/2 ${isFirst ? colors.glow : ""}`}
                ></div>
                <div
                  className={`absolute left-1/2 top-1/2 ${isFirst ? "w-5 h-5 rotate-45" : "w-4 h-4 rounded-full"} border-[2px] ${isFirst ? colors.border : isLast ? "border-red-900" : "border-[var(--dtx-code-border)]"} bg-[var(--dtx-code-bg)] -translate-x-1/2 -translate-y-1/2 flex items-center justify-center ${isFirst ? colors.glow : ""}`}
                >
                  {isFirst && (
                    <div className="w-1.5 h-1.5 bg-white rounded-full -rotate-45 animate-pulse"></div>
                  )}
                </div>
                <div className="w-1/2 pl-8 flex flex-col justify-center gap-2">
                  {phase.tasks.map((task, taskIdx) => {
                    const isActiveTask = isFirst && taskIdx === Math.min(1, phase.tasks.length - 1);
                    return (
                      <div
                        key={taskIdx}
                        className={`${isActiveTask ? `${colors.bg} border-l-[2px] ${colors.border}` : "bg-[var(--dtx-code-panel)]/50"} border border-[var(--dtx-code-border)] p-3 rounded shadow-sm ${isActiveTask ? "shadow-[0_0_10px_rgba(0,229,255,0.05)]" : "opacity-60"}`}
                      >
                        <div
                          className={`flex items-center ${isActiveTask ? "justify-between" : ""} gap-2 ${isActiveTask ? "mb-1" : ""}`}
                        >
                          <div className="flex items-center gap-2">
                            {taskIdx === 0 && isFirst ? (
                              <Check size={10} className="text-green-500" />
                            ) : isActiveTask ? (
                              <Activity size={10} className={`${colors.accent} animate-pulse`} />
                            ) : (
                              <Edit2 size={10} className="text-gray-500" />
                            )}
                            <span
                              className={`text-eyebrow uppercase font-bold ${isActiveTask ? colors.accent : "text-gray-500"} tracking-wider`}
                            >
                              {task}
                            </span>
                          </div>
                          {isActiveTask && (
                            <span
                              className={`text-eyebrow border ${colors.border}/50 ${colors.accent} px-1 rounded animate-pulse uppercase`}
                            >
                              Active
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
