"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Role } from "@/lib/rbac";
import { canAccessMenu } from "@/lib/rbac";
import {
  ShieldCheck,
  Headset,
  Bot,
  MessageSquare,
  Target,
  TrendingDown,
  Smile,
  Gauge,
  PiggyBank,
  HelpCircle,
  BookOpen,
  PenLine,
  Megaphone,
  BarChart3,
  Monitor,
  Eye,
  Scale,
  ClipboardList,
  Columns2,
  BellRing,
  Users,
  Activity,
  Cpu,
  ScrollText,
  Search,
  ChevronDown,
  LayoutDashboard,
  Rocket,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import ThemeToggle from "@/components/dashboard/ThemeToggle";

export type DashboardTab =
  | "overview"
  | "bot-config"
  | "chat-monitor"
  | "knowledge-base"
  | "campaign-sync"
  | "inquiry-loss"
  | "diagnosis"
  | "satisfaction"
  | "reports"
  | "qa"
  | "audit"
  | "compliance"
  | "intent-accuracy"
  | "work-orders"
  | "effect-compare"
  | "payment-reminders"
  | "agent-assist"
  | "agent-performance"
  | "llm-metrics"
  | "platforms"
  | "shadow-approval"
  | "quality-monitor"
  | "model-configs"
  | "prompts"
  | "cost-savings"
  | "unresolved"
  | "release-evidence";

interface TabItem {
  id: DashboardTab;
  label: string;
  icon: LucideIcon;
}

export const TAB_GROUPS: { label: string; tabs: TabItem[] }[] = [
  {
    label: "核心操作",
    tabs: [
      { id: "overview", label: "经营总览", icon: LayoutDashboard },
      { id: "qa", label: "质检中枢", icon: ShieldCheck },
      { id: "agent-assist", label: "坐席辅助", icon: Headset },
      { id: "bot-config", label: "Bot 管理", icon: Bot },
    ],
  },
  {
    label: "数据监控",
    tabs: [
      { id: "chat-monitor", label: "聊天监控", icon: MessageSquare },
      { id: "intent-accuracy", label: "意图准确率", icon: Target },
      { id: "inquiry-loss", label: "询单流失", icon: TrendingDown },
      { id: "diagnosis", label: "未成交诊断", icon: Search },
      { id: "satisfaction", label: "满意度分析", icon: Smile },
      { id: "quality-monitor", label: "回复质量", icon: Gauge },
      { id: "cost-savings", label: "降本看板", icon: PiggyBank },
    ],
  },
  {
    label: "资源管理",
    tabs: [
      { id: "unresolved", label: "未解决问题", icon: HelpCircle },
      { id: "knowledge-base", label: "知识库管理", icon: BookOpen },
      { id: "prompts", label: "Prompt 管理", icon: PenLine },
      { id: "campaign-sync", label: "活动对接", icon: Megaphone },
      { id: "reports", label: "数据中心", icon: BarChart3 },
    ],
  },
  {
    label: "系统运维",
    tabs: [
      { id: "release-evidence", label: "发布治理", icon: Rocket },
      { id: "platforms", label: "平台管理", icon: Monitor },
      { id: "shadow-approval", label: "回复审核", icon: Eye },
      { id: "compliance", label: "合规审核", icon: Scale },
      { id: "work-orders", label: "工单管理", icon: ClipboardList },
      { id: "effect-compare", label: "效果对比", icon: Columns2 },
      { id: "payment-reminders", label: "智能催付", icon: BellRing },
      { id: "agent-performance", label: "坐席绩效", icon: Users },
      { id: "llm-metrics", label: "大模型监控", icon: Activity },
      { id: "model-configs", label: "模型管理", icon: Cpu },
      { id: "audit", label: "系统审计", icon: ScrollText },
    ],
  },
];

export default function SidebarNav({
  activeTab,
  onTabChange,
  role = "admin",
}: {
  activeTab: DashboardTab;
  onTabChange: (tab: DashboardTab) => void;
  role?: Role;
}) {
  // 所有分组默认展开；用户可手动折叠
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    () => new Set(TAB_GROUPS.map((g) => g.label))
  );
  const [menuQuery, setMenuQuery] = useState("");

  const toggleGroup = (label: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const isGroupExpanded = (label: string) => expandedGroups.has(label);

  return (
    <nav className="sidebar w-56 shrink-0 border-r border-sidebar-border bg-sidebar hidden md:flex flex-col select-none">
      {/* ── Brand — 56px, 18px ShieldCheck, 16px 产品名 ── */}
      <div className="flex items-center gap-2 px-4 h-14 shrink-0">
        <ShieldCheck
          className="w-[18px] h-[18px] shrink-0 text-[#35C6D3]"
          strokeWidth={1.75}
        />
        <span className="text-[16px] font-semibold tracking-tight text-sidebar-foreground">
          E‑Sentinel
        </span>
      </div>

      {/* ── 搜索 — 40px, 13px ── */}
      <div className="px-3 py-2">
        <div className="relative">
          <Search
            className="absolute left-2.5 top-1/2 -translate-y-1/2 w-[15px] h-[15px] text-[#94A3B8]"
            strokeWidth={1.75}
          />
          <input
            className="w-full h-10 rounded-lg border border-[#E5EAF0] bg-white pl-8 pr-3 text-[13px] text-sidebar-foreground placeholder:text-[#94A3B8] outline-none transition-all duration-150 focus:border-[#35C6D3]/40 focus:ring-2 focus:ring-[#35C6D3]/10"
            placeholder="搜索菜单…"
            value={menuQuery}
            onChange={(e) => setMenuQuery(e.target.value)}
          />
        </div>
      </div>

      {/* ── 导航分组 ── */}
      <div className="flex-1 overflow-y-auto px-3 py-1">
        {TAB_GROUPS.map((group) => {
          const visibleTabs = group.tabs.filter((tab) =>
            canAccessMenu(role, tab.id)
          );
          if (visibleTabs.length === 0) return null;
          const filteredTabs = menuQuery.trim()
            ? visibleTabs.filter((t) =>
                t.label.toLowerCase().includes(menuQuery.trim().toLowerCase())
              )
            : visibleTabs;
          if (filteredTabs.length === 0) return null;
          const expanded = isGroupExpanded(group.label);
          const isActiveGroup = group.tabs.some((t) => t.id === activeTab);

          return (
            <div key={group.label} className="mb-0.5">
              {/* 分组标题 — 12px medium */}
              <button
                type="button"
                onClick={() => toggleGroup(group.label)}
                className="flex items-center justify-between w-full px-2 h-8 hover:opacity-70 transition-opacity duration-150"
                aria-expanded={expanded}
              >
                <span className="text-[12px] font-medium text-[#64748B] select-none">
                  {group.label}
                </span>
                <ChevronDown
                  className={cn(
                    "w-3.5 h-3.5 text-[#94A3B8] transition-transform duration-150",
                    expanded && "rotate-180"
                  )}
                  strokeWidth={1.75}
                />
              </button>

              {/* 导航项 — 14px, 42px 行高, 18px 图标 */}
              {expanded && (
                <div className="space-y-0.5">
                  {filteredTabs.map((tab) => {
                    const Icon = tab.icon;
                    const isActive = activeTab === tab.id;
                    return (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => onTabChange(tab.id)}
                        className={cn(
                          "group flex items-center gap-2.5 w-full h-[42px] px-2 rounded-lg text-[14px] text-left relative",
                          "transition-colors duration-150",
                          isActive
                            ? "bg-[#E0F0F3] text-[#0F3D47] font-medium"
                            : "text-[#475569] hover:bg-[#F1F5F9]"
                        )}
                      >
                        {/* 选中态左指示线 — 2px 青蓝 */}
                        {isActive && (
                          <span className="absolute left-0 top-2.5 bottom-2.5 w-0.5 rounded-full bg-[#35C6D3]" />
                        )}
                        <Icon
                          className={cn(
                            "w-[18px] h-[18px] shrink-0",
                            isActive
                              ? "text-[#35C6D3]"
                              : "text-[#64748B]"
                          )}
                          strokeWidth={1.75}
                        />
                        <span className="truncate">{tab.label}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Footer ── */}
      <div className="px-4 py-2.5 border-t border-sidebar-border shrink-0">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium text-[#94A3B8] select-none">
            v0.1
          </span>
          <ThemeToggle />
        </div>
      </div>
    </nav>
  );
}
