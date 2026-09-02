"use client";
import React, { createContext, useContext, useState, useEffect } from "react";
import { DEFAULT_SKIN_PACK, SKIN_PACKS, type SkinPack } from "@/theme/skinPacks";

export type IterationTheme =
  | "determinex"
  | "codefall"
  | "orbital"
  | "neon"
  | "strategy"
  | "vector"
  | "redlens"
  | "archive"
  | "aegis"
  | "terrain"
  | "raincity"
  | "shelter"
  | "cave"
  | "aether"
  | "endoframe"
  | "wraith"
  | "ringarray"
  | "testchamber"
  | "galaxyatlas"
  | "deepspace"
  | "dungeon"
  | "mechbay"
  | "rocinante"
  | "lightcycle"
  | "trex"
  | "plaindark"
  | "plainlight";

export const THEME_LABELS: Record<IterationTheme, string> = {
  determinex: "Determinex",
  codefall: "Codefall",
  orbital: "Orbital HUD",
  neon: "Neon Terminal",
  strategy: "Strategy Console",
  vector: "Vector Grid",
  redlens: "Red Lens",
  archive: "Archive Core",
  aegis: "Aegis Assistant",
  terrain: "Terrain Navigator",
  raincity: "Rain City",
  shelter: "Shelter Terminal",
  cave: "Cave Console",
  aether: "Aether Console",
  endoframe: "Endoframe HUD",
  wraith: "Wraith Terminal",
  ringarray: "Ring Array",
  testchamber: "Test Chamber",
  galaxyatlas: "Galaxy Atlas",
  deepspace: "Deep Space Signal",
  dungeon: "Dungeon Map",
  mechbay: "Mech Bay",
  rocinante: "Rocinante",
  lightcycle: "Lightcycle",
  trex: "T-Rex",
  plaindark: "Plain Dark",
  plainlight: "Plain Light",
};

const STORAGE_KEY = "determinex_iteration_theme";

interface ThemeContextValue {
  theme: IterationTheme;
  setTheme: (t: IterationTheme) => void;
  themeLabel: string;
  themePack: SkinPack;
  allThemes: IterationTheme[];
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "determinex",
  setTheme: () => {},
  themeLabel: "Determinex",
  themePack: DEFAULT_SKIN_PACK,
  allThemes: Object.keys(THEME_LABELS) as IterationTheme[],
});

export function IterationThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<IterationTheme>("determinex");

  useEffect(() => {
    const legacy: Record<string, IterationTheme> = {
      matrix: "codefall",
      belta: "orbital",
      gibson: "neon",
      wargames: "strategy",
      tron: "vector",
      hal9000: "redlens",
      muthur: "archive",
      jarvis: "aegis",
      jurassic: "terrain",
      bladerunner: "raincity",
    };
    const stored = localStorage.getItem(STORAGE_KEY);
    const migrated = stored ? (legacy[stored] ?? stored) : null;
    if (migrated && migrated in THEME_LABELS) setThemeState(migrated as IterationTheme);
  }, []);

  const setTheme = (t: IterationTheme) => {
    setThemeState(t);
    localStorage.setItem(STORAGE_KEY, t);
  };

  return (
    <ThemeContext.Provider
      value={{
        theme,
        setTheme,
        themeLabel: THEME_LABELS[theme],
        themePack: SKIN_PACKS[theme] ?? DEFAULT_SKIN_PACK,
        allThemes: Object.keys(THEME_LABELS) as IterationTheme[],
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useIterationTheme() {
  return useContext(ThemeContext);
}
