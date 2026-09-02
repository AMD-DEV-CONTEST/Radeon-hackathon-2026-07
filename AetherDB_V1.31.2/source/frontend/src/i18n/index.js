import { ref } from "vue";
import { createI18n } from "vue-i18n";
import enUS from "./messages/en-US.js";


export const LOCALE_STORAGE_KEY = "aetherdb_locale";
export const SUPPORTED_LOCALES = Object.freeze(["zh-CN", "en-US"]);

const zhCN = Object.fromEntries(Object.keys(enUS).map((key) => [key, key]));

function browserStorage() {
  return typeof localStorage === "undefined" ? null : localStorage;
}

export function normalizeLocale(value) {
  if (typeof value !== "string") return null;
  const normalized = value.trim().replace("_", "-").toLowerCase();
  if (normalized === "zh" || normalized === "zh-cn" || normalized === "zh-hans") {
    return "zh-CN";
  }
  if (normalized === "en" || normalized === "en-us") return "en-US";
  return null;
}

export function resolvePersistedLocale(storage = browserStorage()) {
  if (!storage) return null;
  try {
    return normalizeLocale(storage.getItem(LOCALE_STORAGE_KEY));
  } catch {
    return null;
  }
}

const persistedLocale = resolvePersistedLocale();
const initialLocale = persistedLocale || "zh-CN";

export const localeSelectionRequired = ref(!persistedLocale);
export const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: false,
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    "zh-CN": zhCN,
    "en-US": enUS,
  },
  missing: (_locale, key) => key,
});

function applyDocumentLocale(locale) {
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }
}

applyDocumentLocale(initialLocale);

export function setLocale(value, { persist = true } = {}) {
  const locale = normalizeLocale(value);
  if (!locale) throw new TypeError("Unsupported AetherDB locale");
  i18n.global.locale.value = locale;
  applyDocumentLocale(locale);
  if (persist) {
    const storage = browserStorage();
    try {
      storage?.setItem(LOCALE_STORAGE_KEY, locale);
    } catch {
      // The selected locale remains active for this process if storage is unavailable.
    }
  }
  localeSelectionRequired.value = false;
  return locale;
}

export function translate(key, params) {
  return i18n.global.t(key, params);
}

export function currentLocale() {
  return i18n.global.locale.value;
}
