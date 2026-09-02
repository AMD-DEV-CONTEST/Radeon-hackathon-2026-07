"use client";
import {
  Settings,
  KeyRound,
  Network,
  Activity,
  Check,
  Lock,
  Unlock,
  ShieldCheck,
  Zap,
  CircleDot,
  Eye,
  EyeOff,
  ChevronRight,
  ShieldAlert,
  Palette,
  Server,
  Cpu,
  Bot,
  RotateCcw,
} from "lucide-react";
import { useEffect, useState } from "react";
import { RoleAssignmentPanel } from "@/components/RoleAssignmentPanel";
import { SkinPickerInline } from "@/components/ThemeSelector";
import { saveApiKeys } from "@/lib/api";
import { useSettings } from "@/contexts/SettingsContext";
import { useErrorToast } from "@/components/ErrorToast";
import { getOllamaModels } from "@/lib/api";
import { RuntimeCapabilityCard } from "@/components/RuntimeCapabilityCard";
import {
  NETWORK_POLICY_COPY,
  requestSetupRerun,
  type NetworkPolicyMode,
} from "@/lib/networkPolicy";

const PROVIDER_TOOL_MAP: Record<string, string[]> = {
  openai: ["GPT-4o reasoning", "Embeddings", "Whisper transcription", "DALL·E generation"],
  anthropic: ["Claude Architect (primary)", "Claude opus chain", "Hive strategy layer"],
  gemini: ["Gemini Planner", "Gemini Flash review", "Multimodal context"],
  groq: ["Groq LLaMA turbo", "Ultra-fast inference burst"],
  deepseek: ["DeepSeek Coder", "DeepSeek Chat"],
  mistral: ["Mistral Large", "Codestral"],
  openrouter: ["Free-tier model routes", "Multi-vendor fallback"],
  kimi: ["Kimi K2", "Long-context reasoning"],
};

export function SettingsModal() {
  const showError = useErrorToast();
  const {
    showSettings,
    setShowSettings,
    settingsTab,
    setSettingsTab,
    keyStatus,
    apiKeys,
    setApiKeys,
    ollamaBaseUrl,
    setOllamaBaseUrl,
    saveOllamaEndpoint,
    diagnosticResult,
    isDiagnosing,
    runDiagnostics,
    networkPolicy,
    setNetworkPolicy,
  } = useSettings();
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [ollamaModels, setOllamaModels] = useState<
    { id: string; name: string; size_gb: number; param_size: string; is_determinex: boolean }[]
  >([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [hasFetchedModels, setHasFetchedModels] = useState(false);
  // "citadel-*" tags are pre-rename artifacts of this exact project's own
  // models (see lib/work-readiness.ts's alias table) -- installed alongside
  // their renamed "determinex-*" counterparts on dev boxes that haven't
  // re-pulled yet. Showing them here reads as if Determinex ships someone
  // else's "Citadel" product. Ryan: "citadel models shouldnt exist... not
  // for us." Filtered from display only -- the backend list (and the
  // alias-matching in work-readiness.ts) is untouched, so role-readiness
  // detection still works on boxes that only have the legacy tag.
  const visibleOllamaModels = ollamaModels.filter(
    (m) => !m.name.toLowerCase().startsWith("citadel")
  );

  // Fetch models once when the AI Engine tab is opened. Previously this ran
  // unconditionally during render guarded only by `ollamaModels.length === 0` --
  // a legitimately empty result (no Ollama installed, a normal case) never
  // flips that guard, so it re-fired every render forever, alternating the
  // loading flag too fast for "No local models found" to ever be visible.
  // Found live: the tab was stuck on "Scanning local registry..." indefinitely.
  useEffect(() => {
    if (settingsTab !== "diagnostics" || hasFetchedModels) return;
    setIsLoadingModels(true);
    setHasFetchedModels(true);
    getOllamaModels().then((models) => {
      setOllamaModels(models);
      setIsLoadingModels(false);
    });
  }, [settingsTab, hasFetchedModels]);

  // Escape closes it -- the other half of the accessibility item, where the
  // drawer got Escape and the modals did not, so the only way out of Settings was
  // to find its close button.
  //
  // Declared ABOVE the early return on purpose. The first version of this sat
  // below it, which is a rules-of-hooks violation: hook order changes the moment
  // `showSettings` flips, React throws, and the modal never renders at all. The
  // e2e spec caught it as "settings opened nothing".
  useEffect(() => {
    if (!showSettings) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowSettings(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [showSettings, setShowSettings]);

  if (!showSettings) return null;

  const onClose = () => setShowSettings(false);

  const toggleShowKey = (provider: string) =>
    setShowKeys((p) => ({ ...p, [provider]: !p[provider] }));

  return (
    <div
      data-testid="settings-modal"
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
      className="absolute inset-0 z-50 flex items-center justify-center p-6 backdrop-blur-md"
      style={{ background: "rgba(0,0,0,0.85)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-4xl flex h-[80vh] animate-in zoom-in-95 duration-300 overflow-hidden"
        style={{
          background: "var(--determinex-panel-glass)",
          border: "1px solid var(--determinex-border)",
          borderRadius: "var(--determinex-radius)",
          boxShadow: "var(--determinex-shell-shadow)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Sidebar Tabs */}
        <div className="w-64 border-r border-white/10 bg-black/40 flex flex-col shrink-0">
          <div className="p-6 border-b border-white/10">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/10 mb-4 shadow-[0_0_15px_var(--determinex-accent-glow)]">
              <Settings size={20} className="text-[var(--determinex-accent)]" />
            </div>
            <h2
              className="text-lg font-black tracking-tight text-white uppercase"
              style={{ fontFamily: "var(--determinex-font-display)" }}
            >
              Config Vault
            </h2>
            <p className="text-meta uppercase tracking-widest text-gray-500 mt-1">
              System Settings
            </p>
          </div>

          <div className="flex flex-col gap-2 p-4 flex-1">
            {(
              [
                { id: "keys", label: "API Keys", icon: <KeyRound size={16} /> },
                { id: "roles", label: "Hive Roles", icon: <Network size={16} /> },
                { id: "network", label: "Network", icon: <Unlock size={16} /> },
                { id: "diagnostics", label: "AI Engine", icon: <Server size={16} /> },
                { id: "skin", label: "Skin Pack", icon: <Palette size={16} /> },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                onClick={() => setSettingsTab(tab.id)}
                className={`flex items-center justify-between w-full p-3 rounded-xl transition-all ${
                  settingsTab === tab.id
                    ? "bg-[var(--determinex-accent)]/10 border border-[var(--determinex-accent)]/30 text-white shadow-[0_0_15px_var(--determinex-accent-glow)]"
                    : "border border-transparent text-gray-500 hover:text-gray-300 hover:bg-white/5"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`${settingsTab === tab.id ? "text-[var(--determinex-accent)]" : "text-gray-500"}`}
                  >
                    {tab.icon}
                  </div>
                  <span className="text-body font-bold uppercase tracking-wider">{tab.label}</span>
                </div>
                {settingsTab === tab.id && (
                  <ChevronRight size={14} className="text-[var(--determinex-accent)]" />
                )}
              </button>
            ))}
          </div>

          <div className="p-4 border-t border-white/10">
            <button
              onClick={onClose}
              className="w-full p-3 rounded-xl text-xs font-bold uppercase tracking-widest text-gray-500 border border-white/5 bg-white/[0.02] hover:bg-white/10 hover:text-white transition-colors"
            >
              Close Config
            </button>
          </div>
        </div>

        {/* Main Content Area */}
        <div className="flex-1 flex flex-col bg-black/20 relative">
          <div className="flex-1 overflow-y-auto p-8 no-scrollbar">
            {settingsTab === "keys" && (
              <div className="max-w-2xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-xl font-black text-white">API Keys</h3>
                    <p className="text-label text-gray-400 mt-2 leading-relaxed">
                      Keys are stored locally in this device&apos;s app database — never sent to
                      external servers. Connect providers to unlock capabilities.
                    </p>
                  </div>
                  <ShieldCheck size={32} className="text-emerald-400 opacity-80" />
                </div>

                <div className="grid gap-4">
                  {(
                    [
                      "openai",
                      "anthropic",
                      "gemini",
                      "groq",
                      "deepseek",
                      "mistral",
                      "openrouter",
                      "kimi",
                    ] as const
                  ).map((provider) => (
                    <div
                      key={provider}
                      className={`rounded-2xl border p-5 transition-all ${
                        keyStatus[provider]
                          ? "border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/5"
                          : "border-white/10 bg-black/40"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-3">
                          <div
                            className={`p-2 rounded-lg border ${
                              keyStatus[provider]
                                ? "border-[var(--determinex-accent)]/50 bg-[var(--determinex-accent)]/20 text-[var(--determinex-accent)]"
                                : "border-white/10 bg-white/5 text-gray-500"
                            }`}
                          >
                            <KeyRound size={16} />
                          </div>
                          <span className="text-body font-bold uppercase tracking-widest text-white capitalize">
                            {provider}
                          </span>
                        </div>
                        {keyStatus[provider] && (
                          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-950/40 text-emerald-400 text-meta font-black uppercase tracking-widest">
                            <Check size={12} /> Connected
                          </div>
                        )}
                      </div>

                      <div className="relative">
                        <input
                          type={showKeys[provider] ? "text" : "password"}
                          placeholder={
                            keyStatus[provider] ? "••••••••••••..." : "Paste API Key here..."
                          }
                          value={apiKeys[`${provider}_key` as keyof typeof apiKeys]}
                          onChange={(e) =>
                            setApiKeys({ ...apiKeys, [`${provider}_key`]: e.target.value })
                          }
                          className={`w-full rounded-xl border bg-black/60 px-4 py-3 pr-10 text-sm text-[var(--determinex-text)] outline-none transition-all placeholder:text-[var(--determinex-muted)] focus:shadow-[0_0_15px_var(--determinex-accent-glow)] ${
                            keyStatus[provider]
                              ? "border-[var(--determinex-accent)]/50 focus:border-[var(--determinex-accent)]"
                              : "border-white/10 focus:border-[var(--determinex-accent)]/50"
                          }`}
                        />
                        <button
                          type="button"
                          onClick={() => toggleShowKey(provider)}
                          className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-500 hover:text-[var(--determinex-accent)] transition-colors"
                        >
                          {showKeys[provider] ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>

                      {keyStatus[provider] && (
                        <div className="mt-4 pt-4 border-t border-white/10 flex flex-wrap gap-2">
                          {PROVIDER_TOOL_MAP[provider].map((tool) => (
                            <span
                              key={tool}
                              className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/10 text-meta text-gray-400"
                            >
                              <CircleDot size={8} className="text-emerald-400" /> {tool}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <div className="rounded-2xl border border-white/10 bg-black/40 p-5">
                  <div className="text-label font-bold text-white/85 mb-1">Ollama Endpoint</div>
                  <p className="text-label text-gray-500 mb-3">
                    Local by default. Override if Ollama runs on a different host/port.
                  </p>
                  <input
                    type="text"
                    value={ollamaBaseUrl}
                    onChange={(e) => setOllamaBaseUrl(e.target.value)}
                    placeholder="http://localhost:11434"
                    className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs font-mono text-gray-300 focus:outline-none focus:border-[var(--determinex-accent)]/50"
                  />
                </div>

                <div className="flex justify-end pt-4">
                  <button
                    onClick={async () => {
                      try {
                        await saveApiKeys(apiKeys);
                        await saveOllamaEndpoint(ollamaBaseUrl);
                        onClose();
                      } catch (e) {
                        showError(`Failed to save API keys: ${e}`);
                      }
                    }}
                    className="flex items-center gap-2 px-6 py-3 rounded-xl text-xs font-black uppercase tracking-widest text-black transition-all hover:shadow-[0_0_20px_var(--determinex-accent-glow)] hover:scale-[1.02]"
                    style={{ background: "var(--determinex-accent)" }}
                  >
                    <Lock size={14} /> Seal Vault
                  </button>
                </div>
              </div>
            )}

            {settingsTab === "roles" && (
              <div className="max-w-2xl mx-auto animate-in fade-in slide-in-from-bottom-4">
                <div className="mb-8">
                  <h3 className="text-xl font-black text-white">Hive Role Assignment</h3>
                  <p className="text-label text-gray-400 mt-2 leading-relaxed">
                    Map specific models to architectural roles in the Hive.
                  </p>
                </div>
                <RoleAssignmentPanel keyStatus={keyStatus} />
              </div>
            )}

            {settingsTab === "network" && (
              <div className="max-w-2xl mx-auto animate-in fade-in slide-in-from-bottom-4 pb-12">
                <div className="flex items-start justify-between mb-8">
                  <div>
                    <h3 className="text-xl font-black text-white">Network Policy</h3>
                    <p className="text-label text-gray-400 mt-2 leading-relaxed">
                      Decide when Determinex may use internet-backed IDE features. ProgramBench and
                      hardened benchmark runners stay network-denied regardless of this setting.
                    </p>
                  </div>
                  <div className="rounded-full border border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/10 px-3 py-1.5 text-eyebrow font-black uppercase tracking-widest text-[var(--determinex-accent)]">
                    {NETWORK_POLICY_COPY[networkPolicy].badge}
                  </div>
                </div>

                <div className="grid gap-4">
                  {(["offline", "cloaked", "online"] as NetworkPolicyMode[]).map((mode) => {
                    const copy = NETWORK_POLICY_COPY[mode];
                    const active = networkPolicy === mode;
                    return (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => setNetworkPolicy(mode)}
                        className={`rounded-2xl border p-5 text-left transition-all ${
                          active
                            ? "border-[var(--determinex-accent)]/50 bg-[var(--determinex-accent)]/10 shadow-[0_0_18px_var(--determinex-accent-glow)]"
                            : "border-white/10 bg-black/40 hover:border-[var(--determinex-accent)]/35"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-4">
                          <div className="flex items-center gap-3">
                            <div
                              className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
                                active
                                  ? "border-[var(--determinex-accent)]/50 bg-[var(--determinex-accent)]/20 text-[var(--determinex-accent)]"
                                  : "border-white/10 bg-white/5 text-gray-500"
                              }`}
                            >
                              {mode === "offline" ? (
                                <Lock size={16} />
                              ) : mode === "cloaked" ? (
                                <ShieldCheck size={16} />
                              ) : (
                                <Unlock size={16} />
                              )}
                            </div>
                            <div>
                              <div className="text-body font-black uppercase tracking-widest text-white">
                                {copy.label}
                              </div>
                              <div className="mt-1 text-label text-gray-500">{copy.summary}</div>
                            </div>
                          </div>
                          {active && (
                            <span className="rounded-full border border-emerald-500/30 bg-emerald-950/30 px-3 py-1 text-eyebrow font-black uppercase tracking-widest text-emerald-400">
                              Active
                            </span>
                          )}
                        </div>
                        <p className="mt-4 text-label leading-relaxed text-gray-400">
                          {copy.detail}
                        </p>
                      </button>
                    );
                  })}
                </div>

                <div className="mt-6 rounded-2xl border border-amber-500/25 bg-amber-950/20 p-5">
                  <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-amber-400">
                    <ShieldAlert size={14} /> Benchmark Isolation
                  </div>
                  <p className="mt-3 text-label leading-relaxed text-gray-400">
                    ProgramBench, official evals, and proof sandboxes must stay offline unless a
                    benchmark explicitly permits network. This IDE policy controls user-facing
                    tools, provider calls, docs, connectors, and project work.
                  </p>
                </div>
              </div>
            )}

            {settingsTab === "skin" && (
              <div className="max-w-2xl mx-auto animate-in fade-in slide-in-from-bottom-4">
                <div className="flex items-start justify-between mb-6">
                  <div>
                    <h3 className="text-xl font-black text-white">Visual Skin Pack</h3>
                    <p className="text-label text-gray-400 mt-2 leading-relaxed">
                      Choose a skin to apply across the entire IDE — colors, typography, and ambient
                      rain.
                    </p>
                  </div>
                  <Palette size={28} className="text-[var(--determinex-accent)] opacity-70" />
                </div>
                <SkinPickerInline />
              </div>
            )}

            {settingsTab === "diagnostics" && (
              <div className="max-w-2xl mx-auto animate-in fade-in slide-in-from-bottom-4 pb-12">
                <div className="flex items-start justify-between mb-8">
                  <div>
                    <h3 className="text-xl font-black text-white flex items-center gap-3">
                      <Server className="text-amber-400" /> AI Engine & Diagnostics
                    </h3>
                    <p className="text-label text-gray-400 mt-2 leading-relaxed">
                      Probe Ollama, models registry, and local AI Engine status.
                    </p>
                  </div>
                  <button
                    onClick={runDiagnostics}
                    disabled={isDiagnosing}
                    className="px-5 py-2.5 rounded-xl border border-amber-500/30 bg-amber-950/40 text-amber-400 text-meta uppercase tracking-widest font-black disabled:opacity-50 transition-all hover:bg-amber-900/40 hover:shadow-[0_0_15px_rgba(251,191,36,0.3)] flex items-center gap-2"
                  >
                    {isDiagnosing ? (
                      <Zap size={14} className="animate-pulse" />
                    ) : (
                      <Activity size={14} />
                    )}
                    {isDiagnosing ? "Probing System..." : "Run Diagnostics"}
                  </button>
                </div>

                {/* Measured hardware + real usage. Sits above Setup Repair because "what is this
                    machine" is the first question this tab exists to answer, and until 2026-07-30
                    nothing answered it: detection was nvidia-smi only, so AMD and Apple rigs
                    reported CPU-only and ran at the lowest tier. */}
                <RuntimeCapabilityCard />

                <div className="mb-8 mt-6 rounded-2xl border border-indigo-500/25 bg-indigo-950/20 p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-indigo-300">
                        <RotateCcw size={14} /> Setup Repair
                      </div>
                      <p className="mt-3 text-label leading-relaxed text-gray-400">
                        Reopen the first-run setup when API keys, local models, hardware detection,
                        or Local/Cloak policy need to be fixed after install.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        requestSetupRerun();
                        onClose();
                      }}
                      data-testid="settings-rerun-setup"
                      className="shrink-0 rounded-xl border border-indigo-400/30 bg-indigo-500/10 px-4 py-2 text-meta font-black uppercase tracking-widest text-indigo-200 transition-all hover:bg-indigo-500/20"
                    >
                      Run Setup
                    </button>
                  </div>
                </div>

                {diagnosticResult && (
                  <div className="rounded-2xl border border-amber-500/30 bg-black/60 p-6 font-mono text-label flex flex-col gap-3 shadow-[0_0_30px_rgba(0,0,0,0.5)]">
                    {diagnosticResult.map((line, i) => (
                      <div
                        key={i}
                        className={`flex items-center gap-3 p-3 rounded-xl border ${
                          line.startsWith("✓")
                            ? "border-emerald-500/20 bg-emerald-950/20 text-emerald-400"
                            : line.startsWith("✗")
                              ? "border-red-500/20 bg-red-950/20 text-red-400 font-bold"
                              : "border-white/5 bg-white/5 text-gray-400"
                        }`}
                      >
                        {line.startsWith("✓") ? (
                          <Check size={14} className="shrink-0" />
                        ) : line.startsWith("✗") ? (
                          <ShieldAlert size={14} className="shrink-0" />
                        ) : (
                          <CircleDot size={14} className="shrink-0" />
                        )}
                        {line.replace(/^✓\s*|^✗\s*/, "")}
                      </div>
                    ))}
                  </div>
                )}

                <div className="mt-8 mb-4">
                  <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-1 flex items-center gap-2">
                    <Cpu size={14} className="text-[var(--determinex-accent)]" /> Local Models
                    (Ollama)
                  </h4>
                  <p className="text-label text-gray-500 mb-4">
                    Models pulled and available for offline inference.
                  </p>
                  {isLoadingModels ? (
                    <div className="text-xs text-gray-500 animate-pulse">
                      Scanning local registry...
                    </div>
                  ) : visibleOllamaModels.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {visibleOllamaModels.map((m) => (
                        <div
                          key={m.id}
                          className="p-3 rounded-xl border border-white/10 bg-black/40 flex items-start gap-3"
                        >
                          <div className="p-2 rounded-lg bg-[var(--determinex-accent)]/10 text-[var(--determinex-accent)]">
                            <Bot size={16} />
                          </div>
                          <div>
                            <div className="text-xs font-bold text-white mb-0.5">{m.name}</div>
                            <div className="text-eyebrow uppercase tracking-widest text-gray-500 flex gap-2">
                              <span>{m.size_gb} GB</span>
                              <span>•</span>
                              <span>{m.param_size}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-4 rounded-xl border border-white/5 bg-white/5 text-xs text-gray-400">
                      No local models found. Is Ollama running?
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
