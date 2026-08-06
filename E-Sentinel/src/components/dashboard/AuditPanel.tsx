"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import Panel from "@/components/dashboard/Panel";
import { Search, X, Download, Eye, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

interface AuditLog {
  id: string;
  action: string;
  user_id: string | null;
  user_name: string | null;
  resource_type: string | null;
  resource_id: string | null;
  detail: Record<string, unknown> | null;
  correlation_id: string;
  created_at: string;
}

interface AuditStats {
  total: number;
  byAction: Record<string, number>;
}

const ACTION_LABELS: Record<string, string> = {
  login: "登录", logout: "登出",
  evaluate: "AI 质检", overturn: "误判驳回",
  dispatch_feishu: "飞书派发",
  llm_call: "LLM 调用",
  knowledge_create: "知识创建", knowledge_update: "知识更新", knowledge_delete: "知识归档",
  knowledge_publish: "知识发布", knowledge_reject: "知识驳回",
  bot_config_create: "配置创建", bot_config_activate: "配置启用", bot_config_archive: "配置归档",
  bot_config_publish: "配置发布", bot_config_reject: "配置驳回", bot_config_generate: "配置自动生成",
  optimization_task_create: "任务创建", optimization_task_update: "任务更新",
  report_generate: "报告生成",
  campaign_import: "活动导入",
  rule_create: "规则添加", rule_delete: "规则删除",
  feishu_event_receive: "飞书消息接收",
  auto_evaluate_failed: "自动质检失败",
  compliance_block: "合规拦截", compliance_warn: "合规警告", compliance_pass: "合规通过",
};

/** 结果推断：真实可算——failed 类动作=失败，其余=成功 */
function inferResult(log: AuditLog): "success" | "fail" {
  if (log.action === "auto_evaluate_failed") return "fail";
  if (log.detail && typeof log.detail === "object" && "error" in log.detail) return "fail";
  return "success";
}

const MODULE_OF_ACTION: Record<string, string> = {
  llm_call: "大模型", evaluate: "质检", overturn: "质检",
  dispatch_feishu: "通知", knowledge_create: "知识库", knowledge_update: "知识库", knowledge_delete: "知识库",
  knowledge_publish: "知识库", knowledge_reject: "知识库",
  bot_config_create: "Bot", bot_config_activate: "Bot", bot_config_archive: "Bot",
  bot_config_publish: "Bot", bot_config_reject: "Bot", bot_config_generate: "Bot",
  optimization_task_create: "任务", optimization_task_update: "任务",
  report_generate: "报表", campaign_import: "活动", rule_create: "规则", rule_delete: "规则",
  login: "认证", logout: "认证", feishu_event_receive: "飞书", auto_evaluate_failed: "质检",
  compliance_block: "合规", compliance_warn: "合规", compliance_pass: "合规",
};

function formatDetail(action: string, detail: Record<string, unknown> | null): string {
  if (!detail) return "—";
  switch (action) {
    case "llm_call":
      return [
        detail.model && `模型: ${detail.model}`,
        detail.prompt_type && `类型: ${detail.prompt_type}`,
        detail.latency_ms != null && `延迟: ${(detail.latency_ms as number / 1000).toFixed(1)}s`,
        detail.cached ? "缓存命中" : "",
        detail.was_fallback ? "降级" : "",
      ].filter(Boolean).join(" · ");
    case "dispatch_feishu":
      return [
        detail.route && `路由: ${detail.route}`,
        detail.target && `目标: ${detail.target}`,
      ].filter(Boolean).join(" · ");
    case "evaluate":
      return [
        detail.score != null && `得分: ${detail.score}/100`,
        detail.risk_level && `风险: ${detail.risk_level}`,
        detail.violations_count != null && `违规: ${detail.violations_count} 条`,
      ].filter(Boolean).join(" · ");
    default:
      return Object.entries(detail)
        .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
        .join(" · ") || "—";
  }
}

const ALL_ACTIONS = Object.keys(ACTION_LABELS);

export default function AuditPanel() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [actionFilter, setActionFilter] = useState<string>("all");
  const [correlationFilter, setCorrelationFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [selectedLog, setSelectedLog] = useState<AuditLog | null>(null);
  const PAGE_SIZE = 30;

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      });
      if (actionFilter !== "all") params.set("action", actionFilter);
      if (correlationFilter) params.set("correlation_id", correlationFilter);

      const res = await fetch(`/api/qa/audit-logs?${params}`);
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || []);
        setStats(data.stats);
      } else {
        const errData = await res.json().catch(() => ({ error: "加载失败" }));
        setError(errData.error || "加载审计日志失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setLoading(false);
  }, [page, actionFilter, correlationFilter]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const activeActionCounts = useMemo(
    () => (stats?.byAction ? Object.entries(stats.byAction).sort((a, b) => b[1] - a[1]) : []),
    [stats]
  );

  /** 客户端二次过滤：搜索 Trace / 操作人 */
  const visibleLogs = useMemo(() => {
    if (!search.trim()) return logs;
    const q = search.trim().toLowerCase();
    return logs.filter(
      (l) =>
        (l.correlation_id || "").toLowerCase().includes(q) ||
        (l.user_name || "").toLowerCase().includes(q) ||
        (l.resource_id || "").toLowerCase().includes(q)
    );
  }, [logs, search]);

  const exportCsv = async () => {
    try {
      const res = await fetch("/api/qa/export?table=quality_reports&format=csv&limit=500");
      if (!res.ok) throw new Error("export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // 审计导出失败静默，避免打断主流程
    }
  };

  return (
    <Panel
      title="系统审计"
      subtitle="全链路操作追踪 · 可观测性"
      loading={loading}
      error={error}
      onRetry={fetchLogs}
      empty={!loading && !error && logs.length === 0}
      emptyIcon={<Inbox className="w-11 h-11" strokeWidth={1.2} />}
      emptyTitle="暂无审计日志"
      emptyDescription="系统将在运行时自动记录所有关键操作"
    >
      <div className="space-y-4">
        {/* 状态行 + 工具栏 */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3 text-sm">
            <span className="text-muted-foreground/70">
              共 <strong className="text-foreground font-semibold tabular-nums">{stats?.total ?? 0}</strong> 条记录
            </span>
            <span className="text-muted-foreground/30">·</span>
            <div className="flex gap-2 flex-wrap">
              {activeActionCounts.slice(0, 4).map(([action, count]) => (
                <Badge key={action} variant="outline" className="text-[10px] gap-1 bg-muted/40 text-muted-foreground border-border/60">
                  {ACTION_LABELS[action] || action}
                  <span className="tabular-nums">{count}</span>
                </Badge>
              ))}
            </div>
          </div>
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={exportCsv}>
            <Download className="w-3 h-3" strokeWidth={2.2} />
            导出
          </Button>
        </div>

        {/* 筛选工具栏 */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative min-w-[220px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/50" />
            <input
              className="w-full pl-8 pr-7 py-1.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
              placeholder="搜索 Trace / 操作人 / 资源…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-muted-foreground"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          <select
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setPage(0); }}
            className="px-2.5 py-1.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20"
            aria-label="事件类型筛选"
          >
            <option value="all">全部事件类型</option>
            {ALL_ACTIONS.map((a) => (
              <option key={a} value={a}>{ACTION_LABELS[a] || a}</option>
            ))}
          </select>

          <select
            value={activeActionCounts.find(([a]) => MODULE_OF_ACTION[a])?.[0] ?? "all"}
            onChange={(e) => {
              // 模块筛选映射为动作：选择模块时清空动作筛选，仅作为展示性分组
              setActionFilter("all");
              setPage(0);
            }}
            className="px-2.5 py-1.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20"
            aria-label="模块筛选"
          >
            <option value="all">全部模块</option>
            {Array.from(new Set(Object.values(MODULE_OF_ACTION))).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>

          {correlationFilter && (
            <Badge variant="outline" className="text-[10px] gap-1">
              Trace: {correlationFilter.slice(-12)}
              <button
                className="text-muted-foreground/50 hover:text-destructive ml-0.5"
                onClick={() => { setCorrelationFilter(null); setPage(0); }}
                aria-label="清除 Trace 筛选"
              >
                <X className="w-3 h-3" />
              </button>
            </Badge>
          )}
        </div>

        {/* 高密度表格 */}
        <div className="bg-white border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted border-b">
                <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">时间</th>
                <th className="text-left px-4 py-2.5 font-medium text-muted-foreground">事件</th>
                <th className="text-left px-4 py-2.5 font-medium text-muted-foreground w-20">模块</th>
                <th className="text-left px-4 py-2.5 font-medium text-muted-foreground w-24">操作人</th>
                <th className="text-center px-4 py-2.5 font-medium text-muted-foreground w-16">结果</th>
                <th className="text-left px-4 py-2.5 font-medium text-muted-foreground max-w-[260px]">详情</th>
                <th className="text-right px-4 py-2.5 font-medium text-muted-foreground w-16">查看</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {visibleLogs.map((log) => {
                const result = inferResult(log);
                return (
                  <tr key={log.id} className="hover:bg-muted/40 transition-colors cursor-pointer" onClick={() => setSelectedLog(log)}>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground/70 whitespace-nowrap tabular-nums">
                      {log.created_at ? new Date(log.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="text-[13px] font-medium text-foreground/90">{ACTION_LABELS[log.action] || log.action}</span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground/70">
                      {MODULE_OF_ACTION[log.action] || "系统"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground/80">{log.user_name || "系统"}</td>
                    <td className="px-4 py-2.5 text-center">
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-[10px]",
                          result === "success" ? "bg-success/10 text-success border-success/20" : "bg-destructive/10 text-destructive border-destructive/20"
                        )}
                      >
                        {result === "success" ? "成功" : "失败"}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="block truncate text-xs text-muted-foreground/80 max-w-[260px]" title={formatDetail(log.action, log.detail)}>
                        {formatDetail(log.action, log.detail)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={(e) => { e.stopPropagation(); setSelectedLog(log); }}
                        className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                      >
                        <Eye className="w-3 h-3" strokeWidth={2.2} />
                        详情
                      </button>
                    </td>
                  </tr>
                );
              })}
              {visibleLogs.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center">
                    <Inbox className="w-8 h-8 text-muted-foreground/20 mx-auto mb-2" strokeWidth={1.2} />
                    <p className="text-sm text-muted-foreground/70">没有匹配的审计记录</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground/60">
            第 {page + 1} 页 · 每页 {PAGE_SIZE} 条
          </span>
          <div className="flex gap-1.5">
            <Button variant="outline" size="sm" className="h-7 text-xs" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
              ← 上一页
            </Button>
            <Button variant="outline" size="sm" className="h-7 text-xs" disabled={visibleLogs.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>
              下一页 →
            </Button>
          </div>
        </div>
      </div>

      {/* 详情抽屉 */}
      <Sheet open={!!selectedLog} onOpenChange={(open) => { if (!open) setSelectedLog(null); }}>
        <SheetContent side="right" className="w-full sm:max-w-[520px] overflow-y-auto">
          {selectedLog && (
            <>
              <SheetHeader>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={cn("text-[10px]", inferResult(selectedLog) === "success" ? "bg-success/10 text-success border-success/20" : "bg-destructive/10 text-destructive border-destructive/20")}>
                    {inferResult(selectedLog) === "success" ? "成功" : "失败"}
                  </Badge>
                  <SheetTitle className="text-base">{ACTION_LABELS[selectedLog.action] || selectedLog.action}</SheetTitle>
                </div>
                <SheetDescription className="font-mono text-xs">
                  {selectedLog.created_at ? new Date(selectedLog.created_at).toLocaleString("zh-CN") : "—"}
                </SheetDescription>
              </SheetHeader>

              <div className="mt-5 space-y-4">
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg bg-muted/30 border border-border/50 px-3 py-2">
                    <p className="text-[11px] text-muted-foreground/60">模块</p>
                    <p className="text-sm font-medium">{MODULE_OF_ACTION[selectedLog.action] || "系统"}</p>
                  </div>
                  <div className="rounded-lg bg-muted/30 border border-border/50 px-3 py-2">
                    <p className="text-[11px] text-muted-foreground/60">操作人</p>
                    <p className="text-sm font-medium">{selectedLog.user_name || "系统"}</p>
                  </div>
                  <div className="rounded-lg bg-muted/30 border border-border/50 px-3 py-2">
                    <p className="text-[11px] text-muted-foreground/60">资源类型</p>
                    <p className="text-sm font-medium truncate">{selectedLog.resource_type || "—"}</p>
                  </div>
                  <div className="rounded-lg bg-muted/30 border border-border/50 px-3 py-2">
                    <p className="text-[11px] text-muted-foreground/60">资源 ID</p>
                    <p className="text-sm font-medium truncate font-mono text-xs">{selectedLog.resource_id || "—"}</p>
                  </div>
                </div>

                <div>
                  <p className="text-xs font-semibold text-muted-foreground/80 mb-1.5">事件详情</p>
                  <div className="rounded-lg bg-muted/40 border border-border/60 p-3">
                    <p className="text-sm text-foreground/85 leading-relaxed break-words">{formatDetail(selectedLog.action, selectedLog.detail)}</p>
                  </div>
                </div>

                <div>
                  <p className="text-xs font-semibold text-muted-foreground/80 mb-1.5">Trace ID</p>
                  <div className="rounded-lg bg-muted/40 border border-border/60 p-3 flex items-center justify-between gap-2">
                    <span className="font-mono text-xs break-all text-foreground/80">{selectedLog.correlation_id}</span>
                    <button
                      className="shrink-0 text-xs text-primary hover:underline"
                      onClick={() => { setCorrelationFilter(selectedLog.correlation_id); setSelectedLog(null); }}
                    >
                      按此筛选关联事件
                    </button>
                  </div>
                </div>

                {selectedLog.detail && Object.keys(selectedLog.detail).length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground/80 mb-1.5">原始 Payload</p>
                    <pre className="rounded-lg bg-foreground/[0.04] border border-border/60 p-3 text-[11px] font-mono text-foreground/70 overflow-x-auto whitespace-pre-wrap">
                      {JSON.stringify(selectedLog.detail, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </Panel>
  );
}
