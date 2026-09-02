"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatPercent, formatCompactPercent, formatRating, cn } from "@/lib/utils";
import Panel from "@/components/dashboard/Panel";
import ConversationBubbles from "@/components/dashboard/ConversationBubbles";
import type { DashboardTab } from "@/components/dashboard/SidebarNav";

import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as ReTooltip,
  ResponsiveContainer,
  LineChart,
  Line,
} from "recharts";
import {
  DatabaseZap,
  Plus,
  ShieldCheck,
  Search,
  CheckCircle2,
  AlertTriangle,
  MoreHorizontal,
  Download,
  Send,
  Sparkles,
  Clock,
  ChevronDown,
  Star,
  X,
} from "lucide-react";

/** 手动质检预填示例：降低空态门槛，点开即可体验 */
const MANUAL_QA_EXAMPLE = `客户：你们这产品质量太差了！我要退货！
客服：您别急，我先帮您核实一下订单。不过说实话这批货确实有点问题，公司已经在处理了。
客户：那你赶紧处理，不然我去投诉你们。
客服：您消消气，我这边马上为您登记售后，48 小时内给您答复。`;

/** 内置兜底规则的视觉展示（与 API 返回的自定义规则同构） */
const FALLBACK_RULES: { category: string; rule_text: string; deduction: number; severity: string; builtin: boolean }[] = [
  { category: "话术合规", rule_text: "不得使用‘最好’、‘第一’等广告法绝对化用语", deduction: 10, severity: "major", builtin: true },
  { category: "服务态度", rule_text: "禁止出现消极、敷衍、推诿类回应", deduction: 15, severity: "critical", builtin: true },
  { category: "合规与隐私", rule_text: "不得在未授权时索要/提及用户敏感信息", deduction: 20, severity: "critical", builtin: true },
];

interface Violation {
  category: string;
  rule: string;
  deduction: number;
  severity: string;
  source_quote: string;
}

interface Report {
  id: string;
  ticket_id: string;
  agent_name: string;
  agent_id: string | null;
  agent_matched: boolean;
  total_score: number;
  risk_level: string;
  sentiment_score: number;
  violations_count: number;
  intent: string;
  status: string;
  correlation_id: string;
  review_mode?: string;
  alert_method?: string;
  created_at: string;
  topViolation?: { category: string; rule: string; quote: string; deduction: number } | null;
}

interface Stats {
  total: number;
  todayCount: number;
  avgScore: number;
  pendingReview: number;
  criticalCount: number;
  highCount: number;
  previousHighCount: number;
  dataRefreshedAt: string | null;
  violationsByCategory: { name: string; value: number }[];
}

interface Profile {
  id: string;
  name: string;
  role: string;
  feishu_open_id?: string | null;
}

/** value 接口返回的数据类型 */
interface TrendPoint { date: string; count: number; }
interface RootCauseItem { name: string; value: number; percentage: number; }
interface AgentSummary { id: string; name: string; reviewCount: number; avgScore: number; totalViolations: number; criticalCount: number; violationRate: string; }
interface ValueData {
  summary: { total: number; monthlyTotal: number; activeCount: number; totalViolations: number };
  cost: { aiCost: number; manualEquivalentCost: number; monthlySavings: number; savingsRate: number; aiHoursSaved: number };
  riskAvoidance: { criticalBlocked: number; highRiskBlocked: number; estimatedFinesAvoided: number; platformFineBaseline: number };
  rootCause: RootCauseItem[];
  trend: TrendPoint[];
  agents: AgentSummary[];
}
interface Rule {
  id: string;
  category: string;
  rule_text: string;
  deduction_min: number;
  deduction_max: number;
  severity: string;
  examples?: string | null;
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text);
}

/** 风险等级统一视觉语言：灰=正常 / 蓝绿=已处理 / 黄=待复核 / 橙=高风险 / 红=Critical */
const RISK_STYLES: Record<string, { badge: string; dot: string; label: string }> = {
  low: { badge: "bg-muted/60 text-muted-foreground border-border/60", dot: "bg-muted-foreground/60", label: "低风险" },
  medium: { badge: "bg-info/12 text-info border-info/25", dot: "bg-info", label: "中风险" },
  high: { badge: "bg-warning/15 text-warning border-warning/30", dot: "bg-warning", label: "高风险" },
  critical: { badge: "bg-destructive/15 text-destructive border-destructive/30", dot: "bg-destructive", label: "致命" },
};

const STATUS_STYLES: Record<string, string> = {
  pending_review: "bg-warning/12 text-warning border-warning/25",
  overturn: "bg-info/12 text-info border-info/25",
  processed: "bg-success/12 text-success border-success/25",
  resolved: "bg-success/12 text-success border-success/25",
  confirmed: "bg-success/12 text-success border-success/25",
  archived: "bg-muted/60 text-muted-foreground border-border/60",
};

const STATUS_LABELS: Record<string, string> = {
  pending_review: "待复核",
  overturn: "申诉中",
  processed: "已处理",
  resolved: "已解决",
  confirmed: "已确认",
  archived: "已归档",
};

const CATEGORY_COLORS = ["#3b82f6", "#8b5cf6", "#f97316", "#eab308", "#ef4444"];

/** 统一指标卡：白底 + 可选左侧色条 + 数字着色，杜绝整卡填充色块 */
function StatCard({
  label,
  value,
  sub,
  tone = "neutral",
  accent,
  onClick,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "neutral" | "success" | "danger" | "warning" | "info";
  accent?: "success" | "danger" | "warning" | "info" | null;
  onClick?: () => void;
}) {
  const valueTone: Record<string, string> = {
    neutral: "text-foreground",
    success: "text-success",
    danger: "text-destructive",
    warning: "text-warning",
    info: "text-info",
  };
  const barTone: Record<string, string> = {
    success: "bg-success",
    danger: "bg-destructive",
    warning: "bg-warning",
    info: "bg-info",
  };
  return (
    <Card
      onClick={onClick}
      className={cn(
        "relative overflow-hidden gap-0 py-3.5 shadow-none ring-border/60 transition-all duration-200",
        onClick && "cursor-pointer hover:ring-primary/40 hover:shadow-sm"
      )}
    >
      {accent && <span aria-hidden className={cn("absolute left-0 top-0 bottom-0 w-[3px]", barTone[accent])} />}
      <CardContent className="px-4">
        <p className="text-xs text-muted-foreground mb-1.5">{label}</p>
        <p className={cn("text-2xl font-bold tracking-tight tabular-nums leading-none", valueTone[tone])}>{value}</p>
        {sub && <p className="text-[11px] text-muted-foreground/80 mt-1.5 leading-snug">{sub}</p>}
      </CardContent>
    </Card>
  );
}

export default function QAPanel({
  onNavigate,
}: {
  onNavigate?: (tab: DashboardTab) => void;
} = {}) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Report | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<{ violations?: Violation[]; conversation?: string[] | string | null } | null>(null);
  const [overturnOpen, setOverturnOpen] = useState(false);
  const [overturnReason, setOverturnReason] = useState("");
  const [overturning, setOverturning] = useState(false);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [dispatchTargetId, setDispatchTargetId] = useState<string>("");
  const [dispatching, setDispatching] = useState(false);
  const [valueData, setValueData] = useState<ValueData | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [newRule, setNewRule] = useState({ category: "服务态度", rule_text: "", deduction_min: 5, deduction_max: 15, severity: "major" });
  const [addingRule, setAddingRule] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [activeFilter, setActiveFilter] = useState<string | null>(null); // 'critical' | 'high' | 'pending' | null
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [ruleDrawerOpen, setRuleDrawerOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualText, setManualText] = useState(MANUAL_QA_EXAMPLE);
  const [manualResult, setManualResult] = useState<{ total_score: number; risk_level: string; violations_count: number; needs_alert: boolean } | null>(null);
  const [manualLoading, setManualLoading] = useState(false);
  const [riskFilter, setRiskFilter] = useState<string>("all"); // 'all' | 'critical' | 'high' | 'medium' | 'low'
  const [intentFilter, setIntentFilter] = useState<string>("all");
  const [timeRange, setTimeRange] = useState<"7d" | "14d">("7d");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [statsRes, reportsRes] = await Promise.all([
        fetch("/api/qa/stats"),
        fetch("/api/qa/reports?limit=50"),
      ]);
      if (statsRes.ok) setStats(await statsRes.json());
      if (reportsRes.ok) setReports(await reportsRes.json());
      setLastUpdated(new Date());
    } catch {
      setError("无法加载质检数据，请检查后端服务");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchProfiles = useCallback(async () => {
    try {
      const res = await fetch("/api/qa/profiles");
      if (res.ok) setProfiles(await res.json());
    } catch { /* profiles are optional */ }
  }, []);

  const fetchValue = useCallback(async () => {
    try {
      const res = await fetch("/api/qa/value");
      if (res.ok) setValueData(await res.json());
    } catch { /* value data is optional */ }
  }, []);

  const fetchRules = useCallback(async () => {
    try {
      const res = await fetch("/api/qa/rules");
      if (res.ok) setRules(await res.json());
    } catch { /* rules are optional */ }
  }, []);

  useEffect(() => {
    // 首次进入需要拉取多组独立数据；请求完成后才更新各自状态。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchData();
    fetchProfiles();
    fetchValue();
    fetchRules();
  }, [fetchData, fetchProfiles, fetchValue, fetchRules]);

  const fetchDetail = async (id: string) => {
    const res = await fetch(`/api/qa/reports/${id}`);
    const data = await res.json();
    setSelectedDetail(data);
  };

  const handleOverturn = async () => {
    if (!selected || !overturnReason.trim()) return;
    setOverturning(true);
    const res = await fetch("/api/qa/overturn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        report_id: selected.id,
        corrected_by: "5a0a26d8-2f78-4f82-9ed4-adb83847bc84",
        reason: overturnReason,
        corrected_judgment: {
          total_score: Math.min(100, selected.total_score + 15),
          risk_level: selected.total_score + 15 >= 90 ? "low" : "medium",
        },
      }),
    });
    if (res.ok) {
      setOverturnOpen(false);
      setOverturnReason("");
      fetchData();
    }
    setOverturning(false);
  };

  const openReport = (r: Report) => {
    setSelected(r);
    fetchDetail(r.id);
  };

  const confirmRisk = async (report: Report) => {
    const res = await fetch(`/api/qa/reports/${report.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "confirmed" }),
    });
    if (res.ok) {
      await fetchData();
    } else {
      const body = await res.json().catch(() => null);
      const detail = body?.error ? `: ${body.error}` : `（HTTP ${res.status}）`;
      setError(`确认风险失败${detail}`);
      alert(`确认风险失败${detail}`);
    }
  };

  /** 风险队列：按风险等级排序 + 默认仅显示活跃项 + 过滤 demo 数据 */
  const filteredReports = useMemo(() => {
    let list = [...reports];
    // Filter demo/test data
    list = list.filter((r) => {
      const name = r.agent_name.toLowerCase();
      return !name.includes("演示") && !name.includes("test") && !name.includes("demo");
    });
    // Active filter from stat cards
    if (activeFilter === "critical") list = list.filter((r) => r.risk_level === "critical");
    else if (activeFilter === "high") list = list.filter((r) => r.risk_level === "high");
    else if (activeFilter === "pending") list = list.filter((r) => r.status === "pending_review" || r.status === "overturn" || r.status === "overturned");
    // Default: hide archived and confirmed
    if (!activeFilter) {
      list = list.filter((r) => r.status !== "archived" && r.status !== "confirmed" && r.status !== "resolved");
    }
    if (riskFilter !== "all") list = list.filter((r) => r.risk_level === riskFilter);
    if (intentFilter !== "all") list = list.filter((r) => r.intent === intentFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (r) =>
          r.ticket_id.toLowerCase().includes(q) ||
          r.agent_name.toLowerCase().includes(q) ||
          r.correlation_id.toLowerCase().includes(q) ||
          (r.topViolation?.rule || "").toLowerCase().includes(q)
      );
    }
    const rank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
    return list.sort((a, b) => (rank[a.risk_level] ?? 4) - (rank[b.risk_level] ?? 4));
  }, [reports, activeFilter, riskFilter, intentFilter, search]);

  /** 趋势图数据：value.trend 近14天违规数，时间范围切换 7/14 天 */
  const trendData = useMemo(() => {
    const raw = valueData?.trend || [];
    return timeRange === "7d" ? raw.slice(-7) : raw;
  }, [valueData, timeRange]);

  /** 环比结论：后一半 vs 前一半，带比较基数 */
  const trendInsight = useMemo(() => {
    const raw = valueData?.trend || [];
    if (raw.length < 4) return null;
    const half = Math.floor(raw.length / 2);
    const prev = raw.slice(0, half).reduce((s: number, d) => s + (d.count || 0), 0);
    const curr = raw.slice(half).reduce((s: number, d) => s + (d.count || 0), 0);
    if (prev === 0 && curr === 0) return null;
    if (prev === 0) return { dir: "up", pct: null, prev, curr };
    const pct = (curr - prev) / prev;
    return { dir: pct >= 0 ? "up" : "down", pct: Math.abs(pct), prev, curr };
  }, [valueData]);

  const intents = useMemo(() => Array.from(new Set(reports.map((r) => r.intent).filter(Boolean))), [reports]);

  // Capture current time in effect (Date.now is impure, must not be called during render)
  const [renderTime, setRenderTime] = useState<number>(0);
  useEffect(() => { setRenderTime(Date.now()); }, []);

  const isSyncStale = useMemo(() => {
    if (!stats?.dataRefreshedAt || !renderTime) return false;
    return renderTime - new Date(stats.dataRefreshedAt).getTime() > 86400000;
  }, [stats, renderTime]);

  const criticalAgeMinutes = useMemo(() => {
    if (!renderTime) return null;
    const firstCritical = filteredReports.find((r) => r.risk_level === "critical");
    if (!firstCritical?.created_at) return null;
    return Math.round((renderTime - new Date(firstCritical.created_at).getTime()) / 60000);
  }, [filteredReports, renderTime]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const exportCsv = async () => {
    try {
      const res = await fetch("/api/qa/export?table=quality_reports&format=csv&limit=500");
      if (!res.ok) throw new Error("export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `quality-reports-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("导出失败，请检查后端服务");
    }
  };

  return (
    <Panel
      title="质检中枢"
      subtitle="质量风险运营台 · 近 7 日运营概览"
      loading={loading}
      error={error}
      onRetry={fetchData}
      actions={
        <div className="flex flex-wrap items-center gap-2.5">
          {/* 时间范围 + 数据范围上下文 */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-muted/50 border border-border/60 text-xs text-muted-foreground/80">
            <Clock className="w-3.5 h-3.5" strokeWidth={2} />
            近 7 天
          </div>
          {lastUpdated && (
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground/70">
              更新于 {lastUpdated.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
            </div>
          )}
          {/* Data freshness indicator */}
          {stats?.dataRefreshedAt && (
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground/70">
              数据截至 {new Date(stats.dataRefreshedAt).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
              {isSyncStale && (
                <span className="text-amber-500">· 同步可能延迟</span>
              )}
            </div>
          )}
          <Button variant="outline" size="sm" onClick={fetchData}>
            刷新
          </Button>
          <Button size="sm" onClick={() => setManualOpen(true)}>
            <Sparkles className="w-3.5 h-3.5 mr-1.5" strokeWidth={2.2} />
            开始质检
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        {/* ===== 处置型指标：可点击筛选风险队列 ===== */}
        <section aria-label="风险摘要">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard
              label="待复核"
              value={stats?.pendingReview ?? "—"}
              tone={(stats?.pendingReview ?? 0) > 0 ? "warning" : "neutral"}
              accent={(stats?.pendingReview ?? 0) > 0 ? "warning" : null}
              sub={stats?.pendingReview ? `查看 ${stats.pendingReview} 项` : "无待复核项"}
              onClick={stats?.pendingReview ? () => setActiveFilter(activeFilter === "pending" ? null : "pending") : undefined}
            />
            <StatCard
              label="致命风险"
              value={stats?.criticalCount ?? "—"}
              tone={(stats?.criticalCount ?? 0) > 0 ? "danger" : "neutral"}
              accent={(stats?.criticalCount ?? 0) > 0 ? "danger" : null}
              sub={stats?.criticalCount ? "立即处置" : "当前无致命风险"}
              onClick={stats?.criticalCount ? () => setActiveFilter(activeFilter === "critical" ? null : "critical") : undefined}
            />
            <StatCard
              label="高风险会话"
              value={stats?.highCount ?? "—"}
              tone={(stats?.highCount ?? 0) > 0 ? "warning" : "neutral"}
              accent={(stats?.highCount ?? 0) > 0 ? "warning" : null}
              sub={stats?.highCount ? `查看 ${stats.highCount} 项` : "当前无高风险"}
              onClick={stats?.highCount ? () => setActiveFilter(activeFilter === "high" ? null : "high") : undefined}
            />
            <StatCard
              label="近 7 日已阻断"
              value={valueData ? (valueData.riskAvoidance.criticalBlocked + valueData.riskAvoidance.highRiskBlocked) : "—"}
              tone={(valueData?.riskAvoidance.criticalBlocked ?? 0) + (valueData?.riskAvoidance.highRiskBlocked ?? 0) > 0 ? "success" : "neutral"}
              accent={(valueData?.riskAvoidance.criticalBlocked ?? 0) + (valueData?.riskAvoidance.highRiskBlocked ?? 0) > 0 ? "success" : null}
              sub={valueData ? `阻断 ${valueData.riskAvoidance.criticalBlocked} 致命 · ${valueData.riskAvoidance.highRiskBlocked} 高风险` : undefined}
            />
          </div>
        </section>

        {/* ===== Critical 紧急条目 ===== */}
        {filteredReports.some((r) => r.risk_level === "critical" && r.status !== "confirmed") && (() => {
          const firstCritical = filteredReports.find((r) => r.risk_level === "critical" && r.status !== "confirmed")!;
          const minutesAgo = criticalAgeMinutes;
          return (
            <div className="border-l-4 border-destructive bg-destructive/5 rounded-lg p-4">
              <span className="text-xs font-bold text-destructive uppercase tracking-wide">需要立即处理</span>
              <p className="text-sm font-semibold mt-1">
                致命 · 会话/工单 {firstCritical.ticket_id || "—"} · {firstCritical.agent_name} · {minutesAgo != null ? `${minutesAgo} 分钟前` : "—"}
              </p>
              {firstCritical.topViolation && (
                <>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    命中：{firstCritical.topViolation.rule || firstCritical.topViolation.category}
                  </p>
                  {firstCritical.topViolation.quote && (
                    <p className="text-xs text-muted-foreground/60 mt-0.5 italic">
                      证据：&ldquo;{firstCritical.topViolation.quote.slice(0, 80)}{firstCritical.topViolation.quote.length > 80 ? "……" : ""}&rdquo;
                    </p>
                  )}
                </>
              )}
              <div className="flex gap-2 mt-3">
                <Button size="sm" variant="outline" onClick={() => setSelected(firstCritical)}>查看完整会话</Button>
                <Button size="sm" variant="destructive" onClick={() => void confirmRisk(firstCritical)}>确认风险</Button>
                <Button size="sm" variant="outline">创建工单</Button>
              </div>
            </div>
          );
        })()}

        {/* ===== 风险队列 — 全宽 ===== */}
        <div>
          <Card className="col-span-12 gap-0 overflow-hidden">
            <CardHeader className="border-b border-border/50 pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-[15px]">风险队列</CardTitle>
                  {activeFilter && (
                    <span className={cn("text-[11px] px-2 py-0.5 rounded-full font-medium", activeFilter === "critical" ? "bg-destructive/12 text-destructive" : activeFilter === "high" ? "bg-warning/15 text-warning" : "bg-info/12 text-info")}>
                      {activeFilter === "critical" ? "Critical" : activeFilter === "high" ? "高风险" : "待复核"}
                    </span>
                  )}
                </div>
                {/* 工具栏：筛选 + 导出 */}
                <div className="flex flex-wrap items-center gap-1.5">
                  <div className="relative">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/50" />
                    <input
                      className="w-44 rounded-md border border-border/70 bg-background pl-7 pr-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary/30"
                      placeholder="搜索工单 / 客服 / 规则…"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </div>
                  <select
                    className="rounded-md border border-border/70 bg-background px-2 py-1 text-xs"
                    value={riskFilter}
                    onChange={(e) => setRiskFilter(e.target.value)}
                    aria-label="风险等级筛选"
                  >
                    <option value="all">全部风险</option>
                    <option value="critical">Critical</option>
                    <option value="high">高风险</option>
                    <option value="medium">关注</option>
                    <option value="low">正常</option>
                  </select>
                  {intents.length > 0 && (
                    <select
                      className="rounded-md border border-border/70 bg-background px-2 py-1 text-xs"
                      value={intentFilter}
                      onChange={(e) => setIntentFilter(e.target.value)}
                      aria-label="意图筛选"
                    >
                      <option value="all">全部意图</option>
                      {intents.map((i) => <option key={i} value={i}>{i}</option>)}
                    </select>
                  )}
                  <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={exportCsv}>
                    <Download className="w-3 h-3" strokeWidth={2.2} />
                    导出
                  </Button>
                </div>
              </div>
              {/* 批量操作栏：多选后出现 */}
              {selectedIds.length > 0 && (
                <div className="mt-2.5 flex items-center gap-2 rounded-lg border border-primary/25 bg-primary/[0.04] px-3 py-2">
                  <span className="text-xs font-medium text-primary">已选 {selectedIds.length} 条</span>
                  <div className="ml-auto flex items-center gap-1.5">
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs gap-1"
                      onClick={() => {
                        if (confirm(`确认向选中的 ${selectedIds.length} 条高危报告发送飞书预警？`)) {
                          selectedIds.forEach(async (id) => {
                            await fetch(`/api/qa/alert/${id}`, { method: "POST", headers: { "Content-Type": "application/json" } });
                          });
                          setSelectedIds([]);
                        }
                      }}
                    >
                      <Send className="w-3 h-3" strokeWidth={2.2} />
                      批量派发
                    </Button>
                    <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={exportCsv}>
                      <Download className="w-3 h-3" strokeWidth={2.2} />
                      导出所选
                    </Button>
                    <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setSelectedIds([])}>
                      清除
                    </Button>
                  </div>
                </div>
              )}
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-8 pl-4">
                      <input
                        type="checkbox"
                        className="accent-primary"
                        checked={selectedIds.length > 0 && selectedIds.length === filteredReports.length}
                        onChange={(e) => setSelectedIds(e.target.checked ? filteredReports.map((r) => r.id) : [])}
                        aria-label="全选"
                      />
                    </TableHead>
                    <TableHead className="w-16">优先级</TableHead>
                    <TableHead>会话/工单</TableHead>
                    <TableHead>客服</TableHead>
                    <TableHead className="max-w-[200px]">命中规则·证据</TableHead>
                    <TableHead className="text-right">质量得分</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead className="text-right">时间</TableHead>
                    <TableHead className="w-16 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(() => {
                    if (filteredReports.length === 0) {
                      return (
                        <TableRow>
                          <TableCell colSpan={10} className="py-12">
                            {reports.length === 0 ? (
                              /* 空状态：统一工作启动区 */
                              <div className="flex flex-col items-center justify-center gap-3 text-center py-4">
                                <div className="grid place-items-center w-12 h-12 rounded-xl bg-muted/40 border border-border/50">
                                  <DatabaseZap className="w-6 h-6 text-muted-foreground/40" strokeWidth={1.3} />
                                </div>
                                <div>
                                  <p className="text-sm font-semibold text-foreground/90">尚未接入质检流水</p>
                                  <p className="text-xs text-muted-foreground/70 mt-1">连接数据源后，将自动生成风险队列、趋势与根因分析</p>
                                </div>
                                <div className="flex items-center gap-2 mt-1">
                                  <Button size="sm" onClick={() => onNavigate?.("bot-config")}>
                                    连接数据源
                                  </Button>
                                  <Button variant="outline" size="sm" onClick={() => setManualOpen(true)}>
                                    运行一轮样例质检
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <div className="flex flex-col items-center justify-center gap-2 text-center">
                                <Search className="w-8 h-8 text-muted-foreground/25" strokeWidth={1.2} />
                                <p className="text-sm font-medium text-foreground/80">当前筛选条件下暂无数据</p>
                                <button
                                  type="button"
                                  className="text-xs text-primary hover:text-primary/80"
                                  onClick={() => { setActiveFilter(null); setRiskFilter("all"); setIntentFilter("all"); setSearch(""); }}
                                >
                                  清除全部筛选
                                </button>
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    }
                    return filteredReports.map((r) => {
                      const rs = RISK_STYLES[r.risk_level] || RISK_STYLES.low;
                      const st = STATUS_STYLES[r.status] || "bg-muted/50 text-muted-foreground border-border/60";
                      const time = r.created_at ? new Date(r.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
                      return (
                        <TableRow
                          key={r.id}
                          className="cursor-pointer hover:bg-muted/30"
                          onClick={() => openReport(r)}
                        >
                          <TableCell className="w-8 pl-4" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              className="accent-primary"
                              checked={selectedIds.includes(r.id)}
                              onChange={() => toggleSelect(r.id)}
                              aria-label={`选择 ${r.ticket_id}`}
                            />
                          </TableCell>
                          <TableCell>
                            <span className="flex items-center gap-1.5">
                              <span className={cn("w-2 h-2 rounded-full shrink-0", rs.dot)} />
                              <Badge variant="outline" className={cn("text-[10px]", rs.badge)}>
                                {rs.label}
                              </Badge>
                            </span>
                          </TableCell>
                          <TableCell className="font-mono text-xs">{r.ticket_id.slice(-8)}</TableCell>
                          <TableCell className="font-medium text-[13px]">
                            {r.agent_matched ? r.agent_name : (
                              <span className="text-muted-foreground/60 italic">{r.agent_name}</span>
                            )}
                          </TableCell>
                          <TableCell className="max-w-[220px]">
                            {r.topViolation?.rule ? (
                              <span className="block truncate text-xs font-medium" title={r.topViolation.rule}>
                                {r.topViolation.rule}
                              </span>
                            ) : (
                              <span className="text-xs text-muted-foreground/50">—</span>
                            )}
                            {r.topViolation?.quote ? (
                              <span className="block truncate text-xs text-muted-foreground/60 mt-0.5" title={r.topViolation.quote}>
                                &ldquo;{r.topViolation.quote.slice(0, 50)}{r.topViolation.quote.length > 50 ? "…" : ""}&rdquo;
                              </span>
                            ) : null}
                          </TableCell>
                          <TableCell className="text-right font-mono text-[13px] tabular-nums">{r.total_score} / 100</TableCell>
                          <TableCell>
                            <Badge variant="outline" className={cn("text-[10px]", st)}>
                              {STATUS_LABELS[r.status] || r.status || "—"}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right whitespace-nowrap text-xs text-muted-foreground/70">{time}</TableCell>
                          <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                            <div className="flex items-center justify-end gap-0.5">
                              <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => openReport(r)}>
                                查看
                              </Button>
                              <Tooltip>
                                <TooltipTrigger>
                                  <span className="grid place-items-center w-7 h-7 rounded-md hover:bg-muted cursor-pointer">
                                    <MoreHorizontal className="w-4 h-4 text-muted-foreground/70" />
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent side="left" className="w-36 p-1">
                                  <div className="flex flex-col">
                                    {r.risk_level === "high" || r.risk_level === "critical" ? (
                                      <button
                                        type="button"
                                        className="text-left text-xs px-2 py-1.5 rounded hover:bg-muted flex items-center gap-1.5"
                                        onClick={() => openReport(r)}
                                      >
                                        <Send className="w-3 h-3" strokeWidth={2.2} /> 派发整改
                                      </button>
                                    ) : null}
                                    <button
                                      type="button"
                                      className="text-left text-xs px-2 py-1.5 rounded hover:bg-muted flex items-center gap-1.5"
                                      onClick={copyToClipboard.bind(null, r.correlation_id)}
                                    >
                                      <CheckCircle2 className="w-3 h-3" strokeWidth={2.2} /> 复制 Trace ID
                                    </button>
                                  </div>
                                </TooltipContent>
                              </Tooltip>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    });
                  })()}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

        </div>
        {/* close full-width risk queue wrapper */}

        {/* ===== 洞察区：趋势 + 高频问题与行动 ===== */}
        {!isMobile ? (
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 xl:col-span-8 space-y-4">
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-[15px]">近 7 日风险走势</CardTitle>
                  <select
                    className="rounded-md border border-border/70 bg-background px-2 py-0.5 text-[11px]"
                    value={timeRange}
                    onChange={(e) => setTimeRange(e.target.value as "7d" | "14d")}
                    aria-label="时间范围"
                  >
                    <option value="7d">近 7 天</option>
                    <option value="14d">近 14 天</option>
                  </select>
                </div>
              </CardHeader>
              <CardContent>
                {trendData.length > 0 ? (
                  <>
                    {trendInsight && (
                      <p className="text-xs mb-2 flex items-center gap-1.5">
                        {trendInsight.dir === "up" ? (
                          <span className="inline-flex items-center gap-1 text-warning font-medium">
                            <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2.2} />
                            违规风险较前期上升 {formatCompactPercent(trendInsight.pct)}（前期 {trendInsight.prev} 条 → 本期 {trendInsight.curr} 条）
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-success font-medium">
                            <CheckCircle2 className="w-3.5 h-3.5" strokeWidth={2.2} />
                            违规风险较前期下降 {formatCompactPercent(trendInsight.pct)}
                          </span>
                        )}
                      </p>
                    )}
                    <ResponsiveContainer width="100%" height={140}>
                      <LineChart data={trendData}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} interval="preserveStartEnd" />
                        <YAxis tick={{ fontSize: 10 }} width={28} allowDecimals={false} />
                        <ReTooltip formatter={(v) => [`${v} 条违规`, "数量"]} />
                        <Line type="monotone" dataKey="count" stroke="var(--primary)" strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 4 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </>
                ) : (
                  <div className="h-[140px] flex flex-col items-center justify-center gap-2 text-center">
                    <Clock className="w-8 h-8 text-muted-foreground/25" strokeWidth={1.2} />
                    <p className="text-xs font-medium text-foreground/80">暂无趋势数据</p>
                    <p className="text-[11px] text-muted-foreground/70">导入会话后自动生成</p>
                  </div>
                )}

                {/* 违规类型分布 */}
                <div className="mt-4">
                  <p className="text-xs font-semibold text-foreground/85 mb-2">违规类型分布 · Top 5</p>
                  {stats?.violationsByCategory && stats.violationsByCategory.length > 0 ? (
                    <div className="space-y-2">
                      {stats.violationsByCategory.slice(0, 5).map((c, i) => {
                        const max = Math.max(...stats.violationsByCategory.map((x) => x.value), 1);
                        return (
                          <div key={c.name} className="flex items-center gap-2">
                            <span className="w-14 shrink-0 text-[11px] text-muted-foreground truncate">{c.name}</span>
                            <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full"
                                style={{ width: `${Math.max(4, (c.value / max) * 100)}%`, backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}
                              />
                            </div>
                            <span className="w-8 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">{c.value}</span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground/60 py-3 text-center">暂无违规数据</p>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 高频问题与处置建议 */}
          <div className="col-span-12 xl:col-span-4 space-y-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-[15px]">高频问题与处置建议</CardTitle>
              </CardHeader>
              <CardContent>
                {stats?.violationsByCategory && stats.violationsByCategory.length > 0 ? (
                  <div className="space-y-2">
                    {stats.violationsByCategory.slice(0, 5).map((c, idx) => (
                      <div key={c.name} className="flex items-center justify-between p-2 rounded-md bg-muted/30 hover:bg-muted/50 transition-colors">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: CATEGORY_COLORS[idx % CATEGORY_COLORS.length] }} />
                          <span className="text-xs font-medium truncate">{c.name}</span>
                          <span className="text-xs text-muted-foreground/70 shrink-0">{c.value} 条</span>
                        </div>
                        <div className="flex items-center gap-1 shrink-0 ml-2">
                          <button className="text-[10px] text-blue-600 hover:underline whitespace-nowrap">查看会话</button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground/60 py-3 text-center">暂无违规数据</p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
        ) : (
          /* 移动端：风险队列（保留动作） */
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-[15px]">风险队列</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {filteredReports.length === 0 ? (
                <div className="py-8 text-center space-y-3">
                  <DatabaseZap className="w-8 h-8 text-muted-foreground/25 mx-auto" strokeWidth={1.2} />
                  <p className="text-sm font-medium">尚未接入质检流水</p>
                  <div className="flex items-center justify-center gap-2">
                    <Button size="sm" variant="outline" onClick={() => onNavigate?.("bot-config")}>连接数据源</Button>
                    <Button size="sm" onClick={() => setManualOpen(true)}>运行样例质检</Button>
                  </div>
                </div>
              ) : (
                filteredReports.slice(0, 10).map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    className="w-full flex items-center justify-between gap-2 rounded-lg border border-border/60 p-2.5 text-left hover:bg-muted/40"
                    onClick={() => openReport(r)}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", (RISK_STYLES[r.risk_level] || RISK_STYLES.low).dot)} />
                        <span className="font-mono text-xs">{r.ticket_id.slice(-8)}</span>
                        <Badge variant="outline" className={cn("text-[10px]", (RISK_STYLES[r.risk_level] || RISK_STYLES.low).badge)}>
                          {(r.risk_level || "low").toUpperCase()}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1 truncate">
                        {r.agent_name} · {r.topViolation?.rule || r.intent || "—"}
                      </p>
                      {(r.risk_level === "critical" || r.risk_level === "high") && r.topViolation && (
                        <p className="text-[11px] text-muted-foreground/70 mt-0.5 line-clamp-2">
                          {r.topViolation.category === "合规红线" ? "触发合规红线，需立即复核并决定是否升级" :
                           r.topViolation.category === "隐私保护" ? "涉及隐私违规，建议复核会话并评估数据泄露风险" :
                           `检测到${r.topViolation.category}问题，建议复核并采取处置措施`}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      {(r.risk_level === "critical" || r.risk_level === "high") && (
                        <span className="text-[10px] text-destructive/80 font-medium mr-1">优先处置</span>
                      )}
                      <span className="text-xs text-primary">查看 ›</span>
                    </div>
                  </button>
                ))
              )}
            </CardContent>
          </Card>
        )}

        {/* ===== 根因分析 + 规则健康度 ===== */}
        {!isMobile && (
        <div className="grid grid-cols-12 gap-4">
          {/* 根因与人员 */}
          <Card className="col-span-12 xl:col-span-8">
            <CardHeader className="pb-2">
              <CardTitle className="text-[15px]">根因分析 · 可行动洞察</CardTitle>
            </CardHeader>
            <CardContent>
              {valueData?.rootCause && valueData.rootCause.length > 0 ? (
                <div className="grid md:grid-cols-2 gap-4">
                  <div className="space-y-2.5">
                    <p className="text-xs font-semibold text-muted-foreground/80 mb-2">违规类型根因</p>
                    {valueData.rootCause.map((rc, i: number) => (
                      <div key={rc.name} className="flex items-center gap-3">
                        <span className="text-xs font-mono text-muted-foreground/60 w-5">{i + 1}</span>
                        <div className="flex-1">
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="text-[13px] font-medium">{rc.name}</span>
                            <span className="text-[11px] text-muted-foreground">{rc.value} 条 · {rc.percentage}%</span>
                          </div>
                          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${Math.min(100, rc.percentage)}%`, backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }} />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2.5">
                    <p className="text-xs font-semibold text-muted-foreground/80 mb-2">受影响客服 Top 5</p>
                    {valueData.agents?.slice(0, 5).map((a, i: number) => (
                      <div key={a.id} className="flex items-center justify-between gap-2 text-[13px]">
                        <span className="flex items-center gap-2 min-w-0">
                          <span className="w-5 h-5 rounded-full bg-muted text-[10px] grid place-items-center text-muted-foreground shrink-0">{i + 1}</span>
                          <span className="truncate">{a.name}</span>
                        </span>
                        <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">
                          {a.totalViolations} 违规 · {a.avgScore} 分
                        </span>
                      </div>
                    ))}
                    {(!valueData.agents || valueData.agents.length === 0) && (
                      <p className="text-xs text-muted-foreground/60 py-3 text-center">暂无客服数据</p>
                    )}
                  </div>
                </div>
              ) : (
                <div className="h-[140px] flex flex-col items-center justify-center gap-2.5 text-center">
                  <ShieldCheck className="w-8 h-8 text-muted-foreground/25" strokeWidth={1.2} />
                  <div>
                    <p className="text-sm font-medium text-foreground/80">暂无违规数据</p>
                    <p className="text-xs text-muted-foreground/70 mt-1">开始质检后，根因与人员分析将自动生成</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* 规则健康度 */}
          <Card className="col-span-12 xl:col-span-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-[15px]">规则健康度 · RAG 动态引擎</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-muted/40 border border-border/60 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground/70">生效规则</p>
                  <p className="text-lg font-bold tabular-nums">{rules.length + FALLBACK_RULES.length}</p>
                </div>
                <div className="rounded-lg bg-muted/40 border border-border/60 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground/70">自定义规则</p>
                  <p className="text-lg font-bold tabular-nums">{rules.length}</p>
                </div>
              </div>
              <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
                规则存储在向量数据库，质检时通过 RAG 动态检索最相关的 {">"}=5 条。命中统计随质检数据自动积累。
              </p>
              <Button variant="outline" size="sm" className="w-full gap-1.5" onClick={() => setRuleDrawerOpen(true)}>
                <ShieldCheck className="w-3.5 h-3.5" strokeWidth={2.2} />
                进入规则库
              </Button>
            </CardContent>
          </Card>
        </div>
        )}

        {/* ===== 系统运行状态 ===== */}
        <div className="flex items-center gap-4 px-4 py-2.5 rounded-lg border border-border/70 bg-muted/20 text-xs text-muted-foreground/70">
          <span className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2">
              <span className="relative inline-flex rounded-full h-2 w-2 bg-success" />
            </span>
            数据同步正常
          </span>
          <span>·</span>
          <span>规则库 {rules.length + FALLBACK_RULES.length} 条生效中</span>
          {stats?.dataRefreshedAt && (
            <>
              <span>·</span>
              <span>数据截至 {new Date(stats.dataRefreshedAt).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
            </>
          )}
          {lastUpdated && (
            <>
              <span>·</span>
              <span>最近质检 {lastUpdated.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>
            </>
          )}
          <button
            type="button"
            className="ml-auto text-xs text-blue-600 hover:underline"
            onClick={() => setRuleDrawerOpen(true)}
          >
            进入规则库
          </button>
        </div>

        {/* ===== 经营价值（可折叠，低优先级） ===== */}
        {valueData && (
          <section aria-label="经营价值">
            <details className="group rounded-xl border border-border/70 bg-card">
              <summary className="flex items-center justify-between px-4 py-3 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden">
                <span className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold text-foreground/90">经营价值</span>
                  <span className="text-[11px] text-muted-foreground/70">成本节约 · 风险规避 · 运行效率</span>
                </span>
                <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground/70">
                  默认收起
                  <ChevronDown className="w-3.5 h-3.5 transition-transform duration-200 group-open:rotate-180" />
                </span>
              </summary>
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 px-4 pb-4">
                <StatCard
                  label="月度成本节约"
                  value={valueData ? `¥${valueData.cost.monthlySavings.toLocaleString()}` : "—"}
                  tone={(valueData?.cost.monthlySavings ?? 0) > 0 ? "success" : "neutral"}
                  accent={(valueData?.cost.monthlySavings ?? 0) > 0 ? "success" : null}
                  sub={valueData ? `节省率 ${formatPercent(valueData.cost.savingsRate)} · 省 ${valueData.cost.aiHoursSaved} 人时` : undefined}
                />
                <StatCard
                  label="规避罚款"
                  value={valueData ? `¥${valueData.riskAvoidance.estimatedFinesAvoided.toLocaleString()}` : "—"}
                  tone={(valueData?.riskAvoidance.estimatedFinesAvoided ?? 0) > 0 ? "danger" : "neutral"}
                  accent={(valueData?.riskAvoidance.estimatedFinesAvoided ?? 0) > 0 ? "danger" : null}
                  sub={valueData ? `阻断 ${valueData.riskAvoidance.criticalBlocked} 高危 · ${valueData.riskAvoidance.highRiskBlocked} 高风险` : undefined}
                />
                <StatCard
                  label="AI 质检成本"
                  value={valueData ? `¥${valueData.cost.aiCost.toLocaleString()}` : "—"}
                  sub={valueData ? `人工等效 ¥${valueData.cost.manualEquivalentCost.toLocaleString()}` : undefined}
                />
                <StatCard
                  label="月度质检量"
                  value={valueData?.summary.monthlyTotal ?? "—"}
                  sub={valueData ? `活跃 ${valueData.summary.activeCount} · 违规 ${valueData.summary.totalViolations}` : undefined}
                />
                <StatCard
                  label="评估一致性"
                  value={
                    valueData?.agents?.length
                      ? formatRating(valueData.agents.reduce((s: number, a) => s + a.avgScore, 0) / valueData.agents.length, 100)
                      : "—"
                  }
                  tone="info"
                  sub={valueData ? `覆盖 ${valueData.agents.length} 名客服` : undefined}
                />
              </div>
            </details>
          </section>
        )}

        {/* 移动端：经营价值精简 */}
        {isMobile && valueData && (
          <div className="grid grid-cols-2 gap-3">
            <StatCard label="成本节约" value={`¥${valueData.cost.monthlySavings.toLocaleString()}`} tone={(valueData.cost.monthlySavings ?? 0) > 0 ? "success" : "neutral"} />
            <StatCard label="规避罚款" value={`¥${valueData.riskAvoidance.estimatedFinesAvoided.toLocaleString()}`} tone={(valueData.riskAvoidance.estimatedFinesAvoided ?? 0) > 0 ? "danger" : "neutral"} />
          </div>
        )}

        {/* ===== 手动质检常驻入口（右下角） ===== */}
        <button
          type="button"
          className="fixed bottom-20 md:bottom-6 right-4 md:right-6 z-30 flex items-center gap-2 rounded-full bg-primary text-primary-foreground px-4 py-2.5 text-sm font-medium shadow-lg shadow-primary/25 hover:bg-primary/90 transition-colors"
          onClick={() => setManualOpen(true)}
          aria-label="打开手动质检"
        >
          <Plus className="w-4 h-4" strokeWidth={2.5} />
          手动质检
        </button>

        {/* ===== 案件调查抽屉 ===== */}
        <Sheet
          open={!!selected}
          onOpenChange={(open) => {
            if (!open) {
              setSelected(null);
              setSelectedDetail(null);
              setDispatchTargetId("");
            }
          }}
        >
          <SheetContent side="right" className="w-full sm:max-w-[640px] overflow-y-auto">
            {selected && (
              <>
                <SheetHeader>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className={cn("text-[10px]", (RISK_STYLES[selected.risk_level] || RISK_STYLES.low).badge)}>
                      {(selected.risk_level || "low").toUpperCase()}
                    </Badge>
                    <Badge variant="outline" className={cn("text-[10px]", STATUS_STYLES[selected.status] || "bg-muted/50 text-muted-foreground border-border/60")}>
                      {selected.status === "pending_review" ? "待复核" : selected.status === "overturn" ? "已驳回" : "已处理"}
                    </Badge>
                    <SheetTitle className="text-base ml-1">工单 {selected.ticket_id}</SheetTitle>
                  </div>
                  <SheetDescription className="text-xs">
                    {selected.agent_name} · 得分 {selected.total_score}/100 · 违规 {selected.violations_count} 条
                  </SheetDescription>
                </SheetHeader>

                <Tabs defaultValue="ai" className="mt-5">
                  <TabsList className="w-full">
                    <TabsTrigger value="ai" className="flex-1">AI 判定</TabsTrigger>
                    <TabsTrigger value="chat" className="flex-1">原始对话</TabsTrigger>
                    <TabsTrigger value="actions" className="flex-1">处置</TabsTrigger>
                  </TabsList>

                  <TabsContent value="ai" className="space-y-4 pt-4">
                    <div className="grid grid-cols-3 gap-3">
                      <Card>
                        <CardHeader className="pb-1">
                          <CardTitle className="text-xs text-muted-foreground">总分</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <p className="text-xl font-bold">{selected.total_score}/100</p>
                        </CardContent>
                      </Card>
                      <Card>
                        <CardHeader className="pb-1">
                          <CardTitle className="text-xs text-muted-foreground">情绪值</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <p className="text-xl font-bold flex gap-0.5">
                            {Array.from({ length: 5 }, (_, i) => (
                              <Star
                                key={i}
                                className={`w-4 h-4 ${i < selected.sentiment_score ? "fill-yellow-400 text-yellow-400" : "text-muted-foreground/30"}`}
                              />
                            ))}
                          </p>
                        </CardContent>
                      </Card>
                      <Card>
                        <CardHeader className="pb-1">
                          <CardTitle className="text-xs text-muted-foreground">意图</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <p className="text-sm font-medium truncate">{selected.intent || "—"}</p>
                        </CardContent>
                      </Card>
                    </div>

                    {/* 派发状态 */}
                    <Card className={selected.review_mode === "shadow" ? "border-border/60 bg-muted/50" : "border-info/20 bg-info/50"}>
                      <CardContent className="py-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-muted-foreground">飞书派发</span>
                          {selected.review_mode === "shadow" ? (
                            <Badge variant="outline" className="text-xs bg-muted text-foreground/70 border-border">影子模式·静默</Badge>
                          ) : selected.risk_level === "critical" || selected.risk_level === "high" ? (
                            <Badge variant="outline" className="text-xs bg-info/15 text-info border-info/30">四级降级派发 →</Badge>
                          ) : (
                            <span className="text-xs text-muted-foreground/70">无需预警</span>
                          )}
                        </div>
                        {selected.review_mode === "shadow" && (
                          <p className="text-xs text-muted-foreground/70">影子模式：AI 全量运行但不触发飞书告警，仅积累校准数据</p>
                        )}
                        {selected.alert_method && selected.alert_method !== "none" && (
                          <p className="text-xs text-success font-medium">已派发: {selected.alert_method}</p>
                        )}
                      </CardContent>
                    </Card>

                    {/* 违规项 */}
                    {selectedDetail?.violations && selectedDetail.violations.length > 0 ? (
                      <div className="space-y-3">
                        <h4 className="text-sm font-semibold">违规项 ({selectedDetail.violations.length})</h4>
                        {selectedDetail.violations.map((v: Violation, i: number) => (
                          <Card key={i} className="border-l-[3px] border-l-destructive">
                            <CardContent className="py-3 space-y-1.5">
                              <div className="flex items-center justify-between">
                                <Badge variant="outline" className="text-xs">{v.category}</Badge>
                                <span className="text-sm text-destructive font-medium tabular-nums">-{v.deduction} 分</span>
                              </div>
                              <p className="text-sm font-medium">{v.rule}</p>
                              <blockquote className="border-l-2 border-destructive/25 pl-3 text-sm text-destructive/90 italic">
                                {/未.{0,8}(报|回复|提供).{0,6}(工号|姓名)|全程未报|未在任何回复/.test(v.source_quote)
                                  ? "（缺失类违规，无对话原话可引）"
                                  : `“${v.source_quote}”`}
                              </blockquote>
                            </CardContent>
                          </Card>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground/70">无违规项</p>
                    )}

                    {/* 人工复核 / 处置建议 */}
                    <Card className="border-warning/20 bg-warning/[0.04]">
                      <CardContent className="py-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-semibold">人工复核 / 处置建议</span>
                          <Badge variant="outline" className="text-xs">
                            {selected.status === "confirmed" ? "已确认" : selected.status === "overturn" ? "已驳回" : "待复核"}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground/80">
                          {selected.risk_level === "critical" || selected.risk_level === "high"
                            ? "命中高风险，建议人工复核：确认风险并生成处置工单，或驳回误判。"
                            : "风险等级较低，系统已自动放行，无需人工复核。"}
                        </p>
                        {selected.status === "pending_review" && (
                          <div className="flex gap-2 pt-1">
                            <Button size="sm" variant="destructive" onClick={() => void confirmRisk(selected)}>确认风险</Button>
                            <Button size="sm" variant="outline" onClick={() => setOverturnOpen(true)}>误判驳回</Button>
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </TabsContent>

                  <TabsContent value="chat" className="pt-4">
                    <ConversationBubbles conversation={selectedDetail?.conversation || null} />
                  </TabsContent>

                  <TabsContent value="actions" className="space-y-3 pt-4">
                    {/* 处置记录 */}
                    <Card>
                      <CardContent className="py-3 space-y-3">
                        <p className="text-sm font-semibold">处置动作</p>
                        {selected.status === "pending_review" && (
                          <Button variant="destructive" className="w-full" onClick={() => setOverturnOpen(true)}>
                            误判驳回
                          </Button>
                        )}
                        {(selected.risk_level === "critical" || selected.risk_level === "high") && selected.review_mode !== "shadow" && (
                          <>
                            {profiles.length > 0 && (
                              <select
                                className="w-full rounded-md border px-3 py-1.5 text-xs"
                                value={dispatchTargetId}
                                onChange={(e) => setDispatchTargetId(e.target.value)}
                              >
                                <option value="">自动选择 (按路由)</option>
                                {profiles.map((p) => (
                                  <option key={p.id} value={p.id}>
                                    {p.name} ({p.role}){p.feishu_open_id ? " · 飞书" : " · 无飞书ID"}
                                  </option>
                                ))}
                              </select>
                            )}
                            <Button
                              variant="outline"
                              size="sm"
                              className="w-full border-info/30 text-info hover:bg-info/10"
                              disabled={dispatching}
                              onClick={async () => {
                                setDispatching(true);
                                const res = await fetch(`/api/qa/alert/${selected.id}`, {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ target_profile_id: dispatchTargetId || undefined }),
                                });
                                const data = await res.json();
                                setDispatching(false);
                                if (res.ok) {
                                  alert(`飞书派发成功！路由: ${data.alert_method} → ${data.target || "N/A"}`);
                                } else {
                                  alert(`派发失败: ${data.error}`);
                                }
                              }}
                            >
                              {dispatching ? "派发中..." : "发送飞书预警"}
                            </Button>
                          </>
                        )}
                        <Button variant="outline" className="w-full" onClick={() => copyToClipboard(selected.correlation_id)}>
                          复制 Trace ID
                        </Button>
                      </CardContent>
                    </Card>
                    <p className="text-[11px] text-muted-foreground/70">
                      处置记录将写入审计日志，并进入 Bad Case 训练集用于模型校准。
                    </p>
                  </TabsContent>
                </Tabs>

                <div className="mt-5 pt-4 border-t flex items-center justify-between">
                  <span className="font-mono text-xs text-muted-foreground/70">Trace: {selected.correlation_id}</span>
                  <Tooltip>
                    <TooltipTrigger>
                      <span className="text-xs text-muted-foreground/50 cursor-default">链路追踪详情 →</span>
                    </TooltipTrigger>
                    <TooltipContent>分布式追踪面板（隔离评测链路）</TooltipContent>
                  </Tooltip>
                </div>
              </>
            )}
          </SheetContent>
        </Sheet>

        {/* ===== 规则库抽屉 ===== */}
        <Sheet open={ruleDrawerOpen} onOpenChange={setRuleDrawerOpen}>
          <SheetContent side="right" className="w-full sm:max-w-[560px] overflow-y-auto">
            <SheetHeader>
              <SheetTitle>规则库 · RAG 动态引擎</SheetTitle>
              <SheetDescription>规则存储在向量数据库，质检时动态检索最相关规则。添加后即时生效。</SheetDescription>
            </SheetHeader>

            <div className="mt-5 space-y-4">
              {/* 新增规则表单 */}
              <div className="rounded-lg border border-primary/20 bg-primary/[0.03] p-3 space-y-2">
                <p className="text-xs font-semibold">新增质检规则</p>
                <select
                  className="w-full rounded-md border px-2 py-1.5 text-xs bg-background"
                  value={newRule.category}
                  onChange={(e) => setNewRule({ ...newRule, category: e.target.value })}
                >
                  <option value="服务态度">服务态度</option>
                  <option value="专业性">专业性</option>
                  <option value="解决问题">解决问题</option>
                  <option value="合规与隐私">合规与隐私</option>
                  <option value="转化导向">转化导向</option>
                  <option value="售后处理">售后处理</option>
                  <option value="话术合规">话术合规</option>
                </select>
                <input
                  className="w-full rounded-md border px-2 py-1.5 text-xs bg-background"
                  placeholder="规则描述，例：客服不得使用'最好'、'第一'等广告法禁用词"
                  value={newRule.rule_text}
                  onChange={(e) => setNewRule({ ...newRule, rule_text: e.target.value })}
                />
                <div className="flex gap-2">
                  <select
                    className="rounded-md border px-2 py-1.5 text-xs flex-1 bg-background"
                    value={newRule.severity}
                    onChange={(e) => setNewRule({ ...newRule, severity: e.target.value })}
                  >
                    <option value="minor">Minor</option>
                    <option value="major">Major</option>
                    <option value="critical">Critical</option>
                  </select>
                  <div className="flex items-center rounded-md border bg-background overflow-hidden">
                    <input
                      className="w-14 px-2 py-1.5 text-xs outline-none"
                      type="number"
                      min={1}
                      max={30}
                      aria-label="单次扣分"
                      value={newRule.deduction_max}
                      onChange={(e) => setNewRule({ ...newRule, deduction_max: Number(e.target.value) })}
                    />
                    <span className="pr-2 text-xs text-muted-foreground/70">分</span>
                  </div>
                  <Button
                    size="sm"
                    disabled={!newRule.rule_text.trim() || addingRule}
                    onClick={async () => {
                      setAddingRule(true);
                      const res = await fetch("/api/qa/rules", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(newRule),
                      });
                      if (res.ok) {
                        setNewRule({ category: "服务态度", rule_text: "", deduction_min: 5, deduction_max: 15, severity: "major" });
                        fetchRules();
                      }
                      setAddingRule(false);
                    }}
                  >
                    {addingRule ? "保存中..." : "保存规则"}
                  </Button>
                </div>
              </div>

              {/* 自定义规则列表 */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 mb-2">自定义规则 ({rules.length})</p>
                <div className="space-y-1.5">
                  {rules.length === 0 && (
                    <p className="text-xs text-muted-foreground/70 text-center py-4">暂无自定义规则，使用内置兜底通用标准</p>
                  )}
                  {rules.map((rule) => (
                    <div key={rule.id} className="flex items-center justify-between text-xs py-2 px-2.5 rounded-lg border border-border/60 hover:bg-muted/40 group">
                      <div className="flex items-center gap-2 min-w-0">
                        <Badge variant="outline" className="text-[10px] shrink-0">{rule.category}</Badge>
                        <span className="truncate">{rule.rule_text}</span>
                        <span className="text-muted-foreground/70 shrink-0 tabular-nums">-{rule.deduction_max} 分</span>
                      </div>
                      <button
                        className="text-destructive/70 hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity shrink-0 ml-2"
                        aria-label="删除规则"
                        onClick={async () => {
                          await fetch(`/api/qa/rules?id=${rule.id}`, { method: "DELETE" });
                          fetchRules();
                        }}
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              {/* 兜底规则 */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 mb-2">内置兜底通用标准</p>
                <div className="space-y-1.5">
                  {FALLBACK_RULES.map((r) => (
                    <div key={r.rule_text} className="flex items-center justify-between text-xs py-1.5 px-2.5 rounded-lg bg-muted/30 border border-border/40">
                      <div className="flex items-center gap-2 min-w-0">
                        <Badge variant="outline" className="text-[10px] shrink-0">{r.category}</Badge>
                        <span className="truncate text-muted-foreground/80">{r.rule_text}</span>
                        <span className="text-muted-foreground/60 shrink-0 tabular-nums">-{r.deduction} 分</span>
                      </div>
                      <Badge variant="outline" className="text-[9px] shrink-0 bg-background text-muted-foreground/60 border-border/60">内置</Badge>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>

        {/* ===== 手动质检抽屉 ===== */}
        <Sheet open={manualOpen} onOpenChange={setManualOpen}>
          <SheetContent side="right" className="w-full sm:max-w-[560px] overflow-y-auto">
            <SheetHeader>
              <SheetTitle>手动质检</SheetTitle>
              <SheetDescription>粘贴客服对话，AI 将按规则引擎即时评估。已预填示例，可直接提交。</SheetDescription>
            </SheetHeader>
            <div className="mt-5 space-y-3">
              <textarea
                className="w-full rounded-md border px-3 py-2 text-sm min-h-[120px] font-mono text-[13px] leading-relaxed"
                placeholder="输入客服对话进行质检，例：&#10;客户：你们这产品质量太差了！&#10;客服：你爱买不买，别在这嚷嚷。"
                value={manualText}
                onChange={(e) => setManualText(e.target.value)}
              />
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  disabled={!manualText.trim() || manualLoading}
                  onClick={async () => {
                    setManualLoading(true);
                    setManualResult(null);
                    const res = await fetch("/api/qa/evaluate", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        ticket_id: `manual_${Date.now()}`,
                        conversation: manualText,
                        review_mode: "active",
                        skip_feishu: true,
                      }),
                    });
                    const data = await res.json();
                    setManualResult(data);
                    setManualLoading(false);
                    fetchData();
                  }}
                >
                  {manualLoading ? "AI 评估中..." : "提交质检"}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setManualText(MANUAL_QA_EXAMPLE)}>
                  还原示例
                </Button>
              </div>
              {manualResult && (
                <div className="rounded-lg border border-border/60 p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">得分</span>
                    <strong className="text-lg tabular-nums">{manualResult.total_score}/100</strong>
                    <Badge variant="outline" className={RISK_STYLES[manualResult.risk_level]?.badge || ""}>{manualResult.risk_level?.toUpperCase()}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">违规 {manualResult.violations_count} 条</p>
                  <p className={manualResult.needs_alert ? "text-xs text-destructive font-medium" : "text-xs text-muted-foreground/70"}>
                    {manualResult.needs_alert ? "已触发飞书派发" : "未达派发阈值"}
                  </p>
                </div>
              )}
              <p className="text-[11px] text-muted-foreground/70">
                已预填示例对话，可直接提交体验；也可以粘贴真实客服会话。
              </p>
            </div>
          </SheetContent>
        </Sheet>

        {/* Overturn Dialog */}
        <Dialog open={overturnOpen} onOpenChange={setOverturnOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>误判驳回</DialogTitle>
              <DialogDescription>
                此操作将推翻 AI 的原始判定，并将此案例记入 Bad Case 训练集。
              </DialogDescription>
            </DialogHeader>
            <textarea
              className="w-full rounded-md border px-3 py-2 text-sm min-h-[100px]"
              placeholder="请详细说明驳回原因，例如：客服并未明显违规，退款需垫付运费是公司真实规定..."
              value={overturnReason}
              onChange={(e) => setOverturnReason(e.target.value)}
            />
            <DialogFooter>
              <Button variant="outline" onClick={() => setOverturnOpen(false)}>取消</Button>
              <Button variant="destructive" onClick={handleOverturn} disabled={!overturnReason.trim() || overturning}>
                {overturning ? "提交中..." : "确认驳回"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </Panel>
  );
}
