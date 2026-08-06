"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { DashboardTab } from "@/components/dashboard/SidebarNav";
import { TAB_GROUPS } from "@/components/dashboard/SidebarNav";
import type { Role } from "@/lib/rbac";
import { canAccessMenu } from "@/lib/rbac";
import {
  ShieldCheck,
  Bot,
  BookOpen,
  PenLine,
  Cpu,
  RefreshCw,
  MoreHorizontal,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface MobileNavItem {
  id: DashboardTab;
  label: string;
  icon: LucideIcon;
}

const MOBILE_NAV_ITEMS: MobileNavItem[] = [
  { id: "qa", label: "质检", icon: ShieldCheck },
  { id: "bot-config", label: "Bot", icon: Bot },
  { id: "knowledge-base", label: "知识库", icon: BookOpen },
  { id: "prompts", label: "Prompt", icon: PenLine },
  { id: "model-configs", label: "模型", icon: Cpu },
];

export default function MobileNav({
  activeTab,
  onTabChange,
  role = "operator",
}: {
  activeTab: DashboardTab;
  onTabChange: (tab: DashboardTab) => void;
  role?: Role;
}) {
  const router = useRouter();
  const [moreOpen, setMoreOpen] = useState(false);

  return (
    <nav className="mobile-nav md:hidden" aria-label="移动端主导航">
      {MOBILE_NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        return (
        <button
            key={item.id}
            type="button"
            className={`mobile-nav-btn${activeTab === item.id ? " active" : ""}`}
            onClick={() => onTabChange(item.id)}
            aria-current={activeTab === item.id ? "page" : undefined}
          >
            <span className="mobile-nav-icon">
              <Icon className="w-5 h-5" strokeWidth={activeTab === item.id ? 2.2 : 1.8} />
            </span>
            <span>{item.label}</span>
          </button>
        );
      })}
      <button
        type="button"
        className="mobile-nav-btn"
        onClick={() => router.refresh()}
        aria-label="刷新页面数据"
      >
        <span className="mobile-nav-icon">
          <RefreshCw className="w-5 h-5" strokeWidth={1.8} />
        </span>
        <span>刷新</span>
      </button>
      <button
        type="button"
        className={`mobile-nav-btn${moreOpen ? " active" : ""}`}
        onClick={() => setMoreOpen((open) => !open)}
        aria-expanded={moreOpen}
        aria-controls="mobile-dashboard-menu"
      >
        <span className="mobile-nav-icon">
          {moreOpen ? <X className="w-5 h-5" strokeWidth={1.8} /> : <MoreHorizontal className="w-5 h-5" strokeWidth={1.8} />}
        </span>
        <span>更多</span>
      </button>
      {moreOpen && (
        <div id="mobile-dashboard-menu" className="mobile-dashboard-menu" role="dialog" aria-label="全部后台功能">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <p className="text-sm font-semibold text-foreground">全部功能</p>
            <button type="button" onClick={() => setMoreOpen(false)} className="rounded-md p-1 text-muted-foreground hover:bg-muted" aria-label="关闭全部功能"><X className="size-4" /></button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto p-3">
            {TAB_GROUPS.map((group) => {
              const tabs = group.tabs.filter((tab) => canAccessMenu(role, tab.id));
              if (!tabs.length) return null;
              return <section key={group.label} className="mb-4 last:mb-0"><h3 className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{group.label}</h3><div className="grid grid-cols-2 gap-2">{tabs.map((tab) => { const Icon = tab.icon; return <button key={tab.id} type="button" onClick={() => { onTabChange(tab.id); setMoreOpen(false); }} className={`flex min-h-10 items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs ${activeTab === tab.id ? "border-primary/30 bg-primary/10 text-primary" : "border-border bg-card text-foreground hover:bg-muted"}`}><Icon className="size-4 shrink-0" /><span className="truncate">{tab.label}</span></button>; })}</div></section>;
            })}
          </div>
        </div>
      )}
    </nav>
  );
}
