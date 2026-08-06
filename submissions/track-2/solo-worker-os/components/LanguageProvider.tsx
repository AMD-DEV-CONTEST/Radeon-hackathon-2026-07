'use client';

import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';
import { translations, type Lang, type TranslationDict } from '@/lib/i18n';

interface LangCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: TranslationDict;
}

const Ctx = createContext<LangCtx | null>(null);

export function LanguageProvider({
  children,
  initialLang = 'zh',
}: {
  children: ReactNode;
  initialLang?: Lang;
}) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  // Sync with cookie on mount (covers SSR cookie + multi-tab scenarios)
  useEffect(() => {
    const cookieMatch = document.cookie.match(/solo-lang=(en|zh)/);
    const saved = cookieMatch?.[1] as Lang | undefined;
    if (saved && saved !== lang) setLangState(saved);

    // Cross-tab sync: listen for storage events from other tabs
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'solo-lang' && (e.newValue === 'en' || e.newValue === 'zh')) {
        setLangState(e.newValue);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem('solo-lang', l); } catch { /* */ }
    document.cookie = `solo-lang=${l};path=/;max-age=31536000`;
    // No router.refresh() — language state is managed client-side.
    // Translations update instantly via context; server components pick up
    // the new cookie on the next navigation. This avoids a full-page
    // server re-render on every language toggle.
  }, []);

  return (
    <Ctx.Provider value={{ lang, setLang, t: translations[lang] }}>
      {children}
    </Ctx.Provider>
  );
}

export function useLang(): LangCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useLang must be used within LanguageProvider');
  return ctx;
}
