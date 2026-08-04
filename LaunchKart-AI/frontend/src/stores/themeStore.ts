"use client";

import { create } from "zustand";

type ThemeMode = "dark" | "light" | "system";

interface ThemeState {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  initTheme: () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: "dark", // Default to dark for AMD Radeon cyber aesthetic
  setTheme: (theme: ThemeMode) => {
    set({ theme });
    if (typeof window !== "undefined") {
      localStorage.setItem("launchkart-theme", theme);
      const root = document.documentElement;
      root.classList.remove("light", "dark");

      if (theme === "system") {
        const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        root.classList.add(systemDark ? "dark" : "light");
      } else {
        root.classList.add(theme);
      }
    }
  },
  initTheme: () => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("launchkart-theme") as ThemeMode | null;
      const themeToSet = saved || "dark";
      get().setTheme(themeToSet);
    }
  },
}));
