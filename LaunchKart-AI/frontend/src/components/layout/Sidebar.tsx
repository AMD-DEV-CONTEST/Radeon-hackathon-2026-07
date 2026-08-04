"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Database, Activity, GitCompare, Settings, ShieldCheck } from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  const links = [
    { href: "/dashboard", label: "Product Studio & AI", icon: <LayoutDashboard className="w-5 h-5" /> },
    { href: "/marketplace", label: "Syndication Feeds", icon: <GitCompare className="w-5 h-5" /> },
    { href: "/memory", label: "Vector Memory Bank", icon: <Database className="w-5 h-5" /> },
    { href: "/benchmark", label: "ROCm Benchmarks", icon: <Activity className="w-5 h-5" /> },
    { href: "/settings", label: "Settings & Hardware", icon: <Settings className="w-5 h-5" /> },
  ];

  return (
    <aside className="w-64 border-r border-[var(--color-border)] bg-[var(--color-surface)] flex flex-col h-screen fixed left-0 top-0 z-50 transition-colors duration-200">
      <div className="h-16 flex items-center justify-between px-6 border-b border-[var(--color-border)]">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-red-600 to-red-500 flex items-center justify-center text-white font-black text-base shadow-lg shadow-red-500/25">
            LK
          </div>
          <span className="font-extrabold text-lg tracking-tight text-[var(--color-foreground)]">
            LaunchKart <span className="text-red-500 font-black">AI</span>
          </span>
        </Link>
        <span className="text-[10px] uppercase px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-500 border border-emerald-500/30 font-bold shadow-sm">
          PRO v2.5
        </span>
      </div>

      <div className="px-4 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface-hover)]/40 backdrop-blur-md">
        <div className="flex items-center gap-2.5 text-xs text-[var(--color-muted)] font-medium">
          <ShieldCheck className="w-4 h-4 text-emerald-500 shrink-0" />
          <div className="truncate">
            <span className="text-[var(--color-foreground)] font-bold block tracking-tight">Enterprise AI Cluster</span>
            <span className="text-[11px] text-neutral-400">ROCm 6.1 • 15 Autonomous Agents</span>
          </div>
        </div>
      </div>
      
      <nav className="flex-1 py-5 px-3 space-y-1.5 overflow-y-auto">
        <div className="px-3 pb-2 text-[11px] font-bold uppercase tracking-wider text-[var(--color-muted)]">
          AI Product & SEO Studio
        </div>
        {links.map((link) => {
          const isActive = pathname === link.href || pathname?.startsWith(`${link.href}/`);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center space-x-3 px-3.5 py-2.5 rounded-xl font-semibold text-sm transition-all duration-150 group ${
                isActive
                  ? "bg-red-500/15 text-red-500 font-bold shadow-sm border border-red-500/30"
                  : "text-[var(--color-foreground)] hover:bg-[var(--color-surface-hover)] hover:text-red-400"
              }`}
            >
              <div className={isActive ? "text-red-500" : "text-[var(--color-muted)] group-hover:text-red-400 transition-colors"}>
                {link.icon}
              </div>
              <span>{link.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-[var(--color-border)] bg-[var(--color-surface-hover)]/30 backdrop-blur-md">
        <div className="flex flex-col space-y-1.5 text-xs text-[var(--color-muted)]">
          <div className="flex items-center justify-between">
            <span className="font-medium text-[11px] text-neutral-400">Hardware Acceleration:</span>
            <span className="font-bold text-white text-[11px]">AMD Radeon GPU</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-medium text-[11px] text-neutral-400">Pipeline Status:</span>
            <span className="text-emerald-500 font-bold text-[11px] flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span> Synchronized
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
