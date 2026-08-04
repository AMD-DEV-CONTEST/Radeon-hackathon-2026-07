"use client";

import { useState, useEffect } from "react";
import { Bell, Search, User, CheckCircle, Sun, Moon, Laptop, Shield, Cpu } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useRouter } from "next/navigation";
import { useThemeStore } from "@/stores/themeStore";

export function Header() {
  const [searchQuery, setSearchQuery] = useState("");
  const [showNotifications, setShowNotifications] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showThemeMenu, setShowThemeMenu] = useState(false);
  const router = useRouter();

  const { theme, setTheme, initTheme } = useThemeStore();

  useEffect(() => {
    initTheme();
  }, [initTheme]);

  const handleSearch = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && searchQuery.trim()) {
      router.push(`/memory?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  return (
    <header className="h-16 border-b border-[var(--color-border)] bg-[var(--color-surface)]/80 backdrop-blur-md sticky top-0 z-40 flex items-center justify-between px-6 pl-72 transition-colors duration-200">
      <div className="flex items-center w-96 bg-[var(--color-surface-hover)] rounded-md px-3 py-1.5 border border-[var(--color-border)] focus-within:ring-2 ring-[var(--color-brand-primary)] transition-all">
        <Search className="w-4 h-4 text-[var(--color-muted)] mr-2" />
        <input 
          type="text" 
          placeholder="Search catalogs, pipelines, or logs (Press Enter)..." 
          className="bg-transparent border-none outline-none text-sm w-full text-[var(--color-foreground)] placeholder-[var(--color-muted)]"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={handleSearch}
        />
      </div>

      <div className="flex items-center space-x-3 relative">
        {/* AMD Radeon Compute Cluster Indicator */}
        <div className="flex items-center space-x-2.5 text-xs mr-2 px-3.5 py-1.5 rounded-full bg-gradient-to-r from-red-500/15 to-orange-500/15 text-red-400 border border-red-500/30 backdrop-blur-md shadow-[0_0_15px_rgba(237,28,36,0.15)]">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
          </span>
          <Cpu className="w-3.5 h-3.5 inline text-red-500" />
          <span className="font-semibold tracking-wide">AMD ROCm 6.1 Hardware Online</span>
        </div>

        {/* Theme Switcher Toggle */}
        <div className="relative">
          <Button
            variant="ghost"
            size="icon"
            className="rounded-full bg-[var(--color-surface-hover)] border border-[var(--color-border)] text-[var(--color-foreground)] hover:text-[var(--color-brand-primary)]"
            onClick={() => { setShowThemeMenu(!showThemeMenu); setShowNotifications(false); setShowProfile(false); }}
            title="Toggle Theme Mode"
          >
            {theme === "light" ? (
              <Sun className="w-5 h-5 text-amber-500" />
            ) : theme === "dark" ? (
              <Moon className="w-5 h-5 text-blue-400" />
            ) : (
              <Laptop className="w-5 h-5 text-gray-400" />
            )}
          </Button>

          {showThemeMenu && (
            <div className="absolute right-0 mt-2 w-44 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl shadow-2xl p-2 z-50 text-left space-y-1">
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-muted)] px-2 py-1">
                Theme Preference
              </div>
              <button
                onClick={() => { setTheme("light"); setShowThemeMenu(false); }}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                  theme === "light"
                    ? "bg-[var(--color-brand-primary)]/15 text-[var(--color-brand-primary)] font-bold"
                    : "text-[var(--color-foreground)] hover:bg-[var(--color-surface-hover)]"
                }`}
              >
                <Sun className="w-4 h-4 text-amber-500" /> Light Mode
              </button>
              <button
                onClick={() => { setTheme("dark"); setShowThemeMenu(false); }}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                  theme === "dark"
                    ? "bg-[var(--color-brand-primary)]/15 text-[var(--color-brand-primary)] font-bold"
                    : "text-[var(--color-foreground)] hover:bg-[var(--color-surface-hover)]"
                }`}
              >
                <Moon className="w-4 h-4 text-blue-400" /> Dark Mode
              </button>
              <button
                onClick={() => { setTheme("system"); setShowThemeMenu(false); }}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                  theme === "system"
                    ? "bg-[var(--color-brand-primary)]/15 text-[var(--color-brand-primary)] font-bold"
                    : "text-[var(--color-foreground)] hover:bg-[var(--color-surface-hover)]"
                }`}
              >
                <Laptop className="w-4 h-4 text-gray-400" /> System Default
              </button>
            </div>
          )}
        </div>

        {/* Notifications Button */}
        <div className="relative">
          <Button 
            variant="ghost" 
            size="icon" 
            className="rounded-full relative bg-[var(--color-surface-hover)] border border-[var(--color-border)] text-[var(--color-foreground)]"
            onClick={() => { setShowNotifications(!showNotifications); setShowProfile(false); setShowThemeMenu(false); }}
            title="System Notifications"
          >
            <Bell className="w-5 h-5" />
            <span className="absolute top-1 right-1 w-2 h-2 bg-[var(--color-brand-primary)] rounded-full animate-pulse" />
          </Button>

          {showNotifications && (
            <div className="absolute right-0 mt-2 w-80 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl shadow-2xl p-4 z-50 text-left">
              <h4 className="font-bold text-sm mb-2 flex items-center gap-2 text-[var(--color-foreground)]">
                <Bell className="w-4 h-4 text-[var(--color-brand-primary)]" />
                System Telemetry & Alerts
              </h4>
              <div className="space-y-2 text-xs text-[var(--color-muted)]">
                <div className="p-2.5 bg-[var(--color-surface-hover)] rounded-lg flex items-start gap-2 border border-[var(--color-border)]">
                  <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-[var(--color-foreground)] block">ROCm Hardware Verified</strong>
                    AMD Radeon RX 7900 XTX detected & ready for high-throughput pipeline processing.
                  </div>
                </div>
                <div className="p-2.5 bg-[var(--color-surface-hover)] rounded-lg flex items-start gap-2 border border-[var(--color-border)]">
                  <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-[var(--color-foreground)] block">Distributed Storage Active</strong>
                    ChromaDB tiered vector memory caching is online.
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* User Profile Button */}
        <div className="relative">
          <Button 
            variant="ghost" 
            size="icon" 
            className="rounded-full bg-[var(--color-surface-hover)] border border-[var(--color-border)] text-[var(--color-foreground)]"
            onClick={() => { setShowProfile(!showProfile); setShowNotifications(false); setShowThemeMenu(false); }}
            title="User Profile"
          >
            <User className="w-5 h-5" />
          </Button>

          {showProfile && (
            <div className="absolute right-0 mt-2 w-64 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl shadow-2xl p-4 z-50 text-left">
              <div className="flex items-center space-x-3 mb-3 pb-3 border-b border-[var(--color-border)]">
                <div className="w-10 h-10 rounded-full bg-[var(--color-brand-primary)]/10 text-[var(--color-brand-primary)] flex items-center justify-center font-bold text-lg border border-[var(--color-brand-primary)]/30">
                  EA
                </div>
                <div>
                  <h4 className="font-bold text-sm text-[var(--color-foreground)] flex items-center gap-1">
                    Enterprise Admin <Shield className="w-3.5 h-3.5 text-emerald-500 inline" />
                  </h4>
                  <p className="text-xs text-[var(--color-muted)]">admin@launchkart.enterprise</p>
                </div>
              </div>
              <div className="text-xs space-y-2 font-medium text-[var(--color-muted)]">
                <div className="flex justify-between">
                  <span>Role:</span>
                  <span className="text-[var(--color-brand-primary)] font-bold">Systems Architect</span>
                </div>
                <div className="flex justify-between">
                  <span>Compute Node:</span>
                  <span className="text-emerald-500 font-bold">ROCm Dedicated</span>
                </div>
                <div className="flex justify-between">
                  <span>Pipeline Sync:</span>
                  <span className="text-emerald-500">Active (15 Workers)</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
