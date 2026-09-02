"use client";
import { useEffect, useRef, useState, type ComponentType } from "react";
import {
  GitBranch,
  AlertCircle,
  CheckCircle2,
  Zap,
  Cpu,
  Circle,
  PanelBottom,
  Plus,
  Search,
} from "lucide-react";
import { LayoutMenu } from "./LayoutMenu";
import { AiRouteSummary } from "@/components/AiRouteSelect";
import { routeKeyReady, type ApiKeyStatus } from "@/lib/aiRouting";
import { useAiRouter } from "@/contexts/AiRouterContext";

export type QuickAttachItem = {
  id: string;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
};

type Props = {
  activeSidebar: string;
  selectedModel: string;
  gitBranch: string;
  oracleAccepted: boolean | null;
  oracleVerdict: string | null;
  errorCount: number;
  warningCount?: number;
  keyStatus?: ApiKeyStatus;
  onChangeModel?: (value: string) => void;
  onClickErrors?: () => void;
  /** Opens the command palette. Surfaces its shortcut in the strip. */
  onOpenPalette?: () => void;
  onClickModel?: () => void;
  onTogglePanel?: () => void;
  quickAttachItems?: QuickAttachItem[];
  activeAddonId?: string | null;
  onAttach?: (id: string) => void;
  onOpenToolsHub?: () => void;
};

const PANEL_LABELS: Record<string, string> = {
  none: "Home",
  ideation: "Concept Lab",
  pipeline: "Build Pipeline",
  explorer: "Workspace",
  git: "Source Control",
  hive: "Work",
  benchmark: "Brain",
  tools: "Tools",
  proof: "Proof",
  health: "Health Map",
  trace: "Agent Trace",
  cloak: "Privacy Cockpit",
  flywheel: "Flywheel Feed",
  terminal: "Terminal",
  editor: "Editor",
  search: "Verified Search",
};

function ModelChip({ model, ready }: { model: string; ready: boolean }) {
  const short = model
    .replace(/determinex/gi, "determinex")
    .replace("claude-", "")
    .replace("sonnet-", "Sonnet ")
    .replace("opus-", "Opus ")
    .replace("haiku-", "Haiku ")
    .replace("gemini-", "Gemini ")
    .replace("gpt-", "GPT-")
    .slice(0, 20);
  return (
    <span
      className="flex items-center gap-1 text-meta text-gray-300 font-mono border-l border-white/8 pl-2.5 ml-0.5"
      title={`Active model route: ${model}. Click to switch.`}
    >
      <Circle
        size={6}
        className={`fill-current ${ready ? "text-emerald-400" : "text-amber-400"}`}
      />
      <Cpu size={9} className="text-violet-400" />
      {model === "auto" ? "Auto" : short}
    </span>
  );
}

export function StatusBar({
  activeSidebar,
  selectedModel,
  gitBranch,
  oracleAccepted,
  oracleVerdict,
  errorCount,
  warningCount = 0,
  keyStatus = {},
  onChangeModel,
  onClickErrors,
  onOpenPalette,
  onClickModel,
  onTogglePanel,
  quickAttachItems = [],
  activeAddonId = null,
  onAttach,
  onOpenToolsHub,
}: Props) {
  const panelLabel = PANEL_LABELS[activeSidebar] ?? activeSidebar;
  const router = useAiRouter();
  const [routePopoverOpen, setRoutePopoverOpen] = useState(false);
  const [attachPopoverOpen, setAttachPopoverOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const attachRef = useRef<HTMLDivElement>(null);
  const modelReady = routeKeyReady(selectedModel, keyStatus) && router.routeWarnings.length === 0;

  useEffect(() => {
    if (!routePopoverOpen && !attachPopoverOpen) return;
    const onOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setRoutePopoverOpen(false);
      }
      if (attachRef.current && !attachRef.current.contains(e.target as Node)) {
        setAttachPopoverOpen(false);
      }
    };
    const onEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setRoutePopoverOpen(false);
        setAttachPopoverOpen(false);
      }
    };
    document.addEventListener("mousedown", onOutside);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onOutside);
      document.removeEventListener("keydown", onEscape);
    };
  }, [routePopoverOpen, attachPopoverOpen]);

  const oracleColor =
    oracleAccepted === true
      ? "text-emerald-400"
      : oracleAccepted === false
        ? "text-red-400"
        : "text-gray-700";

  return (
    <div
      /* h-5 (20px) made every control in this strip a ~19px-tall target, under
         WCAG 2.2 AA 2.5.8's 24px floor. h-7 (28px) clears it with the strip's own
         1px border accounted for -- h-6 measured 23px in practice. */
      className="fixed bottom-0 left-0 right-0 z-50 flex h-7 items-center justify-between select-none"
      style={{
        background: "rgba(4,6,10,0.96)",
        borderTop: "1px solid rgba(255,255,255,0.05)",
        backdropFilter: "blur(8px)",
      }}
    >
      {/* Left section */}
      <div className="flex items-center h-full">
        {/* Brand pill */}
        <div
          className="flex h-full items-center px-3 text-eyebrow font-black uppercase tracking-widest"
          style={{ background: "var(--determinex-accent)", color: "#000" }}
        >
          Determinex
        </div>

        {/* Command palette. There WAS a palette and no visible way to learn it
            existed -- the shortcut lived only in a code comment, so the fastest
            path through the app was invisible. */}
        {onOpenPalette && (
          <button
            type="button"
            onClick={onOpenPalette}
            title="Command palette — find any panel or action"
            aria-label="Open the command palette"
            className="flex h-full items-center gap-1.5 border-r border-white/8 px-2.5 text-meta text-gray-500 transition-colors hover:bg-white/[0.04] hover:text-gray-200"
          >
            <Search size={10} />
            <span className="font-mono">Ctrl+K</span>
          </button>
        )}

        {/* Named panel layouts. Per-surface widths were already persisted; this is
            the "I have a reviewing arrangement and a building arrangement"
            case. */}
        <LayoutMenu />

        {/* Git branch */}
        <div className="flex items-center gap-1 px-2.5 text-meta text-gray-600 border-r border-white/8 h-full">
          <GitBranch size={10} />
          <span className="font-mono">{gitBranch || "no repo"}</span>
        </div>

        {/* Errors */}
        <button
          onClick={onClickErrors}
          className="flex items-center gap-1 px-2.5 text-meta h-full border-r border-white/8 transition-colors hover:bg-white/[0.04]"
        >
          {errorCount > 0 ? (
            <>
              <AlertCircle size={10} className="text-red-400" />
              <span className="text-red-400 font-mono">{errorCount}</span>
            </>
          ) : (
            <>
              <CheckCircle2 size={10} className="text-gray-700" />
              <span className="text-gray-700">0</span>
            </>
          )}
          {warningCount > 0 && (
            <>
              <AlertCircle size={10} className="text-amber-400 ml-1.5" />
              <span className="text-amber-400 font-mono">{warningCount}</span>
            </>
          )}
        </button>

        {/* Panel toggle */}
        {onTogglePanel && (
          <button
            onClick={onTogglePanel}
            title="Toggle attached panel"
            aria-label="Toggle attached panel"
            className="flex items-center gap-1 px-2.5 text-meta h-full border-r border-white/8 text-gray-600 transition-colors hover:bg-white/[0.04] hover:text-gray-300"
          >
            <PanelBottom size={10} />
          </button>
        )}

        {/* Quick Attach — one click, from any screen, to attach any tool beside it.
            Used to require going to the separate Tools hub or knowing Ctrl+K.
            Found live 2026-07-19 (Ryan: "tools are the only way to add on? ...
            this should be integrated into the screens"). */}
        {quickAttachItems.length > 0 && onAttach && (
          <div className="relative h-full" ref={attachRef}>
            <button
              onClick={() => setAttachPopoverOpen((v) => !v)}
              title="Quick attach a tool to this screen"
              data-testid="statusbar-quick-attach"
              className="flex items-center gap-1 px-2.5 text-meta h-full border-r border-white/8 text-gray-600 transition-colors hover:bg-white/[0.04] hover:text-gray-300"
            >
              <Plus size={10} />
              <span className="uppercase tracking-widest">Attach</span>
            </button>
            {/* The popover below was max-h-[320px] + no-scrollbar with 17
                quick-attach items, so the tail of the list (Review and Merge
                among them) was cut off with no scrollbar and nothing else to
                suggest it existed. Observed clipping live 2026-07-27. Unlike
                the command palette -- which is keyboard-driven and
                scrollIntoView's the selected row -- this menu is mouse-only,
                so a hidden scrollbar leaves no way to discover the rest. Same
                trap as the left rail and the addon switcher. */}
            {attachPopoverOpen && (
              <div className="absolute bottom-6 left-0 z-[200] w-[220px] max-h-[60vh] overflow-y-auto rounded-xl border border-white/10 bg-[var(--dtx-code-bg)] p-1.5 shadow-2xl animate-fade-in">
                {quickAttachItems.map((item) => {
                  const ItemIcon = item.icon;
                  const active = activeAddonId === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => {
                        onAttach(item.id);
                        setAttachPopoverOpen(false);
                      }}
                      className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-label transition-colors ${
                        active
                          ? "bg-emerald-500/15 text-emerald-300"
                          : "text-gray-400 hover:bg-white/[0.06] hover:text-gray-200"
                      }`}
                    >
                      <ItemIcon
                        size={11}
                        className={active ? "text-emerald-400" : "text-gray-600"}
                      />
                      {item.label}
                    </button>
                  );
                })}
                {onOpenToolsHub && (
                  <button
                    onClick={() => {
                      onOpenToolsHub();
                      setAttachPopoverOpen(false);
                    }}
                    className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-white/8 px-2.5 py-1.5 pt-2 text-left text-eyebrow uppercase tracking-widest text-gray-600 transition-colors hover:text-gray-300"
                  >
                    All tools…
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Center: active panel */}
      <div className="absolute left-1/2 -translate-x-1/2 text-meta font-mono text-gray-600 pointer-events-none">
        {panelLabel}
      </div>

      {/* Right section */}
      <div className="flex items-center gap-0 h-full pr-1">
        {/* Oracle status */}
        <div className="flex items-center gap-1.5 px-2.5 text-meta border-l border-white/8 h-full">
          <Circle size={7} className={`${oracleColor} fill-current`} />
          <span className={`font-mono ${oracleColor}`}>
            {oracleVerdict ? oracleVerdict.slice(0, 12) : "Oracle Ready"}
          </span>
        </div>

        {/* Flywheel pulse */}
        <div className="flex items-center gap-1 px-2.5 text-meta text-gray-700 border-l border-white/8 h-full">
          <Zap size={9} className="text-orange-500/50" />
          <span className="font-mono">Flywheel</span>
        </div>

        {/* Model — click opens a quick-switch popover */}
        <div className="relative h-full" ref={popoverRef}>
          <button
            onClick={() => setRoutePopoverOpen((v) => !v)}
            className="flex items-center h-full px-2.5 border-l border-white/8 hover:bg-white/[0.04] transition-colors"
          >
            <ModelChip model={selectedModel} ready={modelReady} />
          </button>

          {routePopoverOpen && (
            <div className="absolute bottom-6 right-0 z-[200] w-[310px] animate-fade-in">
              <AiRouteSummary
                value={selectedModel}
                keyStatus={keyStatus}
                onChange={onChangeModel}
                onOpenSettings={() => {
                  setRoutePopoverOpen(false);
                  onClickModel?.();
                }}
              />
            </div>
          )}
        </div>

        {/* Shortcut hint */}
        <div className="pl-2 pr-2.5 text-meta font-mono text-gray-800 border-l border-white/5 h-full flex items-center">
          ^P
        </div>
      </div>
    </div>
  );
}
