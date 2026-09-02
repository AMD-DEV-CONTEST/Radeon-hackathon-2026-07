import type { CSSProperties } from "react";
import type { IterationTheme } from "@/contexts/IterationThemeContext";

export type SkinIconKey =
  | "binary"
  | "orbit"
  | "terminal"
  | "radar"
  | "grid"
  | "lens"
  | "archive"
  | "assistant"
  | "terrain"
  | "rain"
  | "shield"
  | "cave"
  | "aether"
  | "frame"
  | "wraith"
  | "ring"
  | "test"
  | "atlas"
  | "signal"
  | "dungeon"
  | "mech"
  | "plainDark"
  | "plainLight";

export interface SkinPack {
  id: IterationTheme;
  label: string;
  shortLabel: string;
  cue: string;
  iconKey: SkinIconKey;
  colors: {
    bg: string;
    panel: string;
    panelStrong: string;
    panelGlass: string;
    border: string;
    accent: string;
    accent2: string;
    accent3: string;
    text: string;
    muted: string;
    danger: string;
    accentGlow: string;
  };
  fonts: {
    sans: string;
    mono: string;
    display: string;
  };
  radius: string;
  shellShadow: string;
  rainBackground: string;
  rainOpacity: string;
  rainBlend: "screen" | "plus-lighter" | "normal" | "multiply";
  logoFilter: string;
  backdropImage?: string;
}

export type SkinPackStyle = CSSProperties &
  Record<`--determinex-${string}`, string> &
  Partial<Record<`--dtx-${string}`, string>>;

// ── The code-surface layer, derived from whatever skin is active ──────────────
//
// WHY THIS EXISTS
// 28 components styled their chrome with literal GitHub hex -- #0d1117 (97 uses),
// #30363d (168), #161b22 (55) -- against 32 that used the skin variables. 681 literal
// hex values in total. That is not a cosmetic inconsistency: a skin sets its palette as
// CSS variables on the root element, so a literal hex IGNORES ALL 27 SKINS. Half the app
// simply did not respond to the theme picker.
//
// The fix keeps the density distinction those panels wanted -- a code surface should read
// as recessed and neutral, not neon -- while making it a FUNCTION OF THE SKIN rather than
// a second hardcoded palette. So every skin gets a coherent code layer for free, and
// picking a skin changes the whole app.
//
// Derived in TypeScript, not with CSS color-mix(): this runs in whatever WebView2 the
// host has, and a color-mix() that the runtime does not understand fails to an invalid
// value -- i.e. an unstyled app. Deriving here is also testable, which color-mix is not.

/** [r, g, b, a] with a in 0..1. */
type Rgba = [number, number, number, number];

/**
 * Parse #rgb, #rrggbb, rgb() or rgba(). Returns null for anything else (named colours,
 * gradients), which callers treat as "leave the skin's value alone".
 *
 * rgba() support is load-bearing, not completeness for its own sake: the Determinex
 * skin's border is `rgba(42, 255, 129, 0.2)`. A hex-only parser no-ops on it, so the
 * derived code border came out as the skin's neon hairline -- on 168 replaced borders,
 * i.e. exactly the "dense tables should not be neon" property this layer exists for.
 */
function parseColor(input: string): Rgba | null {
  const value = input.trim();

  const rgbMatch = value.match(
    /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/i
  );
  if (rgbMatch) {
    const alphaRaw = rgbMatch[4];
    const alpha = alphaRaw
      ? alphaRaw.endsWith("%")
        ? parseFloat(alphaRaw) / 100
        : parseFloat(alphaRaw)
      : 1;
    return [
      parseFloat(rgbMatch[1]),
      parseFloat(rgbMatch[2]),
      parseFloat(rgbMatch[3]),
      Number.isFinite(alpha) ? alpha : 1,
    ];
  }

  const hex = value.replace(/^#/, "");
  if (/^[0-9a-f]{3}$/i.test(hex)) {
    const [r, g, b] = hex.split("");
    return [parseInt(r + r, 16), parseInt(g + g, 16), parseInt(b + b, 16), 1];
  }
  if (/^[0-9a-f]{6}$/i.test(hex)) {
    return [
      parseInt(hex.slice(0, 2), 16),
      parseInt(hex.slice(2, 4), 16),
      parseInt(hex.slice(4, 6), 16),
      1,
    ];
  }
  if (/^[0-9a-f]{8}$/i.test(hex)) {
    return [
      parseInt(hex.slice(0, 2), 16),
      parseInt(hex.slice(2, 4), 16),
      parseInt(hex.slice(4, 6), 16),
      parseInt(hex.slice(6, 8), 16) / 255,
    ];
  }
  return null;
}

const clamp255 = (n: number) => Math.max(0, Math.min(255, Math.round(n)));

/** Serialise back, preserving translucency -- a border that loses its alpha stops being
 *  a hairline and becomes a solid rule. */
function formatColor([r, g, b, a]: Rgba): string {
  if (a >= 1) {
    return `#${[r, g, b].map((c) => clamp255(c).toString(16).padStart(2, "0")).join("")}`;
  }
  return `rgba(${clamp255(r)}, ${clamp255(g)}, ${clamp255(b)}, ${Math.round(a * 1000) / 1000})`;
}

/** Blend `amount` of `b` into `a`. amount 0 => a, 1 => b. Alpha of `a` is preserved. */
function mix(a: string, b: string, amount: number): string {
  const pa = parseColor(a);
  const pb = parseColor(b);
  if (!pa || !pb) return a; // unparseable (gradient, named) -- leave the skin's value
  return formatColor([
    pa[0] + (pb[0] - pa[0]) * amount,
    pa[1] + (pb[1] - pa[1]) * amount,
    pa[2] + (pb[2] - pa[2]) * amount,
    pa[3],
  ]);
}

/** Pull a colour toward its own grey, keeping lightness and alpha. 1 => fully neutral. */
function desaturate(input: string, amount: number): string {
  const p = parseColor(input);
  if (!p) return input;
  const grey = 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2];
  return formatColor([
    p[0] + (grey - p[0]) * amount,
    p[1] + (grey - p[1]) * amount,
    p[2] + (grey - p[2]) * amount,
    p[3],
  ]);
}

/** True when a colour is light enough that surfaces must go DARKER-on-light. */
function isLight(input: string): boolean {
  const p = parseColor(input);
  if (!p) return false;
  return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] > 140;
}

/**
 * Code-surface + semantic tokens for a skin.
 *
 * Recession direction follows the skin: on a dark skin a code surface sinks toward black,
 * on a light skin (plainlight) it must rise toward white instead, or the panels invert
 * and the text stops being readable.
 */
export function getCodeLayerStyle(pack: SkinPack): Record<string, string> {
  const { bg, panel, panelStrong, border, text, muted, accent, accent2, danger } = pack.colors;
  const light = isLight(bg);
  const sink = light ? "#ffffff" : "#000000";
  const lift = light ? "#000000" : "#ffffff";

  return {
    // Surfaces: the skin's own, nudged for recession and drained of chroma so dense
    // tables read as neutral rather than tinted.
    "--dtx-code-bg-deep": desaturate(mix(bg, sink, 0.45), 0.55),
    "--dtx-code-bg": desaturate(mix(bg, sink, 0.2), 0.5),
    "--dtx-code-panel": desaturate(mix(panel, sink, 0.06), 0.45),
    "--dtx-code-raised": desaturate(mix(panelStrong, lift, 0.05), 0.4),

    // Borders: neutral, because a neon hairline on every row of a table is noise. Derived
    // from the skin's border when that is a hex; skins using rgba() keep their own.
    "--dtx-code-border": desaturate(mix(border, lift, 0.12), 0.8),
    "--dtx-code-border-subtle": desaturate(mix(border, sink, 0.25), 0.85),

    // Text tiers reuse the skin's, so contrast decisions made there hold here.
    "--dtx-code-text": text,
    "--dtx-code-muted": muted,

    // Semantic status colours. Tokens rather than literals so a skin can override them
    // later; today they are constant on purpose -- "pass" must stay recognisably green
    // across skins, or the meaning shifts with the decoration.
    "--dtx-ok": "#34d399",
    "--dtx-warn": "#f59e0b",
    "--dtx-fail": danger,
    "--dtx-info": "#60a5fa",
    "--dtx-alt": "#a78bfa",
    "--dtx-alt-2": accent2,
    "--dtx-accent": accent,
  };
}

const monoStack =
  '"JetBrains Mono", "SFMono-Regular", "Cascadia Code", "Fira Code", ui-monospace, monospace';
const cleanSans =
  '"Inter", "Segoe UI", "Helvetica Neue", system-ui, -apple-system, BlinkMacSystemFont, sans-serif';
const cinematicSans =
  '"Outfit", "Aptos Display", "Segoe UI Variable", "Inter", system-ui, -apple-system, sans-serif';

const haze = (a: string, b: string, c: string) =>
  `linear-gradient(115deg, ${a}, transparent 28%), radial-gradient(circle at 20% 18%, ${b}, transparent 26%), radial-gradient(circle at 80% 12%, ${c}, transparent 22%), repeating-linear-gradient(90deg, rgba(255,255,255,0.025) 0, rgba(255,255,255,0.025) 1px, transparent 1px, transparent 72px)`;

const scan = (line: string, glow: string) =>
  `linear-gradient(180deg, transparent 0, ${line} 50%, transparent 100%), repeating-linear-gradient(0deg, ${glow} 0, ${glow} 1px, transparent 1px, transparent 18px), repeating-linear-gradient(90deg, rgba(255,255,255,0.028) 0, rgba(255,255,255,0.028) 1px, transparent 1px, transparent 86px)`;

export const SKIN_PACKS: Record<IterationTheme, SkinPack> = {
  determinex: {
    id: "determinex",
    label: "Determinex",
    shortLabel: "DX",
    cue: "emerald energy orbit",
    iconKey: "orbit",
    colors: {
      bg: "#020705",
      panel: "#06120b",
      panelStrong: "#0a1c11",
      panelGlass: "rgba(6, 18, 11, 0.88)",
      border: "rgba(53, 255, 138, 0.3)",
      accent: "#35ff8a",
      accent2: "#a0b0a8",
      accent3: "#ffffff",
      text: "#e8f5ec",
      muted: "#6d8274",
      danger: "#ff3f5f",
      accentGlow: "rgba(53, 255, 138, 0.5)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "12px",
    shellShadow: "0 0 38px rgba(53,255,138,0.18), 0 18px 80px rgba(0,0,0,0.72)",
    rainBackground: haze(
      "rgba(53,255,138,0.12)",
      "rgba(160,176,168,0.1)",
      "rgba(255,255,255,0.06)"
    ),
    rainOpacity: "0.5",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
  },
  codefall: {
    id: "codefall",
    label: "Codefall",
    shortLabel: "CF",
    cue: "digital rain systems",
    iconKey: "binary",
    colors: {
      bg: "#020604",
      panel: "#07100b",
      panelStrong: "#0a1710",
      panelGlass: "rgba(7, 16, 11, 0.88)",
      border: "rgba(42, 255, 129, 0.2)",
      accent: "#35ff8a",
      accent2: "#00e5ff",
      accent3: "#9cffcb",
      text: "#e9fff3",
      muted: "#6b8978",
      danger: "#ff3f5f",
      accentGlow: "rgba(53, 255, 138, 0.48)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: monoStack },
    radius: "12px",
    shellShadow: "0 0 38px rgba(53,255,138,0.18), 0 18px 80px rgba(0,0,0,0.72)",
    rainBackground: scan("rgba(53,255,138,0.08)", "rgba(53,255,138,0.045)"),
    rainOpacity: "0.52",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/codefall.png",
  },
  orbital: {
    id: "orbital",
    label: "Orbital HUD",
    shortLabel: "OH",
    cue: "belt-station telemetry",
    iconKey: "orbit",
    colors: {
      bg: "#05080b",
      panel: "#0b1117",
      panelStrong: "#101923",
      panelGlass: "rgba(11, 17, 23, 0.88)",
      border: "rgba(249, 185, 75, 0.22)",
      accent: "#f9b94b",
      accent2: "#53d7ff",
      accent3: "#ece6cc",
      text: "#f6f1dc",
      muted: "#7e8790",
      danger: "#ff5a47",
      accentGlow: "rgba(249,185,75,0.42)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "10px",
    shellShadow: "0 0 44px rgba(249,185,75,0.16), 0 20px 90px rgba(0,0,0,0.76)",
    rainBackground: haze("rgba(249,185,75,0.1)", "rgba(83,215,255,0.12)", "rgba(255,255,255,0.06)"),
    rainOpacity: "0.5",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/orbital.png",
  },
  neon: {
    id: "neon",
    label: "Neon Terminal",
    shortLabel: "NT",
    cue: "cyberdeck city glow",
    iconKey: "terminal",
    colors: {
      bg: "#07020a",
      panel: "#110817",
      panelStrong: "#190b22",
      panelGlass: "rgba(17, 8, 23, 0.88)",
      border: "rgba(255, 68, 205, 0.24)",
      accent: "#ff44cd",
      accent2: "#00e5ff",
      accent3: "#fff176",
      text: "#fff4fb",
      muted: "#92709a",
      danger: "#ff315a",
      accentGlow: "rgba(255,68,205,0.5)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: monoStack },
    radius: "14px",
    shellShadow: "0 0 46px rgba(255,68,205,0.2), 0 0 64px rgba(0,229,255,0.12)",
    rainBackground: haze("rgba(255,68,205,0.12)", "rgba(0,229,255,0.12)", "rgba(255,241,118,0.08)"),
    rainOpacity: "0.55",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/neon.png",
  },
  strategy: {
    id: "strategy",
    label: "Strategy Console",
    shortLabel: "SC",
    cue: "war-room amber grid",
    iconKey: "radar",
    colors: {
      bg: "#050703",
      panel: "#0d1007",
      panelStrong: "#151806",
      panelGlass: "rgba(13, 16, 7, 0.9)",
      border: "rgba(255, 176, 64, 0.22)",
      accent: "#ffb040",
      accent2: "#7cff6b",
      accent3: "#d7ff8a",
      text: "#fff2d3",
      muted: "#897c61",
      danger: "#ff4b3e",
      accentGlow: "rgba(255,176,64,0.44)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: monoStack },
    radius: "8px",
    shellShadow: "0 0 38px rgba(255,176,64,0.17), inset 0 0 0 1px rgba(255,255,255,0.02)",
    rainBackground: scan("rgba(255,176,64,0.1)", "rgba(124,255,107,0.04)"),
    rainOpacity: "0.42",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/strategy.png",
  },
  vector: {
    id: "vector",
    label: "Vector Grid",
    shortLabel: "VG",
    cue: "light-cycle vector plane",
    iconKey: "grid",
    colors: {
      bg: "#010714",
      panel: "#06101e",
      panelStrong: "#071a2e",
      panelGlass: "rgba(6, 16, 30, 0.88)",
      border: "rgba(0, 229, 255, 0.24)",
      accent: "#00e5ff",
      accent2: "#307cff",
      accent3: "#ffffff",
      text: "#eafaff",
      muted: "#66889a",
      danger: "#ff4d89",
      accentGlow: "rgba(0,229,255,0.46)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "10px",
    shellShadow: "0 0 48px rgba(0,229,255,0.18), 0 0 74px rgba(48,124,255,0.1)",
    rainBackground: scan("rgba(0,229,255,0.11)", "rgba(48,124,255,0.05)"),
    rainOpacity: "0.5",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/vector.png",
  },
  redlens: {
    id: "redlens",
    label: "Red Lens",
    shortLabel: "RL",
    cue: "single-lens machine room",
    iconKey: "lens",
    colors: {
      bg: "#090202",
      panel: "#150707",
      panelStrong: "#220909",
      panelGlass: "rgba(21, 7, 7, 0.9)",
      border: "rgba(255, 55, 55, 0.26)",
      accent: "#ff3737",
      accent2: "#ff9b63",
      accent3: "#fff2df",
      text: "#fff0f0",
      muted: "#9e6e6e",
      danger: "#ff3737",
      accentGlow: "rgba(255,55,55,0.55)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "10px",
    shellShadow: "0 0 48px rgba(255,55,55,0.24), 0 20px 90px rgba(0,0,0,0.8)",
    rainBackground: haze("rgba(255,55,55,0.11)", "rgba(255,155,99,0.1)", "rgba(255,255,255,0.05)"),
    rainOpacity: "0.46",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/redlens.png",
  },
  archive: {
    id: "archive",
    label: "Archive Core",
    shortLabel: "AC",
    cue: "industrial memory core",
    iconKey: "archive",
    colors: {
      bg: "#050604",
      panel: "#10110b",
      panelStrong: "#191909",
      panelGlass: "rgba(16, 17, 11, 0.9)",
      border: "rgba(191, 166, 90, 0.24)",
      accent: "#c9aa5a",
      accent2: "#8fffba",
      accent3: "#fff1c7",
      text: "#f4ecd2",
      muted: "#877d63",
      danger: "#ff694f",
      accentGlow: "rgba(201,170,90,0.38)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: monoStack },
    radius: "8px",
    shellShadow: "0 0 34px rgba(201,170,90,0.16), 0 18px 72px rgba(0,0,0,0.74)",
    rainBackground: scan("rgba(201,170,90,0.08)", "rgba(143,255,186,0.035)"),
    rainOpacity: "0.38",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/archive.png",
  },
  aegis: {
    id: "aegis",
    label: "Aegis Assistant",
    shortLabel: "AA",
    cue: "gold assistant HUD",
    iconKey: "assistant",
    colors: {
      bg: "#04080d",
      panel: "#08131b",
      panelStrong: "#0d1e29",
      panelGlass: "rgba(8, 19, 27, 0.88)",
      border: "rgba(255, 203, 92, 0.22)",
      accent: "#ffcb5c",
      accent2: "#62e6ff",
      accent3: "#ffffff",
      text: "#f7fbff",
      muted: "#788c99",
      danger: "#ff5c75",
      accentGlow: "rgba(255,203,92,0.42)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "14px",
    shellShadow: "0 0 42px rgba(255,203,92,0.17), 0 0 68px rgba(98,230,255,0.09)",
    rainBackground: haze("rgba(255,203,92,0.1)", "rgba(98,230,255,0.12)", "rgba(255,255,255,0.05)"),
    rainOpacity: "0.45",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/aegis.png",
  },
  terrain: {
    id: "terrain",
    label: "Terrain Navigator",
    shortLabel: "TN",
    cue: "prehistoric perimeter map",
    iconKey: "terrain",
    colors: {
      bg: "#040805",
      panel: "#0c1309",
      panelStrong: "#14200f",
      panelGlass: "rgba(12, 19, 9, 0.9)",
      border: "rgba(255, 198, 72, 0.22)",
      accent: "#ffc648",
      accent2: "#51d66f",
      accent3: "#e93e37",
      text: "#f4ffe7",
      muted: "#75836c",
      danger: "#e93e37",
      accentGlow: "rgba(255,198,72,0.43)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cinematicSans },
    radius: "8px",
    shellShadow: "0 0 40px rgba(255,198,72,0.16), 0 0 55px rgba(81,214,111,0.08)",
    rainBackground: haze("rgba(255,198,72,0.11)", "rgba(81,214,111,0.13)", "rgba(233,62,55,0.08)"),
    rainOpacity: "0.48",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/terrain.png",
  },
  raincity: {
    id: "raincity",
    label: "Rain City",
    shortLabel: "RC",
    cue: "wet neon alley glass",
    iconKey: "rain",
    colors: {
      bg: "#020711",
      panel: "#07101a",
      panelStrong: "#0d1725",
      panelGlass: "rgba(7, 16, 26, 0.88)",
      border: "rgba(91, 210, 255, 0.22)",
      accent: "#5bd2ff",
      accent2: "#ff5ac8",
      accent3: "#ffb84d",
      text: "#edf8ff",
      muted: "#6f7f90",
      danger: "#ff5470",
      accentGlow: "rgba(91,210,255,0.45)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cinematicSans },
    radius: "12px",
    shellShadow: "0 0 48px rgba(91,210,255,0.18), 0 0 70px rgba(255,90,200,0.09)",
    rainBackground: haze("rgba(91,210,255,0.12)", "rgba(255,90,200,0.1)", "rgba(255,184,77,0.08)"),
    rainOpacity: "0.58",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/raincity.png",
  },
  shelter: {
    id: "shelter",
    label: "Shelter Terminal",
    shortLabel: "ST",
    cue: "vault terminal amber",
    iconKey: "shield",
    colors: {
      bg: "#070604",
      panel: "#11100b",
      panelStrong: "#19160d",
      panelGlass: "rgba(17, 16, 11, 0.9)",
      border: "rgba(255, 190, 74, 0.22)",
      accent: "#ffbe4a",
      accent2: "#52ef8c",
      accent3: "#4ab3ff",
      text: "#fff4d8",
      muted: "#887c66",
      danger: "#ff6a45",
      accentGlow: "rgba(255,190,74,0.42)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: monoStack },
    radius: "8px",
    shellShadow: "0 0 36px rgba(255,190,74,0.17), 0 18px 78px rgba(0,0,0,0.75)",
    rainBackground: scan("rgba(255,190,74,0.09)", "rgba(82,239,140,0.035)"),
    rainOpacity: "0.4",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/shelter.png",
  },
  cave: {
    id: "cave",
    label: "Cave Console",
    shortLabel: "CV",
    cue: "stone room low light",
    iconKey: "cave",
    colors: {
      bg: "#050504",
      panel: "#0d0d0b",
      panelStrong: "#171612",
      panelGlass: "rgba(13, 13, 11, 0.91)",
      border: "rgba(190, 166, 124, 0.2)",
      accent: "#bea67c",
      accent2: "#5bd2c4",
      accent3: "#f17955",
      text: "#f1eadc",
      muted: "#837c6f",
      danger: "#f17955",
      accentGlow: "rgba(190,166,124,0.32)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cleanSans },
    radius: "10px",
    shellShadow: "0 0 32px rgba(190,166,124,0.13), 0 20px 80px rgba(0,0,0,0.78)",
    rainBackground: haze(
      "rgba(190,166,124,0.08)",
      "rgba(91,210,196,0.08)",
      "rgba(241,121,85,0.06)"
    ),
    rainOpacity: "0.34",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/cave.png",
  },
  aether: {
    id: "aether",
    label: "Aether Console",
    shortLabel: "AE",
    cue: "soft arcane interface",
    iconKey: "aether",
    colors: {
      bg: "#050512",
      panel: "#0d0d22",
      panelStrong: "#151433",
      panelGlass: "rgba(13, 13, 34, 0.88)",
      border: "rgba(183, 132, 255, 0.22)",
      accent: "#b784ff",
      accent2: "#6ce7ff",
      accent3: "#ffe28a",
      text: "#f5f0ff",
      muted: "#85779e",
      danger: "#ff5d83",
      accentGlow: "rgba(183,132,255,0.44)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "16px",
    shellShadow: "0 0 48px rgba(183,132,255,0.2), 0 0 74px rgba(108,231,255,0.08)",
    rainBackground: haze(
      "rgba(183,132,255,0.12)",
      "rgba(108,231,255,0.1)",
      "rgba(255,226,138,0.06)"
    ),
    rainOpacity: "0.48",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/aether.png",
  },
  endoframe: {
    id: "endoframe",
    label: "Endoframe HUD",
    shortLabel: "EF",
    cue: "red scan combat frame",
    iconKey: "frame",
    colors: {
      bg: "#070303",
      panel: "#130808",
      panelStrong: "#1d0b0b",
      panelGlass: "rgba(19, 8, 8, 0.9)",
      border: "rgba(255, 64, 64, 0.24)",
      accent: "#ff4040",
      accent2: "#9aa4ad",
      accent3: "#ffffff",
      text: "#fff1f1",
      muted: "#957373",
      danger: "#ff4040",
      accentGlow: "rgba(255,64,64,0.5)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: monoStack },
    radius: "6px",
    shellShadow: "0 0 46px rgba(255,64,64,0.22), inset 0 0 0 1px rgba(255,255,255,0.03)",
    rainBackground: scan("rgba(255,64,64,0.12)", "rgba(154,164,173,0.04)"),
    rainOpacity: "0.5",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/endoframe.png",
  },
  wraith: {
    id: "wraith",
    label: "Wraith Terminal",
    shortLabel: "WT",
    cue: "stealth ghost console",
    iconKey: "wraith",
    colors: {
      bg: "#03070a",
      panel: "#071014",
      panelStrong: "#0d171b",
      panelGlass: "rgba(7, 16, 20, 0.9)",
      border: "rgba(128, 216, 255, 0.18)",
      accent: "#80d8ff",
      accent2: "#a7b5c4",
      accent3: "#e7f8ff",
      text: "#eaf8ff",
      muted: "#6d818f",
      danger: "#ff6682",
      accentGlow: "rgba(128,216,255,0.34)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cleanSans },
    radius: "12px",
    shellShadow: "0 0 36px rgba(128,216,255,0.12), 0 22px 90px rgba(0,0,0,0.78)",
    rainBackground: haze(
      "rgba(128,216,255,0.08)",
      "rgba(167,181,196,0.08)",
      "rgba(255,255,255,0.045)"
    ),
    rainOpacity: "0.36",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/wraith.png",
  },
  ringarray: {
    id: "ringarray",
    label: "Ring Array",
    shortLabel: "RA",
    cue: "concentric signal array",
    iconKey: "ring",
    colors: {
      bg: "#04080d",
      panel: "#091019",
      panelStrong: "#101926",
      panelGlass: "rgba(9, 16, 25, 0.88)",
      border: "rgba(116, 228, 255, 0.2)",
      accent: "#74e4ff",
      accent2: "#ffcf70",
      accent3: "#eaffff",
      text: "#edfaff",
      muted: "#718695",
      danger: "#ff6b72",
      accentGlow: "rgba(116,228,255,0.38)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "999px",
    shellShadow: "0 0 42px rgba(116,228,255,0.16), 0 0 80px rgba(255,207,112,0.07)",
    rainBackground: haze(
      "rgba(116,228,255,0.1)",
      "rgba(255,207,112,0.08)",
      "rgba(234,255,255,0.05)"
    ),
    rainOpacity: "0.43",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/ringarray.png",
  },
  testchamber: {
    id: "testchamber",
    label: "Test Chamber",
    shortLabel: "TC",
    cue: "white lab and portal marks",
    iconKey: "test",
    colors: {
      bg: "#080a0c",
      panel: "#101418",
      panelStrong: "#171d22",
      panelGlass: "rgba(16, 20, 24, 0.88)",
      border: "rgba(230, 237, 243, 0.2)",
      accent: "#f5f7fa",
      accent2: "#ff9f2d",
      accent3: "#39c6ff",
      text: "#f8fbff",
      muted: "#8b98a5",
      danger: "#ff5c5c",
      accentGlow: "rgba(245,247,250,0.26)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cleanSans },
    radius: "6px",
    shellShadow: "0 0 36px rgba(245,247,250,0.1), 0 0 58px rgba(57,198,255,0.08)",
    rainBackground: haze(
      "rgba(245,247,250,0.08)",
      "rgba(255,159,45,0.08)",
      "rgba(57,198,255,0.08)"
    ),
    rainOpacity: "0.38",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/testchamber.png",
  },
  galaxyatlas: {
    id: "galaxyatlas",
    label: "Galaxy Atlas",
    shortLabel: "GA",
    cue: "star chart navigation",
    iconKey: "atlas",
    colors: {
      bg: "#030612",
      panel: "#080d1d",
      panelStrong: "#101733",
      panelGlass: "rgba(8, 13, 29, 0.88)",
      border: "rgba(125, 156, 255, 0.22)",
      accent: "#7d9cff",
      accent2: "#ffd36d",
      accent3: "#a977ff",
      text: "#f0f4ff",
      muted: "#77819f",
      danger: "#ff6684",
      accentGlow: "rgba(125,156,255,0.42)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "14px",
    shellShadow: "0 0 46px rgba(125,156,255,0.18), 0 0 78px rgba(169,119,255,0.08)",
    rainBackground: haze(
      "rgba(125,156,255,0.11)",
      "rgba(255,211,109,0.08)",
      "rgba(169,119,255,0.08)"
    ),
    rainOpacity: "0.48",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/galaxyatlas.png",
  },
  deepspace: {
    id: "deepspace",
    label: "Deep Space Signal",
    shortLabel: "DS",
    cue: "cold long-range signal",
    iconKey: "signal",
    colors: {
      bg: "#02050a",
      panel: "#060c14",
      panelStrong: "#0b1420",
      panelGlass: "rgba(6, 12, 20, 0.9)",
      border: "rgba(120, 190, 255, 0.2)",
      accent: "#78beff",
      accent2: "#ffffff",
      accent3: "#ff4a4a",
      text: "#edf6ff",
      muted: "#6a7d90",
      danger: "#ff4a4a",
      accentGlow: "rgba(120,190,255,0.34)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "12px",
    shellShadow: "0 0 38px rgba(120,190,255,0.13), 0 22px 90px rgba(0,0,0,0.8)",
    rainBackground: haze(
      "rgba(120,190,255,0.08)",
      "rgba(255,255,255,0.06)",
      "rgba(255,74,74,0.06)"
    ),
    rainOpacity: "0.36",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/deepspace.png",
  },
  dungeon: {
    id: "dungeon",
    label: "Dungeon Map",
    shortLabel: "DM",
    cue: "stone map and ember routes",
    iconKey: "dungeon",
    colors: {
      bg: "#070604",
      panel: "#11100c",
      panelStrong: "#1a1710",
      panelGlass: "rgba(17, 16, 12, 0.9)",
      border: "rgba(221, 177, 103, 0.22)",
      accent: "#ddb167",
      accent2: "#4ed8c7",
      accent3: "#f46b4d",
      text: "#f6ecd9",
      muted: "#897b6d",
      danger: "#f46b4d",
      accentGlow: "rgba(221,177,103,0.34)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cleanSans },
    radius: "8px",
    shellShadow: "0 0 34px rgba(221,177,103,0.14), 0 20px 82px rgba(0,0,0,0.78)",
    rainBackground: haze(
      "rgba(221,177,103,0.09)",
      "rgba(78,216,199,0.08)",
      "rgba(244,107,77,0.06)"
    ),
    rainOpacity: "0.37",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/dungeon.png",
  },
  mechbay: {
    id: "mechbay",
    label: "Mech Bay",
    shortLabel: "MB",
    cue: "gunmetal ship-ops bay",
    iconKey: "mech",
    colors: {
      bg: "#050709",
      panel: "#0b1014",
      panelStrong: "#121a20",
      panelGlass: "rgba(11, 16, 20, 0.9)",
      border: "rgba(255, 137, 64, 0.22)",
      accent: "#ff8940",
      accent2: "#74d7ff",
      accent3: "#e9eef2",
      text: "#f3f7fa",
      muted: "#77828a",
      danger: "#ff4f55",
      accentGlow: "rgba(255,137,64,0.42)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cleanSans },
    radius: "6px",
    shellShadow: "0 0 40px rgba(255,137,64,0.17), 0 0 58px rgba(116,215,255,0.08)",
    rainBackground: scan("rgba(255,137,64,0.09)", "rgba(116,215,255,0.04)"),
    rainOpacity: "0.44",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/skins/mechbay.png",
  },
  rocinante: {
    id: "rocinante",
    label: "Rocinante",
    shortLabel: "RC",
    cue: "belt-runner hull systems",
    iconKey: "orbit",
    colors: {
      bg: "#040508",
      panel: "#080c14",
      panelStrong: "#0e1420",
      panelGlass: "rgba(8, 12, 20, 0.9)",
      border: "rgba(224, 124, 58, 0.26)",
      accent: "#e07c3a",
      accent2: "#6aa4c8",
      accent3: "#d4dde8",
      text: "#dde6f0",
      muted: "#6b7d90",
      danger: "#e05050",
      accentGlow: "rgba(224,124,58,0.38)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "10px",
    shellShadow: "0 0 44px rgba(224,124,58,0.18), 0 20px 90px rgba(0,0,0,0.82)",
    rainBackground: haze(
      "rgba(224,124,58,0.09)",
      "rgba(106,164,200,0.09)",
      "rgba(255,255,255,0.04)"
    ),
    rainOpacity: "0.4",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/rocinante.png",
  },
  lightcycle: {
    id: "lightcycle",
    label: "Lightcycle",
    shortLabel: "LC",
    cue: "grid runner light trail",
    iconKey: "grid",
    colors: {
      bg: "#010208",
      panel: "#04071a",
      panelStrong: "#070c28",
      panelGlass: "rgba(4, 7, 26, 0.92)",
      border: "rgba(0, 229, 255, 0.3)",
      accent: "#00e5ff",
      accent2: "#ff7d00",
      accent3: "#ffffff",
      text: "#e0f8ff",
      muted: "#5e808e",
      danger: "#ff3c5f",
      accentGlow: "rgba(0,229,255,0.55)",
    },
    fonts: { sans: cinematicSans, mono: monoStack, display: cinematicSans },
    radius: "4px",
    shellShadow: "0 0 60px rgba(0,229,255,0.22), 0 0 100px rgba(0,229,255,0.08)",
    rainBackground: scan("rgba(0,229,255,0.14)", "rgba(255,125,0,0.05)"),
    rainOpacity: "0.62",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/lightcycle.png",
  },
  trex: {
    id: "trex",
    label: "T-Rex",
    shortLabel: "TR",
    cue: "apex predator pursuit mode",
    iconKey: "terrain",
    colors: {
      bg: "#020804",
      panel: "#060f08",
      panelStrong: "#0c180e",
      panelGlass: "rgba(6, 15, 8, 0.92)",
      border: "rgba(40, 220, 100, 0.22)",
      accent: "#28dc64",
      accent2: "#8b1a1a",
      accent3: "#c8f5d2",
      text: "#e0f5e4",
      muted: "#63866b",
      danger: "#cc2222",
      accentGlow: "rgba(40,220,100,0.42)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cinematicSans },
    radius: "8px",
    shellShadow: "0 0 46px rgba(40,220,100,0.16), 0 20px 90px rgba(0,0,0,0.84)",
    rainBackground: haze("rgba(40,220,100,0.1)", "rgba(139,26,26,0.08)", "rgba(200,245,210,0.04)"),
    rainOpacity: "0.46",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
    backdropImage: "/trex.png",
  },
  plaindark: {
    id: "plaindark",
    label: "Plain Dark",
    shortLabel: "PD",
    cue: "quiet dark IDE",
    iconKey: "plainDark",
    colors: {
      bg: "#070b10",
      panel: "#0d1117",
      panelStrong: "#111821",
      panelGlass: "rgba(13, 17, 23, 0.9)",
      border: "rgba(48, 54, 61, 0.9)",
      accent: "#8bb6ff",
      accent2: "#9ae6b4",
      accent3: "#e6edf3",
      text: "#e6edf3",
      muted: "#7d8590",
      danger: "#ff6b6b",
      accentGlow: "rgba(139,182,255,0.24)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cleanSans },
    radius: "8px",
    shellShadow: "0 18px 80px rgba(0,0,0,0.72)",
    rainBackground: haze(
      "rgba(139,182,255,0.06)",
      "rgba(154,230,180,0.05)",
      "rgba(255,255,255,0.035)"
    ),
    rainOpacity: "0.28",
    rainBlend: "screen",
    logoFilter: "grayscale(1) contrast(1.15)",
  },
  plainlight: {
    id: "plainlight",
    label: "Plain Light",
    shortLabel: "PL",
    cue: "clear light IDE",
    iconKey: "plainLight",
    colors: {
      bg: "#f7f9fc",
      panel: "#ffffff",
      panelStrong: "#eef3f8",
      panelGlass: "rgba(255, 255, 255, 0.9)",
      border: "rgba(137, 150, 165, 0.34)",
      accent: "#246bfe",
      accent2: "#0f9f78",
      accent3: "#4c5563",
      text: "#172033",
      muted: "#657085",
      danger: "#c9364f",
      accentGlow: "rgba(36,107,254,0.22)",
    },
    fonts: { sans: cleanSans, mono: monoStack, display: cleanSans },
    radius: "8px",
    shellShadow: "0 18px 60px rgba(32,44,68,0.16)",
    rainBackground: haze("rgba(36,107,254,0.08)", "rgba(15,159,120,0.06)", "rgba(76,85,99,0.04)"),
    rainOpacity: "0.26",
    rainBlend: "multiply",
    logoFilter: "grayscale(0.5) contrast(1.08)",
  },
};

export const DEFAULT_SKIN_PACK = SKIN_PACKS.determinex;

export function getSkinPackStyle(pack: SkinPack): SkinPackStyle {
  return {
    // Code-surface + semantic tokens, derived from this skin. Spread first so an explicit
    // --determinex-* below always wins over a derived value.
    ...getCodeLayerStyle(pack),
    "--determinex-bg": pack.colors.bg,
    "--determinex-panel": pack.colors.panel,
    "--determinex-panel-strong": pack.colors.panelStrong,
    "--determinex-panel-glass": pack.colors.panelGlass,
    "--determinex-border": pack.colors.border,
    "--determinex-accent": pack.colors.accent,
    "--determinex-accent-2": pack.colors.accent2,
    "--determinex-accent-3": pack.colors.accent3,
    "--determinex-text": pack.colors.text,
    "--determinex-muted": pack.colors.muted,
    "--determinex-danger": pack.colors.danger,
    "--determinex-accent-glow": pack.colors.accentGlow,
    "--determinex-font-sans": pack.fonts.sans,
    "--determinex-font-mono": pack.fonts.mono,
    "--determinex-font-display": pack.fonts.display,
    "--determinex-radius": pack.radius,
    "--determinex-shell-shadow": pack.shellShadow,
    "--determinex-rain-bg": pack.rainBackground,
    "--determinex-rain-opacity": pack.rainOpacity,
    "--determinex-rain-blend": pack.rainBlend,
    "--determinex-logo-filter": pack.logoFilter,
  };
}
