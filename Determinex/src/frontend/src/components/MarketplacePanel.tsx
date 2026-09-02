"use client";
import { useState, useMemo, useEffect } from "react";
import {
  Search,
  Check,
  Download,
  Zap,
  ShieldCheck,
  Globe,
  Code2,
  Database,
  Cpu,
  Palette,
  GitBranch,
  Package,
  ArrowRight,
  ExternalLink,
  KeyRound,
} from "lucide-react";

import { type AddonStatus, type AddonCategory, type Addon, ADDONS } from "@/lib/addons";
import {
  ADDONS_UPDATED_EVENT,
  defaultInstalledAddonIds,
  readInstalledAddonIds,
  writeInstalledAddonIds,
} from "@/lib/addonStorage";
import { useSettings } from "@/contexts/SettingsContext";

// llm-category addon id -> the real provider key name get_api_key_status
// actually reports. "chatgpt" the marketplace label maps to the "openai"
// key row; "ollama" is local (no key, always available once the app runs).
const LLM_ADDON_TO_KEY_PROVIDER: Record<string, string> = {
  anthropic: "anthropic",
  deepseek: "deepseek",
  chatgpt: "openai",
  gemini: "gemini",
  mistral: "mistral",
  kimi: "kimi",
};

const CATEGORIES: { id: AddonCategory | "all"; label: string; icon: typeof Zap; color: string }[] =
  [
    { id: "all", label: "All", icon: Package, color: "text-gray-400" },
    { id: "llm", label: "LLM Providers", icon: Cpu, color: "text-violet-400" },
    { id: "oracle", label: "Oracles", icon: Code2, color: "text-emerald-400" },
    { id: "benchmark", label: "Benchmarks", icon: Database, color: "text-amber-400" },
    { id: "privacy", label: "Privacy", icon: ShieldCheck, color: "text-cyan-400" },
    { id: "integration", label: "Integrations", icon: Globe, color: "text-blue-400" },
    { id: "theme", label: "Themes", icon: Palette, color: "text-pink-400" },
  ];

const CATEGORY_ICON_MAP: Record<AddonCategory, typeof Zap> = {
  llm: Cpu,
  oracle: Code2,
  benchmark: Database,
  privacy: ShieldCheck,
  integration: Globe,
  theme: Palette,
};

function AddonCard({
  addon,
  onToggle,
  keyConnected,
  onOpenKeySettings,
}: {
  addon: Addon;
  onToggle: (id: string) => void;
  // Set only for category:"llm" cards -- when present, this REPLACES the
  // fake local-toggle install state with the real get_api_key_status result
  // for that provider. Was previously always driven by the hardcoded/toggled
  // `addon.status`, so every LLM card lied about being "Installed" regardless
  // of whether a key was actually configured. Ryan, live: "supposedly
  // installed? but not..."
  keyConnected?: boolean;
  onOpenKeySettings?: () => void;
}) {
  const CatIcon = CATEGORY_ICON_MAP[addon.category];
  const isLlmKeyCard = keyConnected !== undefined;
  const isInstalled = isLlmKeyCard
    ? keyConnected
    : addon.status === "installed" || addon.status === "builtin";
  const isBuiltin = addon.status === "builtin";
  // Cannot be installed by clicking: toggle() provisions nothing, and the sandboxed oracle fails
  // closed for these languages. Rendering an Install button would promise what the product refuses.
  const isPlanned = addon.planned === true;

  return (
    <div className="group relative flex gap-3.5 rounded-xl border border-white/5 bg-white/[0.02] p-4 transition-all hover:border-white/10 hover:bg-white/[0.04]">
      <div className="h-11 w-11 shrink-0 rounded-xl border border-white/8 bg-black/30 flex items-center justify-center text-xl">
        {addon.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-body font-bold text-white/85">{addon.name}</span>
              {addon.featured && (
                <span className="rounded px-1.5 py-0.5 text-eyebrow font-black uppercase tracking-widest bg-[var(--determinex-accent)]/15 text-[var(--determinex-accent)] border border-[var(--determinex-accent)]/20">
                  Featured
                </span>
              )}
              {addon.status === "beta" && (
                <span className="rounded px-1.5 py-0.5 text-eyebrow font-black uppercase tracking-widest bg-amber-500/15 text-amber-400 border border-amber-500/20">
                  Beta
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-meta text-gray-600">{addon.author}</span>
              <span className="text-meta text-gray-700">v{addon.version}</span>
            </div>
          </div>
          <button
            onClick={() => {
              if (isBuiltin || isPlanned) return;
              if (isLlmKeyCard) {
                onOpenKeySettings?.();
                return;
              }
              onToggle(addon.id);
            }}
            disabled={isBuiltin || isPlanned}
            title={
              isPlanned
                ? "Not shippable yet — the sandboxed oracle fails closed for this language"
                : isLlmKeyCard
                  ? "Open Settings -> API Keys"
                  : undefined
            }
            className={`shrink-0 flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-eyebrow font-black uppercase tracking-widest transition-all ${
              isBuiltin || isPlanned
                ? "border-white/5 bg-white/[0.03] text-gray-700 cursor-default"
                : isInstalled
                  ? isLlmKeyCard
                    ? "border-emerald-500/30 bg-emerald-950/20 text-emerald-400 hover:bg-emerald-900/30"
                    : "border-emerald-500/30 bg-emerald-950/20 text-emerald-400 hover:bg-red-950/20 hover:border-red-500/30 hover:text-red-400"
                  : "border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/8 text-[var(--determinex-accent)] hover:bg-[var(--determinex-accent)]/15"
            }`}
          >
            {isPlanned ? (
              // Never "Install": clicking provisions nothing, and the oracle fails closed for this
              // language, so an Install button here is a promise the product cannot keep.
              <>Planned</>
            ) : isBuiltin ? (
              <>
                <Check size={9} /> Built-in
              </>
            ) : isLlmKeyCard ? (
              isInstalled ? (
                <>
                  <Check size={9} /> Connected
                </>
              ) : (
                <>
                  <KeyRound size={9} /> Add API Key
                </>
              )
            ) : isInstalled ? (
              <>
                <Check size={9} /> Installed
              </>
            ) : (
              <>
                <Download size={9} /> Install
              </>
            )}
          </button>
        </div>
        <p className="text-label leading-relaxed text-gray-500 mt-1.5 line-clamp-2">
          {addon.description}
        </p>
        <div className="flex items-center gap-3 mt-2">
          <div className="flex items-center gap-1">
            {addon.tags.slice(0, 3).map((t) => (
              <span
                key={t}
                className="text-meta text-gray-700 border border-white/5 rounded px-1.5 py-0.5"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function MarketplacePanel() {
  const { keyStatus, setSettingsTab, setShowSettings } = useSettings();
  const openKeySettings = () => {
    setSettingsTab("keys");
    setShowSettings(true);
  };
  // llm-category addons: real key-connected state, not the fake local toggle.
  const llmKeyConnected = (addonId: string): boolean | undefined => {
    const providerKey = LLM_ADDON_TO_KEY_PROVIDER[addonId];
    if (!providerKey) return undefined; // ollama etc. -- not key-gated, falls through to normal toggle
    return keyStatus[providerKey] === true;
  };

  const [activeCategory, setActiveCategory] = useState<AddonCategory | "all">("all");
  const [query, setQuery] = useState("");
  const [showHubInfo, setShowHubInfo] = useState(false);
  const [installed, setInstalled] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return defaultInstalledAddonIds();
    try {
      return readInstalledAddonIds(localStorage);
    } catch {
      return defaultInstalledAddonIds();
    }
  });

  useEffect(() => {
    writeInstalledAddonIds(localStorage, installed);
    window.dispatchEvent(new Event(ADDONS_UPDATED_EVENT));
  }, [installed]);

  const toggle = (id: string) => {
    // A planned addon cannot be installed by clicking. `toggle` only writes an id into
    // localStorage -- nothing is provisioned -- so allowing it would render "Installed" for a
    // capability that does not exist, and the user would meet the oracle's fail-closed refusal
    // after being told the toolchain was present.
    if (ADDONS.find((a) => a.id === id)?.planned) return;
    setInstalled((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const addons = useMemo(() => {
    return ADDONS.map((a) => ({
      ...a,
      // A planned addon stays "available" no matter what localStorage says. Belt and braces with
      // the guard in toggle(): an id persisted before `planned` existed would otherwise still
      // render as "Installed" on upgrade.
      status: (a.planned
        ? "available"
        : installed.has(a.id)
          ? a.status === "builtin"
            ? "builtin"
            : "installed"
          : a.status === "beta"
            ? "beta"
            : "available") as AddonStatus,
    })).filter(
      (a) =>
        (activeCategory === "all" || a.category === activeCategory) &&
        (!query ||
          a.name.toLowerCase().includes(query.toLowerCase()) ||
          a.description.toLowerCase().includes(query.toLowerCase()) ||
          a.tags.some((t) => t.includes(query.toLowerCase())))
    );
  }, [activeCategory, query, installed]);

  const installedCount = ADDONS.filter((a) =>
    // Planned addons never count: a stale localStorage id from before `planned` existed would
    // otherwise inflate the headline number with capabilities that do not exist.
    a.planned
      ? false
      : a.category === "llm"
        ? (llmKeyConnected(a.id) ?? installed.has(a.id))
        : installed.has(a.id)
  ).length;
  const featuredAddons = ADDONS.filter(
    (a) => a.featured && (activeCategory === "all" || a.category === activeCategory)
  );

  return (
    <div
      className="flex h-full min-h-0 overflow-hidden"
      style={{ background: "var(--determinex-bg)" }}
    >
      {/* Left: category nav */}
      <div
        className="w-52 shrink-0 border-r flex flex-col py-4 gap-1 overflow-y-auto no-scrollbar"
        style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.3)" }}
      >
        <div className="px-4 mb-3">
          <div className="text-eyebrow uppercase font-black tracking-widest text-gray-600 mb-0.5">
            Determinex Marketplace
          </div>
          <div className="text-label text-gray-500">{installedCount} installed</div>
        </div>
        {CATEGORIES.map((cat) => {
          const CatIcon = cat.icon;
          const count =
            cat.id === "all" ? ADDONS.length : ADDONS.filter((a) => a.category === cat.id).length;
          return (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id)}
              className={`flex items-center gap-2.5 px-4 py-2 rounded-lg mx-2 text-left transition-all ${
                activeCategory === cat.id
                  ? "bg-white/[0.06] border border-white/8"
                  : "hover:bg-white/[0.03]"
              }`}
            >
              <CatIcon
                size={13}
                className={activeCategory === cat.id ? cat.color : "text-gray-600"}
              />
              <span
                className={`text-label font-semibold flex-1 ${activeCategory === cat.id ? "text-white/80" : "text-gray-500"}`}
              >
                {cat.label}
              </span>
              <span className="text-meta text-gray-700 font-mono">{count}</span>
            </button>
          );
        })}

        <div className="mt-auto px-4 pt-4 border-t border-white/5">
          <button
            onClick={() => setShowHubInfo((value) => !value)}
            className="flex items-center gap-2 text-meta text-gray-600 hover:text-gray-400 transition-colors w-full"
            data-testid="community-hub-button"
          >
            <ExternalLink size={10} /> Browse Community Hub
            <ArrowRight size={9} className="ml-auto" />
          </button>
        </div>
      </div>

      {/* Right: main content */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* Header + search */}
        <div
          className="border-b px-6 py-4 shrink-0"
          style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.2)" }}
        >
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)] mb-0">
              <Package size={13} />
              {activeCategory === "all"
                ? "All Extensions"
                : CATEGORIES.find((c) => c.id === activeCategory)?.label}
            </div>
            <div className="relative flex-1 ml-auto">
              <Search
                size={12}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600"
              />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search extensions..."
                className="w-full rounded-xl border border-white/8 bg-black/30 py-2 pl-8 pr-3 text-label text-white/70 placeholder:text-gray-700 outline-none focus:border-[var(--determinex-accent)]/30 transition-colors"
              />
            </div>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar px-6 py-4 space-y-6">
          {showHubInfo && (
            <div
              className="rounded-xl border border-[var(--determinex-accent)]/20 bg-[var(--determinex-accent)]/5 p-4"
              data-testid="community-hub-panel"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-meta uppercase font-black tracking-widest text-[var(--determinex-accent)] mb-1">
                    Add-on Manager
                  </div>
                  <p className="text-label leading-relaxed text-gray-400 max-w-3xl">
                    Public community publishing is not enabled in this local installer yet. This hub
                    manages bundled add-ons, provider slots, local model routes, privacy gates, and
                    integrations already visible to Determinex.
                  </p>
                </div>
                <button
                  onClick={() => setShowHubInfo(false)}
                  className="rounded-lg border border-white/8 px-2.5 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-gray-500 hover:text-gray-300"
                >
                  Close
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mt-3">
                <button
                  onClick={() => setActiveCategory("llm")}
                  className="rounded-lg border border-white/8 bg-black/20 px-3 py-2 text-left text-label text-gray-400 hover:text-white"
                >
                  Configure providers and API-backed models
                </button>
                <button
                  onClick={() => setActiveCategory("privacy")}
                  className="rounded-lg border border-white/8 bg-black/20 px-3 py-2 text-left text-label text-gray-400 hover:text-white"
                >
                  Review Local vs Cloak privacy gates
                </button>
                <button
                  onClick={() => setActiveCategory("integration")}
                  className="rounded-lg border border-white/8 bg-black/20 px-3 py-2 text-left text-label text-gray-400 hover:text-white"
                >
                  Enable integrations when their credentials are configured
                </button>
              </div>
            </div>
          )}

          {/* Featured banner (only in "all" / relevant category, when no search) */}
          {!query && featuredAddons.length > 0 && (
            <div>
              <div className="text-eyebrow uppercase font-black tracking-widest text-gray-600 mb-3">
                Featured
              </div>
              <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                {featuredAddons.slice(0, 4).map((a) => (
                  <AddonCard
                    key={a.id}
                    addon={{
                      ...a,
                      status: (installed.has(a.id)
                        ? a.status === "builtin"
                          ? "builtin"
                          : "installed"
                        : a.status === "beta"
                          ? "beta"
                          : "available") as AddonStatus,
                    }}
                    onToggle={toggle}
                    keyConnected={a.category === "llm" ? llmKeyConnected(a.id) : undefined}
                    onOpenKeySettings={openKeySettings}
                  />
                ))}
              </div>
            </div>
          )}

          {/* All results */}
          <div>
            {!query && (
              <div className="text-eyebrow uppercase font-black tracking-widest text-gray-600 mb-3">
                {query ? "Results" : "All"}{" "}
                <span className="text-gray-700 font-mono ml-1">{addons.length}</span>
              </div>
            )}
            {addons.length === 0 ? (
              <div className="text-center py-16">
                <Package size={32} className="text-gray-700 mx-auto mb-3" />
                <p className="text-body font-bold text-gray-600">No extensions found</p>
                <p className="text-label text-gray-700 mt-1">Try a different search or category</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                {addons
                  .filter((a) => !a.featured || query)
                  .map((a) => (
                    <AddonCard
                      key={a.id}
                      addon={a}
                      onToggle={toggle}
                      keyConnected={a.category === "llm" ? llmKeyConnected(a.id) : undefined}
                      onOpenKeySettings={openKeySettings}
                    />
                  ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
