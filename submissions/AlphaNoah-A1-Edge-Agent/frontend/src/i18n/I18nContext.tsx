import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  type PropsWithChildren,
} from "react";

import type { ViewText } from "../features/runtime";
import { usePreferences } from "../preferences/PreferencesContext";
import { messages, type TranslationKey } from "./messages";

interface I18nContextValue {
  locale: "zh-CN" | "en-US";
  t: (key: TranslationKey) => string;
  text: (value: ViewText) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: PropsWithChildren) {
  const {
    preferences: { locale },
  } = usePreferences();

  const value = useMemo<I18nContextValue>(
    () => {
      const catalog: Readonly<Record<string, string>> =
        messages[locale];
      return {
        locale,
        t: (key) => messages[locale][key],
        text: (textValue) =>
          textValue.kind === "literal"
            ? textValue.value
            : (catalog[textValue.id] ?? textValue.id),
      };
    },
    [locale],
  );

  useEffect(() => {
    document.title = value.t("meta.title");
    const description = document.querySelector<HTMLMetaElement>(
      'meta[name="description"]',
    );
    description?.setAttribute("content", value.t("meta.description"));
  }, [value]);

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error("useI18n must be used inside I18nProvider");
  }

  return value;
}
