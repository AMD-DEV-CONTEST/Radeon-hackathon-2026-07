"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Panel from "./Panel";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Shield,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Copy,
  Check,
  Search,
  X,
  Plus,
  Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ComplianceRule {
  id: string;
  rule_text: string;
  pattern: string;
  risk_level: number;
  category: string;
  action_type: string;
  description: string | null;
  is_active: boolean;
  match_count: number;
  updated_at?: string;
}

interface ComplianceMatch {
  rule: { id: string; rule_text: string; category: string; risk_level: number };
  matched_text: string;
}

interface ComplianceResult {
  passed: boolean;
  highest_risk: number;
  decision: string;
  matches: ComplianceMatch[];
  summary: string;
}

const RISK_LABELS: Record<number, string> = { 1: "致命", 2: "高风险", 3: "中风险", 4: "低风险" };

/** 风险统一视觉语言：致命红 / 高风险橙 / 中风险琥珀 / 低风险蓝灰（绿色留给"已启用/已处理"） */
const RISK_STYLES: Record<number, { badge: string; dot: string; bar: string }> = {
  1: { badge: "bg-destructive/12 text-destructive border-destructive/25", dot: "bg-destructive", bar: "border-l-destructive" },
  2: { badge: "bg-orange-500/12 text-orange-600 border-orange-500/25 dark:text-orange-400", dot: "bg-orange-500", bar: "border-l-orange-500" },
  3: { badge: "bg-warning/15 text-warning border-warning/25", dot: "bg-warning", bar: "border-l-warning" },
  4: { badge: "bg-sky-500/10 text-sky-600 border-sky-500/25 dark:text-sky-400", dot: "bg-sky-500", bar: "border-l-sky-500" },
};

const CATEGORY_LABELS: Record<string, string> = {
  advertising_law: "广告法",
  absolute_claim: "绝对化用语",
  false_promise: "虚假承诺",
  platform_rule: "平台规则",
  competitor_mention: "竞品提及",
  tone_violation: "语气不当",
  sensitive_word: "敏感词",
};

const NEW_RULE_CATEGORIES = Object.keys(CATEGORY_LABELS);

export default function CompliancePanel() {
  const [tab, setTab] = useState<"rules" | "check">("rules");
  const [rules, setRules] = useState<ComplianceRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Quick check state
  const [checkContent, setCheckContent] = useState("");
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<ComplianceResult | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);

  // Search and filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [filterRiskLevel, setFilterRiskLevel] = useState<number | "all">("all");
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<"all" | "active" | "inactive">("active");

  // Detail drawer
  const [detailRule, setDetailRule] = useState<ComplianceRule | null>(null);
  // Add rule drawer
  const [addOpen, setAddOpen] = useState(false);
  const [newRule, setNewRule] = useState({ rule_text: "", pattern: "", risk_level: 3, category: "advertising_law", description: "", action_type: "block" });
  const [adding, setAdding] = useState(false);

  const [copiedPattern, setCopiedPattern] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  const fetchRules = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch("/api/qa/compliance/rules");
      const data = await res.json();
      if (data.error) { setError(data.error); return; }
      if (data.rules) setRules(data.rules);
    } catch {
      setError("加载合规规则失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRules(); }, [fetchRules]);

  const handleCheck = async () => {
    if (!checkContent.trim()) return;
    setChecking(true);
    setCheckError(null);
    try {
      const res = await fetch("/api/qa/compliance/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: checkContent, source_type: "manual_check" }),
      });
      const data = await res.json();
      if (data.error) {
        setCheckError(data.error);
        setCheckResult(null);
      } else {
        setCheckResult(data);
      }
    } catch {
      setCheckError("合规检查请求失败");
    } finally {
      setChecking(false);
    }
  };

  const handleToggleRule = async (rule: ComplianceRule) => {
    try {
      if (rule.is_active) {
        await fetch(`/api/qa/compliance/rules?id=${rule.id}`, { method: "DELETE" });
        setToast({ message: `规则已停用`, type: "success" });
      } else {
        await fetch("/api/qa/compliance/rules", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: rule.id, is_active: true }),
        });
        setToast({ message: `规则已启用`, type: "success" });
      }
      fetchRules();
    } catch {
      setToast({ message: "操作失败，请重试", type: "error" });
    }
  };

  const handleAddRule = async () => {
    if (!newRule.rule_text.trim() || !newRule.pattern.trim()) return;
    setAdding(true);
    try {
      const res = await fetch("/api/qa/compliance/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rule_text: newRule.rule_text.trim(),
          pattern: newRule.pattern.trim(),
          risk_level: newRule.risk_level,
          category: newRule.category,
          description: newRule.description.trim() || null,
          action_type: newRule.action_type,
        }),
      });
      const data = await res.json();
      if (data.error) { setToast({ message: data.error, type: "error" }); return; }
      setToast({ message: "规则已添加", type: "success" });
      setAddOpen(false);
      setNewRule({ rule_text: "", pattern: "", risk_level: 3, category: "advertising_law", description: "", action_type: "block" });
      fetchRules();
    } catch {
      setToast({ message: "添加失败", type: "error" });
    } finally {
      setAdding(false);
    }
  };

  const handleCopyPattern = async (pattern: string) => {
    try {
      await navigator.clipboard.writeText(pattern);
      setCopiedPattern(pattern);
      setTimeout(() => setCopiedPattern(null), 2000);
    } catch {
      setToast({ message: "复制失败", type: "error" });
    }
  };

  // 统计：总规则 / 启用数 / 各风险级数（全部规则，含停用）
  const totalRules = rules.length;
  const activeRules = rules.filter((r) => r.is_active);
  const totalActive = activeRules.length;

  const riskCounts = useMemo(() => {
    const m: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0 };
    activeRules.forEach((r) => { m[r.risk_level] = (m[r.risk_level] || 0) + 1; });
    return m;
  }, [activeRules]);

  const filteredRules = rules.filter((r) => {
    if (filterStatus === "active" && !r.is_active) return false;
    if (filterStatus === "inactive" && r.is_active) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchesName = r.rule_text.toLowerCase().includes(q);
      const matchesRegex = r.pattern.toLowerCase().includes(q);
      const matchesCategory = (CATEGORY_LABELS[r.category] || r.category).toLowerCase().includes(q);
      if (!matchesName && !matchesRegex && !matchesCategory) return false;
    }
    if (filterRiskLevel !== "all" && r.risk_level !== filterRiskLevel) return false;
    if (filterCategory !== "all" && r.category !== filterCategory) return false;
    return true;
  });

  const formatUpdated = (v?: string) => {
    if (!v) return "—";
    const d = new Date(v);
    const now = new Date();
    const diffH = (now.getTime() - d.getTime()) / 3600000;
    if (diffH < 1) return `${Math.max(1, Math.round(diffH * 60))} 分钟前`;
    if (diffH < 24) return `${Math.round(diffH)} 小时前`;
    return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
  };

  return (
    <Panel
      title="合规审核"
      subtitle="敏感词 · 广告法合规 · 内容审核规则"
      loading={loading}
      error={error}
      onRetry={fetchRules}
    >
      {/* 顶部状态行 */}
      <div className="flex items-center gap-4 mb-4 text-xs text-muted-foreground/80">
        <span>规则库 <strong className="text-foreground tabular-nums">{totalRules}</strong></span>
        <span className="w-px h-3 bg-border" />
        <span>当前启用 <strong className="text-foreground tabular-nums">{totalActive}</strong></span>
        <span className="w-px h-3 bg-border" />
        <span>规则命中随内容审核自动积累</span>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 mb-5 bg-muted rounded-lg p-1 w-fit">
        {(["rules", "check"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
              tab === t ? "bg-white text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {t === "rules" ? `规则库 (${totalRules})` : "内容检查"}
          </button>
        ))}
      </div>

      {/* Rules Tab */}
      {tab === "rules" && (
        <div className="space-y-4">
          {/* 决策卡：可点击筛选，低风险用蓝灰不用绿 */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[1, 2, 3, 4].map((level) => {
              const count = riskCounts[level] || 0;
              const pct = totalActive > 0 ? ((count / totalActive) * 100).toFixed(0) : "0";
              const isActive = filterRiskLevel === level;
              const st = RISK_STYLES[level];
              return (
                <button
                  key={level}
                  type="button"
                  onClick={() => setFilterRiskLevel(isActive ? "all" : level)}
                  className={cn(
                    "relative overflow-hidden bg-white border rounded-lg p-3 flex items-center text-left transition-all border-l-4",
                    st.bar,
                    isActive ? "ring-2 ring-primary/25 shadow-sm" : "hover:shadow-sm"
                  )}
                >
                  <div>
                    <div className="text-xs text-muted-foreground/70">{RISK_LABELS[level]}规则</div>
                    <div className="text-2xl font-bold mt-0.5 tabular-nums">{count}</div>
                    <div className="text-xs text-muted-foreground/50 mt-0.5">占比 {pct}% · 点击筛选</div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* 工具栏：搜索 + 筛选 + 主操作 */}
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative min-w-[240px] flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
              <input
                type="text"
                placeholder="搜索规则名称、正则或分类..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-8 py-2 text-sm border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-muted-foreground"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>

            <select
              value={filterRiskLevel}
              onChange={(e) => setFilterRiskLevel(e.target.value === "all" ? "all" : Number(e.target.value))}
              className="px-3 py-2 text-sm border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
            >
              <option value="all">全部风险</option>
              {[1, 2, 3, 4].map((lv) => <option key={lv} value={lv}>{RISK_LABELS[lv]}</option>)}
            </select>

            <select
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value)}
              className="px-3 py-2 text-sm border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
            >
              <option value="all">全部分类</option>
              {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>

            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as typeof filterStatus)}
              className="px-3 py-2 text-sm border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
            >
              <option value="active">仅启用</option>
              <option value="inactive">仅停用</option>
              <option value="all">全部状态</option>
            </select>

            {(searchQuery || filterRiskLevel !== "all" || filterCategory !== "all" || filterStatus !== "active") && (
              <span className="text-xs text-muted-foreground/50">筛选出 {filteredRules.length} 条</span>
            )}

            <Button size="sm" className="ml-auto" onClick={() => setAddOpen(true)}>
              <Plus className="w-3.5 h-3.5 mr-1" strokeWidth={2.5} />
              新增规则
            </Button>
          </div>

          {/* 规则主表 */}
          <div className="bg-white border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted border-b">
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">规则</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground w-20">风险</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground w-24">分类</th>
                  <th className="text-right px-4 py-2.5 font-medium text-muted-foreground w-20">命中次数</th>
                  <th className="text-left px-4 py-2.5 font-medium text-muted-foreground w-24">最近更新</th>
                  <th className="text-center px-4 py-2.5 font-medium text-muted-foreground w-16">状态</th>
                  <th className="text-right px-4 py-2.5 font-medium text-muted-foreground w-16">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {filteredRules.map((rule) => {
                  const st = RISK_STYLES[rule.risk_level] || RISK_STYLES[4];
                  return (
                    <tr
                      key={rule.id}
                      className="h-12 hover:bg-muted/40 transition-colors cursor-pointer"
                      onClick={() => setDetailRule(rule)}
                    >
                      <td className="px-4 py-2">
                        <div className="text-sm font-medium text-foreground">{rule.rule_text}</div>
                        <div className="flex items-center gap-1 mt-0.5">
                          <span className="text-xs text-muted-foreground/50 font-mono max-w-[200px] truncate">
                            /{rule.pattern.substring(0, 30)}{rule.pattern.length > 30 ? "..." : ""}/
                          </span>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleCopyPattern(rule.pattern); }}
                            className="shrink-0 text-muted-foreground/40 hover:text-muted-foreground transition-colors"
                            title="复制正则"
                          >
                            {copiedPattern === rule.pattern ? <Check className="w-3 h-3 text-success" /> : <Copy className="w-3 h-3" />}
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-2">
                        <span className={cn("inline-block px-2 py-0.5 text-xs rounded-full font-medium border", st.badge)}>
                          {RISK_LABELS[rule.risk_level]}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs text-muted-foreground/70">
                        {CATEGORY_LABELS[rule.category] || rule.category}
                      </td>
                      <td className="px-4 py-2 text-right text-xs tabular-nums text-muted-foreground/80">
                        {rule.match_count ?? 0}
                      </td>
                      <td className="px-4 py-2 text-xs text-muted-foreground/70">
                        {formatUpdated(rule.updated_at)}
                      </td>
                      <td className="px-4 py-2 text-center" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => handleToggleRule(rule)}
                          className={cn(
                            "relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary/20",
                            rule.is_active ? "bg-success" : "bg-muted-foreground/20"
                          )}
                          title={rule.is_active ? "点击停用" : "点击启用"}
                        >
                          <span className={cn("inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform", rule.is_active ? "translate-x-[18px]" : "translate-x-[2px]")} />
                        </button>
                      </td>
                      <td className="px-4 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => setDetailRule(rule)}
                          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                        >
                          <Eye className="w-3 h-3" strokeWidth={2.2} />
                          查看
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {filteredRules.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center">
                      <Shield className="w-8 h-8 text-muted-foreground/20 mx-auto mb-2" />
                      <p className="text-sm text-muted-foreground/70 mb-1">
                        {rules.length === 0 ? "暂无合规规则" : "没有匹配的规则"}
                      </p>
                      <p className="text-xs text-muted-foreground/50">
                        {rules.length === 0 ? "点击右上角「新增规则」开始构建规则库" : "尝试调整搜索条件或筛选器"}
                      </p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Quick Check Tab */}
      {tab === "check" && (
        <div className="space-y-4">
          <div className="bg-white border rounded-lg p-4">
            <label className="text-sm font-medium text-foreground/70 block mb-2">
              内容合规检查
            </label>
            <Textarea
              value={checkContent}
              onChange={(e) => setCheckContent(e.target.value)}
              placeholder="粘贴需要检查的知识库内容或话术文本..."
              rows={6}
              className="mb-3"
            />
            <div className="flex items-center gap-3">
              <Button onClick={handleCheck} disabled={checking || !checkContent.trim()}>
                {checking ? "检查中..." : "合规扫描"}
              </Button>
              {checkContent && (
                <span className="text-xs text-muted-foreground/50">
                  {checkContent.length} 字
                </span>
              )}
            </div>
          </div>

          {checkResult && (
            <div className={cn(
              "border rounded-lg p-4",
              checkResult.decision === "blocked" ? "bg-destructive/5 border-destructive/20"
                : checkResult.decision === "flagged" ? "bg-warning/5 border-warning/25"
                  : "bg-success/5 border-success/20"
            )}>
              <div className="flex items-center gap-2 mb-3">
                {checkResult.decision === "passed" ? (
                  <CheckCircle className="w-5 h-5 text-success" />
                ) : checkResult.decision === "blocked" ? (
                  <XCircle className="w-5 h-5 text-destructive" />
                ) : (
                  <AlertTriangle className="w-5 h-5 text-warning" />
                )}
                <span className="font-semibold">
                  {checkResult.decision === "passed" ? "通过" : checkResult.decision === "blocked" ? "已拦截" : "已标记"}
                </span>
                <span className="text-sm text-muted-foreground/70">{checkResult.summary}</span>
              </div>

              {checkResult.matches.length > 0 && (
                <div className="space-y-2">
                  {checkResult.matches.map((m, i) => (
                    <div key={i} className="bg-white rounded border p-3 flex items-start gap-3">
                      <span className={cn("inline-block px-2 py-0.5 text-xs rounded-full font-medium shrink-0 border", (RISK_STYLES[m.rule.risk_level] || RISK_STYLES[4]).badge)}>
                        {RISK_LABELS[m.rule.risk_level] || `L${m.rule.risk_level}`}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm">{m.rule.rule_text}</div>
                        <div className="text-xs text-muted-foreground/50 mt-0.5">
                          匹配: &quot;{m.matched_text}&quot; · {CATEGORY_LABELS[m.rule.category] || m.rule.category}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {checkError && (
            <div className="bg-destructive/5 border border-destructive/20 rounded-lg p-3 text-sm text-destructive">
              {checkError}
            </div>
          )}
        </div>
      )}

      {/* 规则详情抽屉 */}
      <Sheet open={!!detailRule} onOpenChange={(open) => { if (!open) setDetailRule(null); }}>
        <SheetContent side="right" className="w-full sm:max-w-[520px] overflow-y-auto">
          {detailRule && (
            <>
              <SheetHeader>
                <div className="flex items-center gap-2">
                  <span className={cn("inline-block px-2 py-0.5 text-xs rounded-full font-medium border", (RISK_STYLES[detailRule.risk_level] || RISK_STYLES[4]).badge)}>
                    {RISK_LABELS[detailRule.risk_level]}
                  </span>
                  <span className={cn("inline-block px-2 py-0.5 text-xs rounded-full font-medium border", detailRule.is_active ? "bg-success/10 text-success border-success/25" : "bg-muted text-muted-foreground border-border")}>
                    {detailRule.is_active ? "已启用" : "已停用"}
                  </span>
                </div>
                <SheetTitle className="text-base mt-2">{detailRule.rule_text}</SheetTitle>
                <SheetDescription>
                  {CATEGORY_LABELS[detailRule.category] || detailRule.category} · 命中 {detailRule.match_count ?? 0} 次
                  {detailRule.updated_at ? ` · 更新于 ${formatUpdated(detailRule.updated_at)}` : ""}
                </SheetDescription>
              </SheetHeader>

              <div className="mt-5 space-y-4">
                {/* 正则 */}
                <div>
                  <p className="text-xs font-semibold text-muted-foreground/80 mb-1.5">匹配正则</p>
                  <div className="rounded-lg bg-muted/40 border border-border/60 p-3 flex items-start justify-between gap-2">
                    <code className="text-xs font-mono break-all text-foreground/80">{detailRule.pattern}</code>
                    <button
                      onClick={() => handleCopyPattern(detailRule.pattern)}
                      className="shrink-0 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
                      title="复制正则"
                    >
                      {copiedPattern === detailRule.pattern ? <Check className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                {/* 描述 */}
                {detailRule.description && (
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground/80 mb-1.5">规则说明</p>
                    <p className="text-sm text-foreground/80">{detailRule.description}</p>
                  </div>
                )}

                {/* 元信息 */}
                <div>
                  <p className="text-xs font-semibold text-muted-foreground/80 mb-1.5">规则属性</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-lg bg-muted/30 border border-border/50 px-3 py-2">
                      <p className="text-[11px] text-muted-foreground/60">处置动作</p>
                      <p className="text-sm font-medium">{detailRule.action_type === "block" ? "拦截" : "仅标记"}</p>
                    </div>
                    <div className="rounded-lg bg-muted/30 border border-border/50 px-3 py-2">
                      <p className="text-[11px] text-muted-foreground/60">命中次数</p>
                      <p className="text-sm font-medium tabular-nums">{detailRule.match_count ?? 0}</p>
                    </div>
                  </div>
                </div>

                {/* 启停操作 */}
                <Button
                  variant={detailRule.is_active ? "outline" : "default"}
                  className="w-full"
                  onClick={() => { handleToggleRule(detailRule); setDetailRule(null); }}
                >
                  {detailRule.is_active ? "停用此规则" : "启用此规则"}
                </Button>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* 新增规则抽屉 */}
      <Sheet open={addOpen} onOpenChange={setAddOpen}>
        <SheetContent side="right" className="w-full sm:max-w-[520px] overflow-y-auto">
          <SheetHeader>
            <SheetTitle>新增合规规则</SheetTitle>
            <SheetDescription>规则将按风险等级参与内容合规扫描，命中即记录。</SheetDescription>
          </SheetHeader>

          <div className="mt-5 space-y-4">
            <div>
              <label className="text-xs font-semibold text-muted-foreground/80 block mb-1.5">规则名称</label>
              <input
                className="w-full rounded-lg border px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                placeholder="例：禁止使用绝对化用语"
                value={newRule.rule_text}
                onChange={(e) => setNewRule({ ...newRule, rule_text: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-muted-foreground/80 block mb-1.5">匹配正则</label>
              <input
                className="w-full rounded-lg border px-3 py-2 text-sm font-mono bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                placeholder="例：最好|第一|绝对"
                value={newRule.pattern}
                onChange={(e) => setNewRule({ ...newRule, pattern: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-muted-foreground/80 block mb-1.5">风险等级</label>
                <select
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                  value={newRule.risk_level}
                  onChange={(e) => setNewRule({ ...newRule, risk_level: Number(e.target.value) })}
                >
                  <option value={1}>致命</option>
                  <option value={2}>高风险</option>
                  <option value={3}>中风险</option>
                  <option value={4}>低风险</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-muted-foreground/80 block mb-1.5">分类</label>
                <select
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                  value={newRule.category}
                  onChange={(e) => setNewRule({ ...newRule, category: e.target.value })}
                >
                  {NEW_RULE_CATEGORIES.map((c) => (
                    <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold text-muted-foreground/80 block mb-1.5">规则说明（可选）</label>
              <Textarea
                className="rounded-lg"
                rows={3}
                placeholder="说明规则适用的场景与判断标准..."
                value={newRule.description}
                onChange={(e) => setNewRule({ ...newRule, description: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-muted-foreground/80 block mb-1.5">处置动作</label>
              <div className="flex gap-2">
                <Button
                  variant={newRule.action_type === "block" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setNewRule({ ...newRule, action_type: "block" })}
                >
                  命中即拦截
                </Button>
                <Button
                  variant={newRule.action_type === "flag" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setNewRule({ ...newRule, action_type: "flag" })}
                >
                  仅标记
                </Button>
              </div>
            </div>
            <Button
              className="w-full"
              disabled={!newRule.rule_text.trim() || !newRule.pattern.trim() || adding}
              onClick={handleAddRule}
            >
              {adding ? "保存中..." : "保存规则"}
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      {/* Toast notification */}
      {toast && (
        <div
          className={cn(
            "fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium animate-toast-in",
            toast.type === "success" ? "bg-success text-success-foreground" : "bg-destructive text-destructive-foreground"
          )}
        >
          {toast.message}
        </div>
      )}
    </Panel>
  );
}
