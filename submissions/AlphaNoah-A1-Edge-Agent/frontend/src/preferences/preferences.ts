export type Locale = "zh-CN" | "en-US";
export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";
export type MotionPreference = "standard" | "reduced";

export interface Preferences {
  locale: Locale;
  theme: ThemePreference;
  motion: MotionPreference;
}

export const PREFERENCES_STORAGE_KEY = "alphanoah.preferences.v1";

const locales: readonly Locale[] = ["zh-CN", "en-US"];
const themes: readonly ThemePreference[] = ["system", "light", "dark"];
const motions: readonly MotionPreference[] = ["standard", "reduced"];

function includesValue<T extends string>(
  values: readonly T[],
  value: unknown,
): value is T {
  return typeof value === "string" && values.includes(value as T);
}

export function detectBrowserLocale(language = navigator.language): Locale {
  return language.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US";
}

export function detectSystemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function detectMotionPreference(): MotionPreference {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "reduced"
    : "standard";
}

export function resolveTheme(
  preference: ThemePreference,
  systemTheme: ResolvedTheme,
): ResolvedTheme {
  return preference === "system" ? systemTheme : preference;
}

export function readStoredPreferences(
  storage: Pick<Storage, "getItem"> = window.localStorage,
): Partial<Preferences> {
  try {
    const rawValue = storage.getItem(PREFERENCES_STORAGE_KEY);
    if (!rawValue) {
      return {};
    }

    const candidate: unknown = JSON.parse(rawValue);
    if (!candidate || typeof candidate !== "object") {
      return {};
    }

    const value = candidate as Record<string, unknown>;
    return {
      ...(includesValue(locales, value.locale)
        ? { locale: value.locale }
        : {}),
      ...(includesValue(themes, value.theme)
        ? { theme: value.theme }
        : {}),
      ...(includesValue(motions, value.motion)
        ? { motion: value.motion }
        : {}),
    };
  } catch {
    return {};
  }
}

export function getInitialPreferences(): Preferences {
  const stored = readStoredPreferences();

  return {
    locale: stored.locale ?? detectBrowserLocale(),
    theme: stored.theme ?? "system",
    motion: stored.motion ?? detectMotionPreference(),
  };
}
