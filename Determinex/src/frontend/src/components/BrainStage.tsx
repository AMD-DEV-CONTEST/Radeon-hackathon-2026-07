"use client";

import { useState, useEffect } from "react";
import {
  Brain,
  Database,
  Cpu,
  Terminal,
  Activity,
  Circle,
  Zap,
  AlertCircle,
  ExternalLink,
  BarChart3,
  Settings,
} from "lucide-react";
import { ModelSelectorDropdown } from "@/components/ModelSelectorDropdown";
import { RosettaWeights } from "@/components/RosettaWeights";
import { isTauri, getHealthTelemetry } from "@/lib/api";
import { getRoleAssignments, type RoleAssignments } from "@/lib/api";

interface BrainStageProps {
  selectedModel: string;
  modelTiers: any[];
  /** Refetch the models registry after the user adds a model. */
  onModelAdded?: (modelId: string) => void;
  tandemPresets: any[];
  onSelectModel: (id: string) => void;
  matrixLogs: string[];
  onOpenModelSlots?: () => void;
  onOpenProof?: () => void;
}

function TelemetryGauge({
  label,
  value,
  max,
  color,
  unit,
}: {
  label: string;
  value: number | null;
  max: number;
  color: string;
  unit: string;
}) {
  const pct = value === null ? 0 : Math.min(100, Math.round((value / max) * 100));
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-meta font-bold uppercase tracking-widest text-gray-500">{label}</span>
        {value === null ? (
          <span className="font-mono text-label text-gray-700">—</span>
        ) : (
          <span className="font-mono text-label" style={{ color }}>
            {value}
            {unit}{" "}
            <span className="text-gray-600">
              / {max}
              {unit}
            </span>
          </span>
        )}
      </div>
      <div className="h-1.5 w-full rounded-full bg-white/5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${pct}%`,
            background: color,
            boxShadow: value !== null ? `0 0 8px ${color}` : "none",
          }}
        />
      </div>
    </div>
  );
}

export function BrainStage({
  selectedModel,
  modelTiers,
  onModelAdded,
  tandemPresets,
  onSelectModel,
  matrixLogs,
  onOpenModelSlots,
  onOpenProof,
}: BrainStageProps) {
  const [telemetry, setTelemetry] = useState<Record<string, any> | null>(null);
  const [tauriActive] = useState(() => isTauri());
  const [roles, setRoles] = useState<RoleAssignments | null>(null);

  useEffect(() => {
    if (!tauriActive) return;
    const poll = () => {
      getHealthTelemetry()
        .then((res) => setTelemetry(res))
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 8000);
    return () => clearInterval(id);
  }, [tauriActive]);

  useEffect(() => {
    getRoleAssignments()
      .then(setRoles)
      .catch(() => setRoles(null));
  }, []);

  const latestLogs = matrixLogs.slice(-16);

  const cpuPct: number | null = telemetry?.cpu_pct ?? null;
  const ramUsedGb: number | null =
    telemetry?.ram_used_mb != null ? Math.round((telemetry.ram_used_mb / 1024) * 10) / 10 : null;
  const ramTotalGb: number =
    telemetry?.ram_total_mb != null ? Math.round(telemetry.ram_total_mb / 1024) : 32;

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden p-5">
      {/* Ambient glow */}
      <div className="pointer-events-none absolute inset-0 opacity-10">
        <div
          className="absolute right-0 top-0 h-[500px] w-[500px] translate-x-1/3 -translate-y-1/3 rounded-full"
          style={{ background: "var(--determinex-accent)", filter: "blur(120px)" }}
        />
      </div>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-white/10 pb-4">
          <div>
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
              <Brain size={14} /> Engine Room
            </div>
            <h2
              className="mt-2 text-hero font-black leading-tight text-[var(--determinex-text)]"
              style={{ fontFamily: "var(--determinex-font-display)" }}
            >
              Brain & Model Slots
            </h2>
            <p className="mt-1 max-w-xl text-label leading-relaxed text-[var(--determinex-muted)]">
              Route Oracle, Architect, Builder, and Monitor through local models, API calls, or a
              hybrid stack.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {onOpenModelSlots && (
              <button
                type="button"
                onClick={onOpenModelSlots}
                className="flex items-center gap-1.5 rounded-full border border-orange-400/30 bg-orange-950/30 px-3 py-1.5 text-meta font-black uppercase tracking-widest text-orange-300 transition-all hover:bg-orange-900/40"
              >
                <Settings size={11} /> Model Slots
              </button>
            )}
            <span className="flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-950/40 px-3 py-1.5 text-label font-mono text-emerald-400">
              <Circle size={6} className="fill-emerald-400 animate-pulse" /> Brain Online
            </span>
          </div>
        </div>

        {/* Main Grid */}
        <div
          className="grid min-h-0 flex-1 grid-cols-1 gap-5 py-5 xl:grid-cols-2"
          style={{ gridTemplateRows: "1fr 1fr" }}
        >
          {/* Top Left: Model Topologies */}
          <div className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-black/30 p-5 shadow-xl backdrop-blur-md transition-all hover:border-white/20 overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="flex items-center gap-2 text-body font-black uppercase tracking-widest text-[var(--determinex-text)]">
                <Database size={16} className="text-orange-400" /> Active Topologies
              </h3>
            </div>
            {/* Latent-bridge weights live next to model selection because that is
                what they are: per-architecture weights for the models chosen here. */}
            <div className="border-b border-white/8 px-4 py-3">
              <RosettaWeights />
            </div>
            <div className="flex-1 overflow-y-auto no-scrollbar">
              <ModelSelectorDropdown
                selectedModel={selectedModel}
                modelTiers={modelTiers}
                tandemPresets={tandemPresets}
                onSelectModel={onSelectModel}
                onSelectTopology={(_, name) => onSelectModel(name)}
                onModelAdded={onModelAdded}
              />
            </div>
          </div>

          {/* Top Right: System Telemetry */}
          <div className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-black/30 p-5 shadow-xl backdrop-blur-md transition-all hover:border-white/20 overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="flex items-center gap-2 text-body font-black uppercase tracking-widest text-[var(--determinex-text)]">
                <Cpu size={16} className="text-cyan-400" /> System Telemetry
              </h3>
              {tauriActive && cpuPct !== null ? (
                <span className="rounded-full border border-cyan-500/20 bg-cyan-950/30 px-2 py-0.5 font-mono text-meta text-cyan-400">
                  LIVE
                </span>
              ) : (
                <span className="rounded-full border border-gray-700 bg-black/40 px-2 py-0.5 font-mono text-meta text-gray-600">
                  {tauriActive ? "NOT WIRED" : "BROWSER"}
                </span>
              )}
            </div>
            {tauriActive && cpuPct !== null ? (
              <div className="flex-1 flex flex-col gap-4 justify-center">
                <TelemetryGauge
                  label="CPU"
                  value={cpuPct}
                  max={100}
                  color="var(--dtx-alt-2)"
                  unit="%"
                />
                <TelemetryGauge
                  label="RAM"
                  value={ramUsedGb}
                  max={ramTotalGb}
                  color="var(--dtx-alt)"
                  unit="GB"
                />
              </div>
            ) : tauriActive ? (
              <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center opacity-50">
                <AlertCircle size={22} className="text-gray-600" />
                <p className="text-label font-mono text-gray-600 leading-relaxed">
                  get_health_telemetry doesn&apos;t report CPU/RAM yet.
                  <br />
                  Not measured -- not a stalled &quot;0%&quot;.
                </p>
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center opacity-50">
                <AlertCircle size={22} className="text-gray-600" />
                <p className="text-label font-mono text-gray-600 leading-relaxed">
                  Telemetry requires the Tauri desktop app.
                  <br />
                  Running in browser — no hardware data.
                </p>
              </div>
            )}
          </div>

          {/* Bottom Left: Role routing -- was 4 rows of static placeholder text
              ("Intent + questions", "Plan + DAG"...) that never reflected what
              model was actually assigned to each role. Now reads the real
              litellm_config.yaml assignments via get_role_assignments. */}
          <div className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-black/30 p-5 shadow-xl backdrop-blur-md transition-all hover:border-white/20 overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="flex items-center gap-2 text-body font-black uppercase tracking-widest text-[var(--determinex-text)]">
                <Zap size={16} className="text-emerald-400" /> Role Slots
              </h3>
              {onOpenModelSlots && (
                <button
                  type="button"
                  onClick={onOpenModelSlots}
                  className="text-eyebrow font-black uppercase tracking-widest text-gray-600 hover:text-gray-300 transition-colors"
                >
                  Edit
                </button>
              )}
            </div>
            <div className="flex flex-col gap-3 flex-1">
              {[
                {
                  label: "Oracle",
                  value: roles?.oracle,
                  sub: "Turns the user request into a project direction and specification.",
                  color: "text-emerald-400",
                },
                {
                  label: "Architect",
                  value: roles?.architect,
                  sub: "Breaks the spec into ordered work steps and verifier checkpoints.",
                  color: "text-cyan-400",
                },
                {
                  label: "Builder",
                  value: roles?.builder,
                  sub: "Writes files through the selected local, API, or hybrid model route.",
                  color: "text-violet-400",
                },
                {
                  label: "Monitor",
                  value: roles?.monitor,
                  sub: "Reads compiler/test output, retries failures, and explains blockers.",
                  color: "text-amber-400",
                },
              ].map((row) => (
                <div
                  key={row.label}
                  className="rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2.5"
                >
                  <div className="flex items-center justify-between gap-2 mb-0.5">
                    <span className="text-meta font-bold uppercase tracking-widest text-gray-500">
                      {row.label}
                    </span>
                    <span
                      className={`font-mono text-label font-black truncate max-w-[160px] ${row.value ? row.color : "text-gray-700"}`}
                    >
                      {row.value ?? "loading..."}
                    </span>
                  </div>
                  <p className="text-meta text-gray-600 font-mono">{row.sub}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Bottom Right: Live Log -- the same matrixLogs array Proof shows in
              full with real controls (session library, verdict, pipeline
              state). This was a second, unstyled copy of the same data with
              no way to act on it; a link there is more honest than a
              duplicate. */}
          <div className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-black/30 p-5 shadow-xl backdrop-blur-md transition-all hover:border-white/20 overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="flex items-center gap-2 text-body font-black uppercase tracking-widest text-[var(--determinex-text)]">
                <Terminal size={16} className="text-violet-400" /> Live Session Log
              </h3>
              <div className="flex items-center gap-2">
                {latestLogs.length > 0 && (
                  <span className="rounded-full border border-violet-500/20 bg-violet-950/30 px-2 py-0.5 font-mono text-meta text-violet-400 animate-pulse">
                    ACTIVE
                  </span>
                )}
                {onOpenProof && (
                  <button
                    type="button"
                    onClick={onOpenProof}
                    className="text-eyebrow font-black uppercase tracking-widest text-gray-600 hover:text-gray-300 transition-colors"
                  >
                    Full log in Proof
                  </button>
                )}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto no-scrollbar font-mono text-meta leading-relaxed">
              {latestLogs.length > 0 ? (
                latestLogs.map((log, i) => (
                  <div
                    key={i}
                    className={`py-0.5 truncate ${
                      log.startsWith("[ERROR]")
                        ? "text-rose-400/80"
                        : log.startsWith("[OBSERVER]")
                          ? "text-cyan-400/70"
                          : log.startsWith("[DETERMINEX]")
                            ? "text-emerald-400/70"
                            : log.startsWith("[USER]")
                              ? "text-white/60"
                              : "text-gray-600"
                    }`}
                  >
                    {log}
                  </div>
                ))
              ) : (
                <div className="flex flex-col items-center justify-center h-full gap-2 text-center opacity-50">
                  <Activity size={18} className="text-gray-700" />
                  <p className="text-gray-600">
                    No active session. Start a build from Work to watch the model route and per-step
                    reasoning here.
                    <br />
                    Start a hive run in Work.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* System Benchmarks link */}
        <a
          href="/proof-center/"
          className="group shrink-0 flex items-center justify-between rounded-2xl border border-white/8 bg-black/25 px-5 py-4 transition-all hover:border-[var(--determinex-accent)]/40 hover:bg-[var(--determinex-accent)]/5 hover:shadow-[0_0_20px_var(--determinex-accent-glow)]"
        >
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--determinex-accent)]/20 bg-[var(--determinex-accent)]/10">
              <BarChart3 size={16} className="text-[var(--determinex-accent)]" />
            </div>
            <div>
              <div className="text-meta font-black uppercase tracking-widest text-[var(--determinex-text)]">
                System Benchmarks
              </div>
              <div className="text-meta text-gray-600 font-mono mt-0.5">
                ProgramBench · SWE-bench · Model scores · Campaign timeline
              </div>
            </div>
          </div>
          <ExternalLink
            size={14}
            className="text-gray-600 group-hover:text-[var(--determinex-accent)] transition-colors shrink-0"
          />
        </a>
      </div>
    </div>
  );
}
