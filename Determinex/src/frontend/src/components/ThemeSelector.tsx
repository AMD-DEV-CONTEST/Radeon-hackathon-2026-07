"use client";
import React, { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  Archive,
  Binary,
  Bot,
  Castle,
  Check,
  CircleDashed,
  CircleDot,
  CloudRain,
  Crosshair,
  FlaskConical,
  Frame,
  Ghost,
  Grid3X3,
  Moon,
  Mountain,
  Orbit,
  RadioTower,
  Rocket,
  Shield,
  Sparkles,
  Sun,
  Telescope,
  TerminalSquare,
  Trees,
  Wrench,
} from "lucide-react";
import { useIterationTheme } from "@/contexts/IterationThemeContext";
import { SKIN_PACKS, type SkinIconKey } from "@/theme/skinPacks";

type SkinIconComponent = React.ComponentType<{
  size?: number;
  strokeWidth?: number;
  className?: string;
}>;

const SKIN_ICONS: Record<SkinIconKey, SkinIconComponent> = {
  binary: Binary,
  orbit: Orbit,
  terminal: TerminalSquare,
  radar: Crosshair,
  grid: Grid3X3,
  lens: CircleDot,
  archive: Archive,
  assistant: Bot,
  terrain: Trees,
  rain: CloudRain,
  shield: Shield,
  cave: Mountain,
  aether: Sparkles,
  frame: Frame,
  wraith: Ghost,
  ring: CircleDashed,
  test: FlaskConical,
  atlas: Telescope,
  signal: RadioTower,
  dungeon: Castle,
  mech: Rocket,
  plainDark: Moon,
  plainLight: Sun,
};

// Note: rocinante uses "orbit", lightcycle uses "grid", trex uses "terrain" — all already in SKIN_ICONS

// Skin groups for visual organization
const SKIN_GROUPS: Array<{ label: string; ids: string[] }> = [
  {
    label: "Industrial",
    ids: ["codefall", "vector", "neon", "strategy", "redlens", "raincity"],
  },
  {
    label: "Exploration",
    ids: ["orbital", "aegis", "terrain", "archive", "cave", "shelter"],
  },
  {
    label: "Signal & Aether",
    ids: ["aether", "signal", "wraith", "frame", "ring", "dungeon", "mech", "atlas", "test"],
  },
  {
    label: "Cinematic",
    ids: ["rocinante", "lightcycle", "trex"],
  },
  {
    label: "Plain",
    ids: ["plaindark", "plainlight"],
  },
];

function ColorSwatch({ color, label }: { color: string; label: string }) {
  return (
    <div
      className="h-3 w-3 rounded-sm border border-white/10 shrink-0"
      style={{ background: color }}
      title={label}
    />
  );
}

export function SkinPickerInline() {
  const { theme, setTheme, allThemes } = useIterationTheme();
  const [startingTheme, setStartingTheme] = useState(theme);
  const allById = allThemes.reduce<Record<string, string>>((acc, t) => ({ ...acc, [t]: t }), {});

  return (
    <div className="space-y-1">
      <div className="mb-3 rounded-xl border border-[var(--determinex-border)]/30 bg-black/30 p-3">
        <div className="text-eyebrow font-black uppercase tracking-widest text-[var(--determinex-accent)]">
          Preview mode
        </div>
        <p className="mt-1 text-label leading-relaxed text-white/45">
          Pick a skin to preview it across the IDE. Apply keeps it; Cancel returns to the skin you
          opened this panel with.
        </p>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => setStartingTheme(theme)}
            className="rounded-lg border border-emerald-400/25 bg-emerald-950/20 px-3 py-2 text-eyebrow font-black uppercase tracking-widest text-emerald-300"
          >
            Apply skin
          </button>
          <button
            type="button"
            onClick={() => setTheme(startingTheme)}
            className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-eyebrow font-black uppercase tracking-widest text-white/45"
          >
            Cancel preview
          </button>
        </div>
      </div>
      {SKIN_GROUPS.map((group) => {
        const groupThemes = group.ids.filter((id) => allById[id]);
        if (groupThemes.length === 0) return null;
        return (
          <div key={group.label}>
            <div className="px-1 pb-1.5 pt-3">
              <span className="font-mono text-eyebrow uppercase tracking-[0.3em] text-white/30">
                {group.label}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {groupThemes.map((id) => {
                const t = id as keyof typeof SKIN_PACKS;
                const pack = SKIN_PACKS[t];
                if (!pack) return null;
                const Icon = SKIN_ICONS[pack.iconKey] ?? Wrench;
                const active = theme === t;
                return (
                  <button
                    key={t}
                    onClick={() => setTheme(t)}
                    title="Preview this skin"
                    className="group relative flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-all"
                    style={{
                      borderColor: active ? pack.colors.accent + "60" : "rgba(255,255,255,0.07)",
                      background: active
                        ? `linear-gradient(135deg, ${pack.colors.accentGlow}, ${pack.colors.panelStrong})`
                        : "rgba(255,255,255,0.02)",
                      boxShadow: active ? `0 0 12px ${pack.colors.accentGlow}` : undefined,
                    }}
                  >
                    <span
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition-all"
                      style={{
                        color: pack.colors.accent,
                        borderColor: pack.colors.border,
                        background: `linear-gradient(135deg, ${pack.colors.panelStrong}, ${pack.colors.bg})`,
                        boxShadow: active ? `0 0 10px ${pack.colors.accentGlow}` : undefined,
                      }}
                    >
                      <Icon size={14} strokeWidth={1.85} />
                    </span>
                    <span className="min-w-0 flex-1 overflow-hidden">
                      <span
                        className={`block truncate text-label font-bold ${active ? "text-white" : "text-white/55 group-hover:text-white/80"}`}
                      >
                        {pack.label}
                      </span>
                      <span className="block truncate text-eyebrow uppercase tracking-wider text-white/20">
                        {pack.cue}
                      </span>
                    </span>
                    {active && (
                      <Check
                        size={12}
                        strokeWidth={2.5}
                        className="shrink-0"
                        style={{ color: pack.colors.accent }}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
