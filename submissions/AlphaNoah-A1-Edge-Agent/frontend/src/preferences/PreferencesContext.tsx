import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";

import {
  getInitialPreferences,
  PREFERENCES_STORAGE_KEY,
  resolveTheme,
  type Locale,
  type MotionPreference,
  type Preferences,
  type ResolvedTheme,
  type ThemePreference,
} from "./preferences";

interface PreferencesContextValue {
  preferences: Preferences;
  resolvedTheme: ResolvedTheme;
  setLocale: (locale: Locale) => void;
  setTheme: (theme: ThemePreference) => void;
  setMotion: (motion: MotionPreference) => void;
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

export function PreferencesProvider({ children }: PropsWithChildren) {
  const [preferences, setPreferences] = useState(getInitialPreferences);
  const [systemTheme, setSystemTheme] =
    useState<ResolvedTheme>(() =>
      window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light",
    );

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (event: MediaQueryListEvent) => {
      setSystemTheme(event.matches ? "dark" : "light");
    };

    setSystemTheme(media.matches ? "dark" : "light");
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  const resolvedTheme = resolveTheme(preferences.theme, systemTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.lang = preferences.locale;
    root.dataset.theme = resolvedTheme;
    root.dataset.themePreference = preferences.theme;
    root.dataset.motion = preferences.motion;
    window.localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify(preferences),
    );
  }, [preferences, resolvedTheme]);

  const value = useMemo<PreferencesContextValue>(
    () => ({
      preferences,
      resolvedTheme,
      setLocale: (locale) =>
        setPreferences((current) => ({ ...current, locale })),
      setTheme: (theme) =>
        setPreferences((current) => ({ ...current, theme })),
      setMotion: (motion) =>
        setPreferences((current) => ({ ...current, motion })),
    }),
    [preferences, resolvedTheme],
  );

  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences(): PreferencesContextValue {
  const value = useContext(PreferencesContext);
  if (!value) {
    throw new Error("usePreferences must be used inside PreferencesProvider");
  }

  return value;
}
