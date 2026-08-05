"use client";

import { Blocks, Key, Puzzle, Zap, Server, ShieldAlert } from "lucide-react";
import { isTauri } from "@/lib/api";

interface ToolsRegistryProps {
  toolCatalog: any[];
  toolCoverage: string | number;
  onShowServiceLogin: (id: string) => void;
  onOpenBrowse?: () => void;
}

export function ToolsRegistry({
  toolCatalog,
  toolCoverage,
  onShowServiceLogin,
  onOpenBrowse,
}: ToolsRegistryProps) {
  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-y-auto no-scrollbar p-6">
      <div className="mb-6 border-b border-white/10 pb-6">
        <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
          <Blocks size={14} /> Capability Grid
        </div>
        <h2
          className="mt-2 text-3xl font-black tracking-tight text-[var(--determinex-text)]"
          style={{ fontFamily: "var(--determinex-font-display)" }}
        >
          Tools & Plugins
        </h2>
        <p className="mt-2 text-sm text-[var(--determinex-muted)] max-w-2xl leading-relaxed">
          Manage integrations, connect services, and review active tool permissions.
        </p>
      </div>

      {!isTauri() && (
        <div className="mb-4 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2 text-meta text-gray-600 font-mono text-center shrink-0">
          Browser mode cannot read the native tool registry -- open the Tauri desktop app for live
          capability status.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {toolCatalog.map((t) => (
          <div
            key={t.name}
            className={`flex flex-col gap-3 rounded-2xl border p-5 transition-all ${
              t.status === "online"
                ? "border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/5"
                : "border-white/10 bg-black/30"
            }`}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
                    t.status === "online"
                      ? "border-[var(--determinex-accent)]/50 bg-[var(--determinex-accent)]/20 text-[var(--determinex-accent)]"
                      : t.status === "needs_key"
                        ? "border-amber-500/50 bg-amber-500/20 text-amber-400"
                        : "border-rose-500/50 bg-rose-500/20 text-rose-400"
                  }`}
                >
                  {t.status === "online" ? (
                    <Zap size={18} />
                  ) : t.status === "needs_key" ? (
                    <Key size={18} />
                  ) : (
                    <ShieldAlert size={18} />
                  )}
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white capitalize">
                    {t.name.replace(/_/g, " ")}
                  </h3>
                  <p className="text-label font-mono text-gray-500">{t.type || "Integration"}</p>
                </div>
              </div>
            </div>
            <p className="text-label text-gray-400 leading-relaxed min-h-[40px]">
              {t.description || "Provides extended capabilities to the Hive orchestration engine."}
            </p>

            <div className="mt-auto pt-4 border-t border-white/10">
              {t.status === "needs_key" ? (
                <button
                  onClick={() => onShowServiceLogin(t.requires || t.name)}
                  className="w-full rounded-xl border border-amber-500/30 bg-amber-500/10 py-2.5 text-meta font-black uppercase tracking-widest text-amber-400 transition-colors hover:bg-amber-500/20"
                >
                  Connect Service
                </button>
              ) : t.status === "needs_install" ? (
                <button
                  disabled
                  className="w-full rounded-xl border border-rose-500/30 bg-rose-500/10 py-2.5 text-meta font-black uppercase tracking-widest text-rose-400 opacity-50 cursor-not-allowed"
                >
                  Missing Dependency
                </button>
              ) : (
                <div className="flex items-center justify-center gap-2 rounded-xl border border-[var(--determinex-accent)]/20 bg-[var(--determinex-accent)]/10 py-2.5">
                  <div className="h-1.5 w-1.5 rounded-full bg-[var(--determinex-accent)] shadow-[0_0_6px_var(--determinex-accent-glow)]" />
                  <span className="text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
                    Online
                  </span>
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Placeholder for missing plugins */}
        <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-white/20 bg-white/[0.02] p-8 text-center">
          <Puzzle size={24} className="text-gray-600" />
          <div>
            <div className="text-body font-bold text-gray-400">Discover Plugins</div>
            <div className="text-label text-gray-600 mt-1">
              Browse the community extension registry.
            </div>
          </div>
          <button
            onClick={onOpenBrowse}
            className="mt-2 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-meta font-bold uppercase tracking-widest text-gray-400 transition-colors hover:bg-white/10"
          >
            Browse Extensions
          </button>
        </div>
      </div>
    </div>
  );
}
