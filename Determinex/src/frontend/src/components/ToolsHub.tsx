"use client";
import { useEffect, useState } from "react";
import {
  Bot,
  Code2,
  ExternalLink,
  Gauge,
  GitBranch,
  GraduationCap,
  HardDrive,
  LayoutGrid,
  Package,
  Blocks,
  Cloud,
  Plus,
  Search,
  ShieldCheck,
  Terminal,
  Trash2,
  Wrench,
} from "lucide-react";
import { MarketplacePanel } from "./MarketplacePanel";
import { ToolsRegistry } from "./ToolsRegistry";
import { useSettings } from "@/contexts/SettingsContext";
import { NETWORK_POLICY_COPY } from "@/lib/networkPolicy";
import { checkOllamaStatus } from "@/lib/api";

// The "rolodex": every provider Determinex can route to, grouped by what actually
// matters when picking one -- where it runs, what it costs, and whether your data
// leaves this machine. Deliberately NOT a flat list of brand names with identical
// "Slotable" badges (the previous version) -- a new user has no way to tell "which
// AI system do I use" from that. keyField maps to the real key vault (keyStatus,
// populated by getApiKeyStatus()) so "Connected" is a real, live fact, not decoration.
type ProviderClass = "local" | "free" | "cheap" | "frontier";

const CLASS_COPY: Record<ProviderClass, { label: string; badge: string; color: string }> = {
  local: { label: "Local / On-device", badge: "FREE · PRIVATE", color: "var(--dtx-ok)" },
  free: { label: "Free-tier Cloud API", badge: "FREE TIER", color: "var(--dtx-info)" },
  cheap: { label: "Cheap Cloud API", badge: "LOW COST", color: "var(--dtx-info)" },
  frontier: {
    label: "Frontier Cloud API",
    badge: "PAID · HIGHEST QUALITY",
    color: "var(--dtx-warn)",
  },
};

type ProviderEntry = {
  key: string;
  name: string;
  cls: ProviderClass;
  detail: string;
  privacy: string;
  keyField: string | null; // maps into keyStatus; null = checked a different way (Ollama)
  getKeyUrl?: string; // official provider console page to obtain an API key
};

const PROVIDER_ROLODEX: ProviderEntry[] = [
  {
    key: "ollama",
    name: "Ollama Local",
    cls: "local",
    detail:
      "Offline builder/observer/fallback models. Needs local GPU/VRAM; nothing is sent anywhere.",
    privacy: "Never leaves this machine",
    keyField: null,
  },
  {
    key: "groq",
    name: "Groq",
    cls: "free",
    detail: "Free-tier, ultra-fast inference burst for latency-sensitive steps.",
    privacy: "Leaves the machine (API call)",
    keyField: "groq",
    getKeyUrl: "https://console.groq.com/keys",
  },
  {
    key: "openrouter",
    name: "OpenRouter",
    cls: "free",
    detail: "Multi-vendor router; several free-tier models available alongside metered ones.",
    privacy: "Leaves the machine (routed)",
    keyField: "openrouter",
    getKeyUrl: "https://openrouter.ai/keys",
  },
  {
    key: "deepseek",
    name: "DeepSeek",
    cls: "cheap",
    detail: "Low-cost coding/chat models with strong price-to-capability for a builder role.",
    privacy: "Leaves the machine (API call)",
    keyField: "deepseek",
    getKeyUrl: "https://platform.deepseek.com/api_keys",
  },
  {
    key: "gemini",
    name: "Gemini",
    cls: "cheap",
    detail: "Fast multimodal review, screenshots, and broad context passes; has a free quota.",
    privacy: "Leaves the machine (API call)",
    keyField: "gemini",
    getKeyUrl: "https://aistudio.google.com/apikey",
  },
  {
    key: "mistral",
    name: "Mistral",
    cls: "cheap",
    detail: "Mistral Large + Codestral, code-focused, mid-cost per token.",
    privacy: "Leaves the machine (API call)",
    keyField: "mistral",
    getKeyUrl: "https://console.mistral.ai/api-keys/",
  },
  {
    key: "anthropic",
    name: "Claude",
    cls: "frontier",
    detail: "Long-context planning, architecture review, and implementation critique.",
    privacy: "Leaves the machine (API call)",
    keyField: "anthropic",
    getKeyUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    key: "openai",
    name: "OpenAI (GPT / Codex)",
    cls: "frontier",
    detail: "Hosted reasoning, embeddings, structured tools, and code review/generation.",
    privacy: "Leaves the machine (API call)",
    keyField: "openai",
    getKeyUrl: "https://platform.openai.com/api-keys",
  },
];

type CustomProvider = {
  id: string;
  name: string;
  url: string;
  apiKey: string;
  color: string;
};

const CUSTOM_PROVIDERS_STORAGE_KEY = "determinex-custom-providers";
const CUSTOM_PROVIDER_COLORS = [
  "var(--dtx-alt)",
  "var(--dtx-alt)",
  "var(--dtx-info)",
  "var(--dtx-ok)",
  "var(--dtx-warn)",
  "#fb7185",
  "var(--dtx-alt-2)",
  "#facc15",
];

function loadCustomProviders(): CustomProvider[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CUSTOM_PROVIDERS_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as CustomProvider[]) : [];
  } catch {
    return [];
  }
}

function saveCustomProviders(providers: CustomProvider[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CUSTOM_PROVIDERS_STORAGE_KEY, JSON.stringify(providers));
}

// save_service_key's Rust whitelist only recognizes deepseek/mistral/openrouter
// (plus non-model services like github/slack/figma) -- openai/anthropic/gemini/groq
// are saved through the bulk saveApiKeys() call in SettingsModal's "keys" tab instead.
const BULK_KEY_VAULT_PROVIDERS = new Set(["openai", "anthropic", "gemini", "groq"]);

type Tab = "workspace" | "providers" | "installed" | "browse";

type Props = {
  toolCatalog: any;
  toolCoverage: any;
  onShowServiceLogin: (id: string) => void;
  onLaunchTool: (
    id: "terminal" | "editor" | "build" | "trace" | "search" | "health" | "mission" | "roadmap"
  ) => void;
  activeTool?: string | null;
  onOpenBrain?: () => void;
};

const TABS: { id: Tab; label: string; icon: typeof Package; desc: string }[] = [
  {
    id: "workspace",
    label: "Workspace Tools",
    icon: Wrench,
    desc: "Attach IDE tools to the active screen",
  },
  {
    id: "providers",
    label: "AI Providers",
    icon: Bot,
    desc: "Route Codex, Claude, Gemini, OpenAI, Ollama, and hybrids",
  },
  { id: "installed", label: "Installed", icon: Blocks, desc: "Active tools and integrations" },
  { id: "browse", label: "Browse", icon: Package, desc: "Discover and install extensions" },
];

export function ToolsHub({
  toolCatalog,
  toolCoverage,
  onShowServiceLogin,
  onLaunchTool,
  activeTool,
  onOpenBrain,
}: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("workspace");
  const { networkPolicy, setSettingsTab, setShowSettings, keyStatus } = useSettings();
  const networkCopy = NETWORK_POLICY_COPY[networkPolicy];

  const [ollamaOnline, setOllamaOnline] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    checkOllamaStatus().then((status) => {
      if (!cancelled) setOllamaOnline(Boolean(status?.ok));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // "Add your own provider" -- Ryan: "add your own with link and api and
  // setup for color of it." Persisted client-side (localStorage) so it
  // survives reloads. Note this makes the provider visible and rememberable
  // in the rolodex; wiring a brand-new user-defined provider into the actual
  // role-assignment/routing backend is a separate, bigger task than this UI.
  const [customProviders, setCustomProviders] = useState<CustomProvider[]>([]);
  useEffect(() => {
    setCustomProviders(loadCustomProviders());
  }, []);
  const [addingCustom, setAddingCustom] = useState(false);
  const [customDraft, setCustomDraft] = useState({
    name: "",
    url: "",
    apiKey: "",
    color: CUSTOM_PROVIDER_COLORS[0],
  });

  const addCustomProvider = () => {
    if (!customDraft.name.trim()) return;
    const next: CustomProvider[] = [
      ...customProviders,
      {
        id: `custom-${Date.now()}`,
        name: customDraft.name.trim(),
        url: customDraft.url.trim(),
        apiKey: customDraft.apiKey.trim(),
        color: customDraft.color,
      },
    ];
    setCustomProviders(next);
    saveCustomProviders(next);
    setCustomDraft({ name: "", url: "", apiKey: "", color: CUSTOM_PROVIDER_COLORS[0] });
    setAddingCustom(false);
  };

  const removeCustomProvider = (id: string) => {
    const next = customProviders.filter((p) => p.id !== id);
    setCustomProviders(next);
    saveCustomProviders(next);
  };

  // The backend's static tool registry has no visibility into the real API
  // key vault (registry.rs hardcodes "needs_key" for every key-gated tool),
  // so a tool whose key the user HAS already saved in Settings would show
  // "Connect Service" forever. Only OPENAI_API_KEY has a real counterpart in
  // ApiKeyStatus today -- the rest (GITHUB_TOKEN, LINEAR_API_KEY, etc.) have
  // no storage anywhere in the app yet, so "needs_key" stays honest for them.
  const REQUIRES_TO_KEY_STATUS: Record<string, keyof typeof keyStatus> = {
    OPENAI_API_KEY: "openai",
  };
  const liveToolCatalog = Array.isArray(toolCatalog)
    ? toolCatalog.map((tool) => {
        const mappedKey = tool?.requires ? REQUIRES_TO_KEY_STATUS[tool.requires] : undefined;
        if (mappedKey && keyStatus[mappedKey]) {
          return { ...tool, status: "online" };
        }
        return tool;
      })
    : toolCatalog;
  const workspaceTools = [
    {
      id: "terminal" as const,
      name: "Terminal",
      icon: Terminal,
      detail:
        "Run commands beside Work, Space, Brain, or Proof instead of opening a separate page.",
    },
    {
      id: "editor" as const,
      name: "Code",
      icon: Code2,
      detail:
        "Inspect files, generated output, and diffs while staying in the current project screen.",
    },
    {
      id: "build" as const,
      name: "Build",
      icon: Gauge,
      detail: "Watch tasks, tests, problems, artifacts, dependencies, and environment checks.",
    },
    {
      id: "trace" as const,
      name: "Trace",
      icon: GitBranch,
      detail: "Replay worker events, WAL records, retries, and handoff history.",
    },
    {
      id: "search" as const,
      name: "Search",
      icon: Search,
      detail: "Search project context and verified snippets from the active workspace.",
    },
    {
      id: "health" as const,
      name: "Health",
      icon: LayoutGrid,
      detail: "View oracle health, file readiness, and scan results for the selected project.",
    },
    {
      id: "mission" as const,
      name: "Mission",
      icon: GraduationCap,
      detail:
        "Open the interactive guide with current release gates, runbooks, and proof boundaries.",
    },
    {
      id: "roadmap" as const,
      name: "Roadmap",
      icon: ShieldCheck,
      detail: "Open the Determinex successor roadmap, exact blockers, and release-lock contract.",
    },
  ];

  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden"
      style={{ background: "var(--determinex-bg)" }}
    >
      {/* Tab bar */}
      <div
        className="flex shrink-0 items-center gap-1 border-b px-4 pt-3"
        style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.3)" }}
      >
        {TABS.map(({ id, label, icon: Icon, desc }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            title={desc}
            className={`flex items-center gap-2 rounded-t-xl border-b-2 px-4 py-2.5 text-meta font-black uppercase tracking-widest transition-all ${
              activeTab === id
                ? "border-[var(--determinex-accent)] text-[var(--determinex-accent)]"
                : "border-transparent text-gray-600 hover:text-gray-400"
            }`}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === "workspace" && (
          <div className="h-full overflow-y-auto p-6 no-scrollbar">
            <div className="mb-6 border-b border-white/10 pb-5">
              <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
                <Wrench size={14} /> Attachable IDE Tools
              </div>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[var(--determinex-muted)]">
                These are not separate destinations. They dock into the current screen so a user can
                keep proof, code, terminal output, and search beside the work they are doing.
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {workspaceTools.map(({ id, name, icon: Icon, detail }) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => onLaunchTool(id)}
                  data-testid={`tools-launch-${id}`}
                  className={`group rounded-2xl border p-5 text-left transition-all hover:-translate-y-0.5 hover:shadow-[0_14px_38px_rgba(0,0,0,0.35)] ${
                    activeTool === id
                      ? "border-[var(--determinex-accent)] bg-[var(--determinex-accent)]/10"
                      : "border-white/10 bg-black/30 hover:border-[var(--determinex-accent)]/40"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-[var(--determinex-border)] bg-[var(--determinex-accent)]/10 text-[var(--determinex-accent)]">
                      <Icon size={18} />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-black text-white">{name}</div>
                      <div className="mt-0.5 text-eyebrow font-black uppercase tracking-widest text-[var(--determinex-accent)] opacity-0 transition-opacity group-hover:opacity-100">
                        {activeTool === id ? "Open" : "Attach"}
                      </div>
                    </div>
                  </div>
                  <p className="mt-3 text-label leading-relaxed text-gray-500">{detail}</p>
                </button>
              ))}
            </div>
          </div>
        )}

        {activeTab === "providers" && (
          <div className="h-full overflow-y-auto p-6 no-scrollbar">
            <div className="mb-6 border-b border-white/10 pb-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
                  <Bot size={14} /> Model and Agent Providers
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setSettingsTab("network");
                    setShowSettings(true);
                  }}
                  className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-eyebrow font-black uppercase tracking-widest text-gray-400 transition hover:border-[var(--determinex-accent)]/40 hover:text-[var(--determinex-accent)]"
                  title="Open Network Policy settings"
                >
                  Network: {networkCopy.shortLabel}
                </button>
              </div>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[var(--determinex-muted)]">
                Grouped by what actually matters when picking one: where it runs, what it costs, and
                whether your code leaves this machine. A role (Oracle, Architect, Builder, Monitor)
                can be assigned any provider below --{" "}
                <button
                  type="button"
                  onClick={() => {
                    setSettingsTab("roles");
                    setShowSettings(true);
                  }}
                  className="font-bold text-[var(--determinex-accent)] underline underline-offset-2 hover:opacity-80"
                >
                  mix local and cloud in a Hybrid Stack
                </button>{" "}
                per role instead of picking one provider for everything.
              </p>
              <div className="mt-4 rounded-xl border border-white/10 bg-black/25 px-4 py-3 text-label leading-relaxed text-gray-500">
                {networkCopy.summary} ProgramBench and hardened benchmark runners remain
                network-denied even when the IDE is online.
              </div>
              <div className="mt-3 rounded-xl border border-emerald-500/15 bg-emerald-950/10 px-4 py-3 text-label leading-relaxed text-emerald-300/80">
                None of these are required to use Determinex -- Ollama Local alone is enough. This
                list exists because the system is <em>capable</em> of routing to any of them (or
                mixing several in a Hybrid Stack), not because you need to set them all up.
              </div>
            </div>

            {(["local", "free", "cheap", "frontier"] as ProviderClass[]).map((cls) => {
              const rows = PROVIDER_ROLODEX.filter((p) => p.cls === cls);
              const copy = CLASS_COPY[cls];
              return (
                <div key={cls} className="mb-6">
                  <div className="mb-2.5 flex items-center gap-2">
                    {cls === "local" ? (
                      <HardDrive size={12} style={{ color: copy.color }} />
                    ) : (
                      <Cloud size={12} style={{ color: copy.color }} />
                    )}
                    <span
                      className="text-meta font-black uppercase tracking-widest"
                      style={{ color: copy.color }}
                    >
                      {copy.label}
                    </span>
                    <span
                      className="rounded-full border px-2 py-0.5 text-eyebrow font-black uppercase tracking-widest"
                      style={{
                        borderColor: `${copy.color}40`,
                        color: copy.color,
                        background: `${copy.color}14`,
                      }}
                    >
                      {copy.badge}
                    </span>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {rows.map((p) => {
                      const connected =
                        p.keyField === null
                          ? ollamaOnline === true
                          : Boolean(keyStatus[p.keyField]);
                      const statusKnown = p.keyField === null ? ollamaOnline !== null : true;
                      return (
                        <div
                          key={p.key}
                          className="rounded-2xl border border-white/10 bg-black/30 p-5"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-sm font-black text-white">{p.name}</div>
                            <span
                              className={`flex items-center gap-1.5 rounded-full border px-2 py-1 text-eyebrow font-black uppercase tracking-widest ${
                                !statusKnown
                                  ? "border-white/10 bg-white/[0.03] text-gray-500"
                                  : connected
                                    ? "border-emerald-500/30 bg-emerald-950/20 text-emerald-400"
                                    : "border-white/10 bg-white/[0.03] text-gray-500"
                              }`}
                            >
                              <span
                                className={`h-1.5 w-1.5 rounded-full ${!statusKnown ? "bg-gray-600" : connected ? "bg-emerald-400" : "bg-gray-600"}`}
                              />
                              {!statusKnown
                                ? "Checking…"
                                : connected
                                  ? "Connected"
                                  : "Not connected"}
                            </span>
                          </div>
                          <p className="mt-3 text-label leading-relaxed text-gray-500">
                            {p.detail}
                          </p>
                          <p className="mt-2 text-meta font-mono text-gray-600">{p.privacy}</p>
                          <div className="mt-4 flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                if (p.keyField === null) {
                                  onOpenBrain?.();
                                } else if (networkPolicy === "offline") {
                                  setSettingsTab("network");
                                  setShowSettings(true);
                                } else if (BULK_KEY_VAULT_PROVIDERS.has(p.key)) {
                                  // openai/anthropic/gemini/groq save via SettingsModal's
                                  // "keys" tab (saveApiKeys) -- save_service_key's Rust
                                  // whitelist doesn't recognize these service names, so
                                  // routing them through ServiceLoginModal would fail
                                  // server-side with "Unknown service". Found live while
                                  // building this rolodex, 2026-07-19.
                                  setSettingsTab("keys");
                                  setShowSettings(true);
                                } else {
                                  onShowServiceLogin(p.key);
                                }
                              }}
                              className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-eyebrow font-black uppercase tracking-widest text-gray-400 transition hover:border-[var(--determinex-accent)]/40 hover:text-[var(--determinex-accent)]"
                            >
                              {p.keyField === null
                                ? "Open model slots"
                                : networkPolicy === "offline"
                                  ? "Enable network policy"
                                  : connected
                                    ? "Manage key"
                                    : "Add API key"}
                            </button>
                            {/* Not connected yet -- link straight to the provider's own
                                console so the user can decide whether they even want this
                                one, rather than only ever seeing an internal "add key" form
                                with no idea where a key would come from. */}
                            {!connected && p.getKeyUrl && (
                              <a
                                href={p.getKeyUrl}
                                target="_blank"
                                rel="noreferrer"
                                className="flex items-center gap-1 rounded-lg px-2 py-2 text-eyebrow font-bold uppercase tracking-widest text-gray-600 transition hover:text-gray-300"
                              >
                                Get a key <ExternalLink size={10} />
                              </a>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {/* Custom providers -- Ryan: "add your own with link and api and
                setup for color of it." */}
            <div className="mb-6">
              <div className="mb-2.5 flex items-center gap-2">
                <Plus size={12} className="text-fuchsia-400" />
                <span className="text-meta font-black uppercase tracking-widest text-fuchsia-400">
                  Your Own
                </span>
                <span className="rounded-full border border-fuchsia-400/25 bg-fuchsia-950/15 px-2 py-0.5 text-eyebrow font-black uppercase tracking-widest text-fuchsia-300">
                  CUSTOM
                </span>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {customProviders.map((p) => (
                  <div key={p.id} className="rounded-2xl border border-white/10 bg-black/30 p-5">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <span
                          className="h-2.5 w-2.5 rounded-full"
                          style={{ background: p.color }}
                        />
                        <div className="text-sm font-black text-white">{p.name}</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeCustomProvider(p.id)}
                        className="rounded-md p-1.5 text-gray-600 hover:bg-red-950/30 hover:text-red-400"
                        title="Remove"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                    <p className="mt-3 text-meta font-mono text-gray-600">
                      {p.apiKey ? "•".repeat(Math.min(p.apiKey.length, 24)) : "no key saved"}
                    </p>
                    {p.url && (
                      <a
                        href={p.url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 flex w-fit items-center gap-1 text-eyebrow font-bold uppercase tracking-widest text-gray-500 hover:text-gray-300"
                      >
                        {p.url} <ExternalLink size={10} />
                      </a>
                    )}
                  </div>
                ))}

                {addingCustom ? (
                  <div className="rounded-2xl border border-fuchsia-400/25 bg-fuchsia-950/10 p-5">
                    <input
                      value={customDraft.name}
                      onChange={(e) => setCustomDraft((d) => ({ ...d, name: e.target.value }))}
                      placeholder="Provider name"
                      className="w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-label text-white outline-none focus:border-fuchsia-400/40"
                    />
                    <input
                      value={customDraft.url}
                      onChange={(e) => setCustomDraft((d) => ({ ...d, url: e.target.value }))}
                      placeholder="Docs / console URL"
                      className="mt-2 w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-label text-white outline-none focus:border-fuchsia-400/40"
                    />
                    <input
                      type="password"
                      value={customDraft.apiKey}
                      onChange={(e) => setCustomDraft((d) => ({ ...d, apiKey: e.target.value }))}
                      placeholder="API key"
                      className="mt-2 w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-label text-white outline-none focus:border-fuchsia-400/40"
                    />
                    <div className="mt-3 flex items-center gap-1.5">
                      {CUSTOM_PROVIDER_COLORS.map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => setCustomDraft((d) => ({ ...d, color: c }))}
                          className={`h-5 w-5 rounded-full transition ${customDraft.color === c ? "ring-2 ring-white/70 ring-offset-2 ring-offset-black" : ""}`}
                          style={{ background: c }}
                          title={c}
                        />
                      ))}
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={addCustomProvider}
                        disabled={!customDraft.name.trim()}
                        className="rounded-lg border border-fuchsia-400/25 bg-fuchsia-950/20 px-3 py-1.5 text-eyebrow font-black uppercase tracking-widest text-fuchsia-300 hover:bg-fuchsia-900/30 disabled:opacity-40"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setAddingCustom(false)}
                        className="rounded-lg border border-white/10 px-3 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-500 hover:bg-white/5"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setAddingCustom(true)}
                    className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-white/15 bg-black/10 p-5 text-gray-500 transition hover:border-fuchsia-400/40 hover:text-fuchsia-300"
                  >
                    <Plus size={18} />
                    <span className="text-eyebrow font-black uppercase tracking-widest">
                      Add your own provider
                    </span>
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "browse" && <MarketplacePanel />}

        {activeTab === "installed" && (
          <div className="h-full overflow-y-auto no-scrollbar">
            <ToolsRegistry
              toolCatalog={liveToolCatalog}
              toolCoverage={toolCoverage}
              onShowServiceLogin={onShowServiceLogin}
              onOpenBrowse={() => setActiveTab("browse")}
            />
          </div>
        )}
      </div>
    </div>
  );
}
