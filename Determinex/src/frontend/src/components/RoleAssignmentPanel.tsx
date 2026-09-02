"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Cloud,
  Cpu,
  RefreshCw,
  Save,
  Zap,
} from "lucide-react";
import {
  getOllamaModels,
  getRoleAssignments,
  RoleAssignments,
  setRoleAssignments,
} from "@/lib/api";
import {
  CLOUD_ROUTE_OPTIONS,
  FREE_CLOUD_ROUTE_OPTIONS,
  routeKeyReady,
  routeLabel,
  routeReadinessLabel,
  type AiRouteOption,
  type ApiKeyStatus,
} from "@/lib/aiRouting";

interface InstalledModel {
  id: string;
  name: string;
  size_gb: number;
  param_size: string;
  is_determinex: boolean;
}

const LOCAL_ALIASES = [
  "determinex/planner-7b",
  "determinex/planner",
  "determinex/engineer",
  "determinex/observer",
];

const ROLE_META: Record<
  keyof RoleAssignments,
  { label: string; color: string; desc: string; runsPerSession: string }
> = {
  oracle: {
    label: "Oracle Slot",
    color: "text-purple-400",
    desc: "Understands the request and turns it into structured intent",
    runsPerSession: "once",
  },
  architect: {
    label: "Architect Slot",
    color: "text-amber-400",
    desc: "Reads Oracle summary and generates the step DAG",
    runsPerSession: "once",
  },
  builder: {
    label: "Builder Slot",
    color: "text-cyan-400",
    desc: "Writes code and applies project changes",
    runsPerSession: "every step",
  },
  monitor: {
    label: "Monitor Slot",
    color: "text-emerald-400",
    desc: "Reviews output, proofs, errors, and retries",
    runsPerSession: "every step",
  },
};

function modelLabel(id: string, models: InstalledModel[]): string {
  const route = routeLabel(id);
  if (route !== id) return route;
  if (id.startsWith("determinex/")) {
    const suffix = id.replace("determinex/", "");
    const found = models.find(
      (m) => m.id.includes(suffix) || m.name.toLowerCase().includes(suffix)
    );
    if (found) return found.name;
    return id;
  }
  const bare = id.replace(/^ollama\//, "");
  const found = models.find((m) => m.id === bare || m.id === id);
  return found ? found.name : id;
}

function tierLabel(roles: RoleAssignments): { label: string; color: string; desc: string } {
  const values = Object.values(roles);
  const freeCount = values.filter((value) => value.startsWith("free/")).length;
  const cloudCount = values.filter((value) =>
    /^(cloud|openai|anthropic|gemini|deepseek|mistral|groq)\//.test(value)
  ).length;
  if (freeCount === values.length) {
    return {
      label: "Free Cloud Stack",
      color: "text-green-400",
      desc: "All roles use OpenRouter free-tier routes",
    };
  }
  if (freeCount > 0 && cloudCount === 0) {
    return {
      label: "Free + Local Stack",
      color: "text-teal-400",
      desc: "OpenRouter free routes mixed with local inference",
    };
  }
  if (cloudCount === 0) {
    return {
      label: "Local Slot Stack",
      color: "text-emerald-400",
      desc: "Fully local, no API provider required",
    };
  }
  if (cloudCount <= 2) {
    return {
      label: "Hybrid Slot Stack",
      color: "text-amber-400",
      desc: "API and local models are mixed by role",
    };
  }
  return {
    label: "API Slot Stack",
    color: "text-cyan-400",
    desc: "Cloud/API routes are selected for most roles",
  };
}

function ReadinessBadge({ id, keyStatus }: { id: string; keyStatus: ApiKeyStatus }) {
  const ready = routeKeyReady(id, keyStatus);
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-eyebrow font-black uppercase tracking-wider ${
        ready
          ? "border-emerald-500/25 bg-emerald-950/30 text-emerald-400"
          : "border-amber-500/25 bg-amber-950/25 text-amber-400"
      }`}
    >
      {routeReadinessLabel(id, keyStatus)}
    </span>
  );
}

function CloudRouteButton({
  option,
  current,
  keyStatus,
  onSelect,
}: {
  option: AiRouteOption;
  current: string;
  keyStatus: ApiKeyStatus;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full items-center justify-between px-3 py-2 text-left transition-colors ${
        option.kind === "free_cloud" ? "hover:bg-[#0f2a0f]" : "hover:bg-[var(--dtx-code-border)]"
      }`}
    >
      <div className="flex min-w-0 items-center gap-2">
        {option.kind === "free_cloud" ? (
          <Zap size={10} className="shrink-0 text-green-500" />
        ) : (
          <Cloud size={10} className="shrink-0 text-cyan-400" />
        )}
        <span
          className={`truncate text-label font-mono ${option.kind === "free_cloud" ? "text-green-200" : "text-gray-300"}`}
        >
          {option.label}
        </span>
        <span className="shrink-0 text-meta text-gray-600">{option.providerLabel}</span>
      </div>
      <div className="ml-2 flex shrink-0 items-center gap-2">
        <ReadinessBadge id={option.id} keyStatus={keyStatus} />
        {option.id === current && <CheckCircle2 size={10} className="text-emerald-400" />}
      </div>
    </button>
  );
}

export function RoleAssignmentPanel({ keyStatus = {} }: { keyStatus?: ApiKeyStatus }) {
  const [roles, setRoles] = useState<RoleAssignments | null>(null);
  const [draft, setDraft] = useState<RoleAssignments | null>(null);
  const [models, setModels] = useState<InstalledModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, m] = await Promise.all([getRoleAssignments(), getOllamaModels()]);
      setRoles(r);
      setDraft({ ...r });
      // "citadel-*" tags are this exact project's own pre-rename artifacts
      // (see lib/work-readiness.ts's alias table), installed alongside their
      // renamed "determinex-*" counterparts on boxes that haven't re-pulled
      // yet. Letting a role get assigned to one reads as if Determinex ships
      // someone else's "Citadel" product as a selectable option. Ryan:
      // "citadel models shouldnt exist... not for us."
      setModels(m.filter((model) => !model.name.toLowerCase().startsWith("citadel")));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      await setRoleAssignments(draft);
      setRoles({ ...draft });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const isDirty = draft && roles && JSON.stringify(draft) !== JSON.stringify(roles);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-10">
        <div className="h-4 w-4 animate-spin rounded-full border border-purple-500/60 border-t-purple-400" />
        <span className="text-label text-gray-500">Reading config...</span>
      </div>
    );
  }

  if (error && !draft) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-red-800/40 bg-red-950/30 p-4">
        <AlertTriangle size={14} className="shrink-0 text-red-400" />
        <p className="text-label text-red-300">{error}</p>
      </div>
    );
  }

  const tier = draft ? tierLabel(draft) : null;

  return (
    <div className="flex flex-col gap-4">
      {tier && (
        <div className="flex items-center gap-2 rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] px-3 py-2">
          <Cpu size={12} className={tier.color} />
          <span className={`text-meta font-bold uppercase tracking-widest ${tier.color}`}>
            {tier.label}
          </span>
          <span className="ml-1 text-label text-gray-600">{tier.desc}</span>
        </div>
      )}

      {draft &&
        (Object.keys(ROLE_META) as (keyof RoleAssignments)[]).map((role) => {
          const meta = ROLE_META[role];
          const current = draft[role];
          const isOpen = openDropdown === role;

          return (
            <div key={role} className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <div>
                  <span className={`text-label font-bold ${meta.color}`}>{meta.label}</span>
                  <span className="ml-2 text-label text-gray-600">{meta.desc}</span>
                </div>
                <span className="text-eyebrow uppercase tracking-wider text-gray-700">
                  {meta.runsPerSession}
                </span>
              </div>

              <div className="relative">
                <button
                  type="button"
                  onClick={() => setOpenDropdown(isOpen ? null : role)}
                  className="flex w-full items-center justify-between rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg-deep)] px-3 py-2 text-left transition-colors hover:border-[#484f58]"
                >
                  <span className="truncate font-mono text-label text-gray-300">
                    {modelLabel(current, models)}
                  </span>
                  <div className="ml-2 flex shrink-0 items-center gap-2">
                    <ReadinessBadge id={current} keyStatus={keyStatus} />
                    <ChevronDown
                      size={11}
                      className={`text-gray-600 transition-transform ${isOpen ? "rotate-180" : ""}`}
                    />
                  </div>
                </button>

                {isOpen && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setOpenDropdown(null)} />
                    <div className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] shadow-2xl">
                      <div className="border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-3 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-600">
                        Local slots
                      </div>
                      <div className="max-h-44 overflow-y-auto">
                        {models.map((m) => (
                          <button
                            key={m.id}
                            type="button"
                            onClick={() => {
                              setDraft((d) => (d ? { ...d, [role]: `ollama/${m.id}` } : d));
                              setOpenDropdown(null);
                            }}
                            className="flex w-full items-center justify-between px-3 py-2 text-left transition-colors hover:bg-[var(--dtx-code-border)]"
                          >
                            <div className="flex min-w-0 items-center gap-2">
                              <Cpu
                                size={10}
                                className={
                                  m.is_determinex
                                    ? "shrink-0 text-emerald-400"
                                    : "shrink-0 text-gray-600"
                                }
                              />
                              <span className="truncate font-mono text-label text-gray-300">
                                {m.id}
                              </span>
                            </div>
                            <div className="ml-2 flex shrink-0 items-center gap-2">
                              <span className="text-meta text-gray-600">
                                {m.size_gb.toFixed(1)}GB
                              </span>
                              {(`ollama/${m.id}` === current || m.id === current) && (
                                <CheckCircle2 size={10} className="text-emerald-400" />
                              )}
                            </div>
                          </button>
                        ))}
                        {LOCAL_ALIASES.map((alias) => (
                          <button
                            key={alias}
                            type="button"
                            onClick={() => {
                              setDraft((d) => (d ? { ...d, [role]: alias } : d));
                              setOpenDropdown(null);
                            }}
                            className="flex w-full items-center justify-between px-3 py-2 text-left transition-colors hover:bg-[var(--dtx-code-border)]"
                          >
                            <div className="flex items-center gap-2">
                              <Cpu size={10} className="shrink-0 text-purple-400" />
                              <span className="font-mono text-label text-purple-300">{alias}</span>
                              <span className="text-meta text-gray-700">alias</span>
                            </div>
                            {alias === current && (
                              <CheckCircle2 size={10} className="text-emerald-400" />
                            )}
                          </button>
                        ))}
                      </div>

                      <div className="border-y border-[var(--dtx-code-border)] bg-[#0a1a0a] px-3 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-green-700">
                        <span className="flex items-center gap-1.5">
                          <Zap size={9} className="text-green-500" />
                          Free OpenRouter routes
                        </span>
                      </div>
                      {FREE_CLOUD_ROUTE_OPTIONS.map((option) => (
                        <CloudRouteButton
                          key={option.id}
                          option={option}
                          current={current}
                          keyStatus={keyStatus}
                          onSelect={() => {
                            setDraft((d) => (d ? { ...d, [role]: option.id } : d));
                            setOpenDropdown(null);
                          }}
                        />
                      ))}

                      <div className="border-y border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-3 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-600">
                        Paid API routes
                      </div>
                      {CLOUD_ROUTE_OPTIONS.map((option) => (
                        <CloudRouteButton
                          key={option.id}
                          option={option}
                          current={current}
                          keyStatus={keyStatus}
                          onSelect={() => {
                            setDraft((d) => (d ? { ...d, [role]: option.id } : d));
                            setOpenDropdown(null);
                          }}
                        />
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          );
        })}

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-800/40 bg-red-950/30 px-3 py-2">
          <AlertTriangle size={12} className="shrink-0 text-red-400" />
          <p className="break-all text-label text-red-300">{error}</p>
        </div>
      )}

      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={() => void load()}
          className="flex items-center gap-1.5 text-label text-gray-600 transition-colors hover:text-gray-400"
        >
          <RefreshCw size={10} />
          Reload from config
        </button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={!isDirty || saving}
          className={`flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-label font-bold transition-all ${
            saved
              ? "border border-emerald-700/40 bg-emerald-900/40 text-emerald-400"
              : isDirty
                ? "bg-cyan-600 text-white shadow-[0_0_12px_rgba(0,229,255,0.2)] hover:bg-cyan-500"
                : "cursor-not-allowed border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] text-gray-600"
          }`}
        >
          {saving ? (
            <>
              <div className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />
              Saving...
            </>
          ) : saved ? (
            <>
              <CheckCircle2 size={11} /> Saved
            </>
          ) : (
            <>
              <Save size={11} /> Save Slots
            </>
          )}
        </button>
      </div>

      <p className="text-meta leading-relaxed text-gray-700">
        Slot changes take effect on the next build session. Restart is not required. Config saved to{" "}
        <span className="font-mono">litellm_config.yaml</span>.
      </p>
    </div>
  );
}
