"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "e-sentinel-theme";

type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY) as Theme | null;
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* ignore */
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export default function ThemeToggle({
  className,
}: {
  className?: string;
}) {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setTheme(getInitialTheme());
    setMounted(true);
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    document.documentElement.classList.toggle("dark", next === "dark");
  };

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "切换到浅色模式" : "切换到深色模式"}
      title={isDark ? "浅色模式" : "深色模式"}
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground/70 transition-colors",
        "hover:bg-sidebar-accent hover:text-sidebar-foreground",
        className
      )}
    >
      {mounted ? (
        isDark ? (
          <Sun className="h-3.5 w-3.5" strokeWidth={2} />
        ) : (
          <Moon className="h-3.5 w-3.5" strokeWidth={2} />
        )
      ) : (
        <Sun className="h-3.5 w-3.5 opacity-0" strokeWidth={2} />
      )}
    </button>
  );
}
