'use client';

import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';

type Theme = 'light' | 'dark';

interface ThemeCtx {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
}

const Ctx = createContext<ThemeCtx | null>(null);

export function ThemeProvider({
  children,
  initialTheme = 'light',
}: {
  children: ReactNode;
  initialTheme?: Theme;
}) {
  const [theme, setThemeState] = useState<Theme>(initialTheme);
  const [mounted, setMounted] = useState(false);

  // Sync with localStorage on mount
  useEffect(() => {
    setMounted(true);
    try {
      const saved = localStorage.getItem('solo-theme') as Theme | null;
      if (saved && (saved === 'light' || saved === 'dark')) {
        setThemeState(saved);
      }
    } catch { /* */ }

    // Cross-tab sync
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'solo-theme' && (e.newValue === 'light' || e.newValue === 'dark')) {
        setThemeState(e.newValue);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // Apply theme class to <html>
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem('solo-theme', t); } catch { /* */ }
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('solo-theme', next); } catch { /* */ }
      return next;
    });
  }, []);

  return (
    <Ctx.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </Ctx.Provider>
  );
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
