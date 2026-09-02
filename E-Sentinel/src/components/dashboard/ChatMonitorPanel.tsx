"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Sheet, SheetContent,
} from "@/components/ui/sheet";
import Panel from "@/components/dashboard/Panel";
import MetricCard from "@/components/dashboard/MetricCard";
import ConversationBubbles from "@/components/dashboard/ConversationBubbles";
import { formatPercent, formatRating, formatDateTime, formatShortId } from "@/lib/utils";
import type { BotChatSession, ChatStats } from "@/lib/types/bot";
import {
  ArrowUpRight, Bot, User, Sparkles, Layers, Search, AlertTriangle,
} from "lucide-react";

/* ──────────────── Constants ──────────────── */
const PAGE_SIZE = 15;

const SATISFACTION_COLORS: Record<string, string> = {
  good: "bg-success/10 text-success border-success/20",
  neutral: "bg-warning/10 text-warning border-warning/20",
  bad: "bg-destructive/10 text-destructive border-destructive/20",
};

const SATISFACTION_LABELS: Record<string, string> = {
  good: "好评", neutral: "中评", bad: "差评",
};

const INQUIRY_RESULT_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  converted: { label: "已转化", color: "bg-success/10 text-success border-success/20", icon: <ArrowUpRight className="w-3 h-3" /> },
  lost: { label: "流失", color: "bg-destructive/10 text-destructive border-destructive/20", icon: <AlertTriangle className="w-3 h-3" /> },
  pending: { label: "待定", color: "bg-muted text-muted-foreground", icon: null },
};

/* ──────────────── Helpers ──────────────── */
function getSentimentColor(score: number | null | undefined): string {
  if (score == null) return "text-muted-foreground/50";
  if (score < 2.5) return "text-destructive font-semibold";
  if (score < 3.5) return "text-warning";
  return "text-muted-foreground/70";
}

/* ──────────────── Main Component ──────────────── */
export default function ChatMonitorPanel() {
  const [sessions, setSessions] = useState<BotChatSession[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<ChatStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<BotChatSession | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  // Monitoring filters
  const [timeRange, setTimeRange] = useState<"24h" | "7d" | "30d">("24h");
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [satisfactionFilter, setSatisfactionFilter] = useState<string>("all");
  const [pendingOnly, setPendingOnly] = useState(false);
  const [sortMode, setSortMode] = useState<"risk" | "latest">("risk");

  // LLM state
  const [inspectResult, setInspectResult] = useState<any>(null);
  const [topicClusters, setTopicClusters] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [llmInspectLoading, setLlmInspectLoading] = useState(false);
  const [llmClusterLoading, setLlmClusterLoading] = useState(false);
  const [llmSummaryLoading, setLlmSummaryLoading] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);

  /* ── Data fetching ── */
  const getDateRange = useCallback(() => {
    const now = new Date();
    const to = now.toISOString();
    let from: string;
    if (timeRange === "24h") {
      from = new Date(now.getTime() - 86400000).toISOString();
    } else if (timeRange === "7d") {
      from = new Date(now.getTime() - 7 * 86400000).toISOString();
    } else {
      from = new Date(now.getTime() - 30 * 86400000).toISOString();
    }
    return { date_from: from, date_to: to };
  }, [timeRange]);

  const fetchStats = useCallback(async () => {
    try {
      const { date_from, date_to } = getDateRange();
      const params = new URLSearchParams({ date_from, date_to });
      const res = await fetch(`/api/qa/chat-stats?${params}`);
      if (res.ok) setStats(await res.json());
    } catch { /* stats are supplementary */ }
  }, [getDateRange]);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { date_from, date_to } = getDateRange();
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
        date_from,
        date_to,
      });
      if (platformFilter !== "all") params.set("platform_id", platformFilter);
      if (satisfactionFilter !== "all") params.set("satisfaction", satisfactionFilter);
      if (pendingOnly) params.set("pending_only", "true");
      const res = await fetch(`/api/qa/chat-sessions?${params}`);
      if (res.ok) {
        const data = await res.json();
        let items = data.sessions || [];
        // Client-side risk sorting
        if (sortMode === "risk") {
          items = [...items].sort((a: BotChatSession, b: BotChatSession) => {
            const riskScore = (s: BotChatSession) => {
              let score = 0;
              if (s.satisfaction === "bad") score += 100;
              if ((s.sentiment_score ?? 5) < 2.5) score += 50;
              if (s.inquiry_result === "lost") score += 30;
              if (!s.bot_handled) score += 10;
              return score;
            };
            return riskScore(b) - riskScore(a);
          });
        }
        setSessions(items);
        setTotal(data.total || 0);
      } else {
        const e = await res.json().catch(() => ({ error: "加载失败" }));
        setError(e.error || "加载会话数据失败");
      }
    } catch {
      setError("网络请求失败");
    }
    setLoading(false);
  }, [getDateRange, page, platformFilter, satisfactionFilter, pendingOnly, sortMode]);

  useEffect(() => { fetchStats(); }, [fetchStats]);
  useEffect(() => { fetchSessions(); }, [fetchSessions]);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  /* ── LLM Handlers ── */
  const handleInspect = async () => {
    setLlmInspectLoading(true);
    setLlmError(null);
    setInspectResult(null);
    try {
      const res = await fetch("/api/qa/chat-sessions/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_ids: sessions.slice(0, 10).map((s) => s.id) }),
      });
      if (res.ok) {
        setInspectResult(await res.json());
      } else {
        const e = await res.json().catch(() => ({}));
        if (res.status === 429) setLlmError("Moonshot API 过载，请等待 30 秒后重试");
        else setLlmError(e.error || "质检失败");
      }
    } catch { setLlmError("网络错误"); }
    setLlmInspectLoading(false);
  };

  const handleCluster = async () => {
    setLlmClusterLoading(true);
    setLlmError(null);
    setTopicClusters(null);
    try {
      const res = await fetch("/api/qa/chat-sessions/cluster", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_ids: sessions.map((s) => s.id) }),
      });
      if (res.ok) {
        setTopicClusters(await res.json());
      } else {
        const e = await res.json().catch(() => ({}));
        setLlmError(e.error || "聚类失败");
      }
    } catch { setLlmError("网络错误"); }
    setLlmClusterLoading(false);
  };

  const handleSummary = async () => {
    setLlmSummaryLoading(true);
    setLlmError(null);
    setSummary(null);
    try {
      const today = new Date().toISOString().split("T")[0];
      const res = await fetch("/api/qa/chat-sessions/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date_from: today, date_to: today }),
      });
      if (res.ok) {
        setSummary(await res.json());
      } else {
        const e = await res.json().catch(() => ({}));
        setLlmError(e.error || "摘要生成失败");
      }
    } catch { setLlmError("网络错误"); }
    setLlmSummaryLoading(false);
  };

  /* ── Derived values ── */
  const satisfiedTotal = stats?.satisfaction_distribution
    ? stats.satisfaction_distribution.good + stats.satisfaction_distribution.neutral + stats.satisfaction_distribution.bad
    : 0;
  const goodRate = satisfiedTotal > 0 ? stats!.satisfaction_distribution.good / satisfiedTotal : 0;
  const pendingBreakdown = stats?.pending_breakdown;
  const isEmpty = !loading && !error && sessions.length === 0;

  /* ── Render ── */
  return (
    <Panel
      title="聊天监控"
      subtitle="实时会话监控与风险预警"
      loading={loading}
      error={error}
      onRetry={fetchSessions}
      empty={isEmpty}
      emptyTitle="暂无会话数据"
      emptyDescription="导入机器人聊天记录后即可在此查看和质检"
      actions={
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleSummary}
            disabled={llmSummaryLoading || sessions.length === 0}
            title={sessions.length === 0 ? "暂无会话数据，无法生成摘要" : undefined}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-border bg-white text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
          >
            <Sparkles className="w-3 h-3" />
            {llmSummaryLoading ? "摘要中..." : "LLM 摘要"}
          </button>
          <button
            type="button"
            onClick={handleCluster}
            disabled={llmClusterLoading || sessions.length === 0}
            title={sessions.length === 0 ? "暂无会话数据，无法进行聚类" : undefined}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-border bg-white text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
          >
            <Layers className="w-3 h-3" />
            {llmClusterLoading ? "聚类中..." : "LLM 聚类"}
          </button>
          <button
            type="button"
            onClick={handleInspect}
            disabled={llmInspectLoading || sessions.length === 0}
            title={sessions.length === 0 ? "暂无会话数据，无法执行质检" : undefined}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-border bg-white text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
          >
            <Search className="w-3 h-3" />
            {llmInspectLoading ? "质检中..." : "LLM 质检"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">

        {/* ── KPI Cards (5) ── */}
        {stats && (
          <div className="grid grid-cols-5 gap-3">
            <MetricCard
              label="总会话数"
              value={stats.total_sessions.toLocaleString()}
              sub={`近 ${timeRange === "24h" ? "24 小时" : timeRange === "7d" ? "7 日" : "30 日"}`}
            />
            <MetricCard
              label={<span className="inline-flex items-center gap-1">机器人处理率<span title="机器人独立完成（无转人工）的会话占比">ⓘ</span></span>}
              value={formatPercent(stats.bot_handled_rate)}
              intent={stats.bot_handled_rate >= 0.7 ? "success" : "warning"}
            />
            <MetricCard
              label="转人工率"
              value={formatPercent(stats.transfer_rate)}
              intent={stats.transfer_rate > 0.3 ? "danger" : "neutral"}
            />
            <MetricCard
              label="好评率"
              value={formatPercent(goodRate)}
              intent={goodRate >= 0.8 ? "success" : goodRate < 0.5 ? "danger" : "warning"}
              sub={
                satisfiedTotal > 0
                  ? `好评${stats.satisfaction_distribution.good} · 中评${stats.satisfaction_distribution.neutral} · 差评${stats.satisfaction_distribution.bad}`
                  : undefined
              }
            />
            <MetricCard
              label="待跟进会话"
              value={String(stats.pending_review_count)}
              intent={stats.pending_review_count > 0 ? "danger" : "success"}
              sub={
                pendingBreakdown
                  ? `差评 ${pendingBreakdown.bad} · 流失 ${pendingBreakdown.lost} · 高风险 ${pendingBreakdown.high_risk}`
                  : undefined
              }
            />
          </div>
        )}

        {/* ── LLM Results ── */}
        {llmError && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">{llmError}</div>
        )}
        {summary && (
          <Card className="border-blue-100 bg-blue-50/50">
            <CardHeader className="pb-1"><CardTitle className="text-sm">每日摘要</CardTitle></CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground/70 whitespace-pre-wrap">{(summary as any).summary}</p>
              {(summary as any).top_questions?.length > 0 && (
                <div className="mt-2">
                  <p className="text-xs font-semibold text-foreground/70">TOP 问题</p>
                  <ul className="list-disc list-inside text-xs text-muted-foreground/70">
                    {(summary as any).top_questions.slice(0, 5).map((q: string, i: number) => <li key={i}>{q}</li>)}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        )}
        {topicClusters && (
          <Card className="border-purple-100 bg-purple-50/50">
            <CardHeader className="pb-1"><CardTitle className="text-sm">问题聚类</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {(topicClusters as any).clusters?.map((c: any, i: number) => (
                  <Badge key={i} variant="outline" className="text-xs bg-white">
                    {c.topic} ({c.count})
                  </Badge>
                )) || <p className="text-xs text-muted-foreground/50">暂无聚类结果</p>}
              </div>
            </CardContent>
          </Card>
        )}
        {inspectResult?.issues && inspectResult.issues.length > 0 && (
          <Card className="border-red-100 bg-red-50/50">
            <CardHeader className="pb-1"><CardTitle className="text-sm">质检结果</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                {inspectResult.issues.slice(0, 5).map((issue: any, i: number) => (
                  <div key={i} className="text-xs p-2 bg-white rounded border">
                    <span className="font-semibold text-red-700">{issue.type || "异常"}</span>
                    <span className="text-muted-foreground/70 ml-2">{issue.description}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Monitoring Filter Bar ── */}
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={timeRange}
            onChange={(e) => { setTimeRange(e.target.value as any); setPage(0); }}
            className="rounded-lg border border-border bg-white px-3 py-1.5 text-xs font-medium text-foreground/70 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="24h">近 24 小时</option>
            <option value="7d">近 7 日</option>
            <option value="30d">近 30 日</option>
          </select>
          <select
            value={satisfactionFilter}
            onChange={(e) => { setSatisfactionFilter(e.target.value); setPage(0); }}
            className="rounded-lg border border-border bg-white px-3 py-1.5 text-xs font-medium text-foreground/70 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">全部满意度</option>
            <option value="good">好评</option>
            <option value="neutral">中评</option>
            <option value="bad">差评</option>
          </select>
          <button
            type="button"
            onClick={() => { setPendingOnly(!pendingOnly); setPage(0); }}
            className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              pendingOnly
                ? "bg-destructive/10 text-destructive border border-destructive/20"
                : "bg-white border border-border text-muted-foreground hover:bg-muted"
            }`}
          >
            <AlertTriangle className="w-3 h-3" />
            仅看待跟进
          </button>
          <div className="ml-auto flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground/50">排序：</span>
            <select
              value={sortMode}
              onChange={(e) => { setSortMode(e.target.value as any); setPage(0); }}
              className="rounded-lg border border-border bg-white px-2.5 py-1.5 text-xs font-medium text-foreground/70 focus:outline-none"
            >
              <option value="risk">风险优先</option>
              <option value="latest">最新优先</option>
            </select>
          </div>
        </div>

        {/* ── Sessions Table ── */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium flex items-center justify-between">
              <span>会话列表</span>
              <span className="text-xs text-muted-foreground/50 font-normal">
                {total > 0 && `共 ${total} 条`}
                {page > 0 && (
                  <button className="hover:underline ml-2" onClick={() => setPage((p) => Math.max(0, p - 1))}>
                    ← 上一页
                  </button>
                )}
                {(page + 1) * PAGE_SIZE < total && (
                  <button className="hover:underline ml-2" onClick={() => setPage((p) => p + 1)}>下一页 →</button>
                )}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="rounded-lg border border-border bg-card overflow-hidden">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[110px]">会话编号</TableHead>
                      <TableHead className="w-[130px]">时间</TableHead>
                      <TableHead>平台</TableHead>
                      <TableHead>业务类型</TableHead>
                      <TableHead>接待</TableHead>
                      <TableHead className="text-center">情绪</TableHead>
                      <TableHead>满意度</TableHead>
                      <TableHead>风险/标签</TableHead>
                      <TableHead>结果</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sessions.map((s) => {
                      const sentimentScore = s.sentiment_score;
                      const sentimentColor = getSentimentColor(sentimentScore);
                      const inquiryMeta = s.inquiry_result ? INQUIRY_RESULT_META[s.inquiry_result] : null;
                      const cleanTags = (s.tags || []).filter((t: string) => t !== "demo" && !t.startsWith("demo"));
                      return (
                        <TableRow key={s.id} className="hover:bg-muted/50">
                          <TableCell className="font-mono text-xs">
                            <span title={s.external_session_id || s.id || ""}>
                              {formatShortId(s.external_session_id || s.id)}
                            </span>
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground/70 tabular-nums whitespace-nowrap">
                            {formatDateTime(s.created_at)}
                          </TableCell>
                          <TableCell className="text-xs">{s.platform_name || "—"}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[11px]">
                              {s.session_type === "pre_sale" ? "售前" : "售后"}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            {s.bot_handled ? (
                              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/70">
                                <Bot className="w-3 h-3" /> 机器人
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/70">
                                <User className="w-3 h-3" /> 人工
                              </span>
                            )}
                          </TableCell>
                          <TableCell>
                            <span className={`text-xs tabular-nums ${sentimentColor}`}>
                              {formatRating(sentimentScore, 5)}
                            </span>
                          </TableCell>
                          <TableCell>
                            {s.satisfaction ? (
                              <Badge className={`text-[11px] ${SATISFACTION_COLORS[s.satisfaction] || ""}`}>
                                {SATISFACTION_LABELS[s.satisfaction] || s.satisfaction}
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground/30">—</span>
                            )}
                          </TableCell>
                          <TableCell>
                            {cleanTags.length > 0 ? (
                              <span className="text-xs text-muted-foreground/70" title={cleanTags.join(" · ")}>
                                {cleanTags.slice(0, 2).join(" · ")}
                                {cleanTags.length > 2 && ` +${cleanTags.length - 2}`}
                              </span>
                            ) : (
                              <span className="text-xs text-muted-foreground/30">—</span>
                            )}
                          </TableCell>
                          <TableCell>
                            {inquiryMeta ? (
                              <Badge className={`text-[11px] inline-flex items-center gap-1 ${inquiryMeta.color}`}>
                                {inquiryMeta.icon}{inquiryMeta.label}
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground/30">—</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <button
                              className="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors"
                              onClick={() => setSelected(s)}
                            >
                              详情
                            </button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── Detail Sheet ── */}
        <Sheet open={!!selected} onOpenChange={(open) => { if (!open) setSelected(null); }}>
          <SheetContent side="right" className="w-[600px] sm:max-w-[600px] overflow-y-auto">
            {selected && (
              <div className="flex flex-col gap-4">
                <div>
                  <h3 className="text-lg font-bold text-foreground">会话详情</h3>
                  <p className="text-xs text-muted-foreground/50 mt-0.5">
                    {formatShortId(selected.external_session_id || selected.id)}
                  </p>
                </div>
                <div className="grid grid-cols-3 gap-3 text-xs">
                  <div><span className="text-muted-foreground/50">平台</span><p className="font-medium">{selected.platform_name || "—"}</p></div>
                  <div><span className="text-muted-foreground/50">类型</span><p className="font-medium">{selected.session_type === "pre_sale" ? "售前" : "售后"}</p></div>
                  <div><span className="text-muted-foreground/50">消息数</span><p className="font-medium">{selected.total_messages}</p></div>
                  <div><span className="text-muted-foreground/50">情绪值</span><p className={`font-medium ${getSentimentColor(selected.sentiment_score)}`}>{formatRating(selected.sentiment_score, 5)}</p></div>
                  <div><span className="text-muted-foreground/50">满意度</span><p className="font-medium">{selected.satisfaction ? SATISFACTION_LABELS[selected.satisfaction] || selected.satisfaction : "—"}</p></div>
                  <div><span className="text-muted-foreground/50">询单结果</span><p className="font-medium">{selected.inquiry_result ? INQUIRY_RESULT_META[selected.inquiry_result]?.label || selected.inquiry_result : "—"}</p></div>
                  <div><span className="text-muted-foreground/50">接待方式</span><p className="font-medium">{selected.bot_handled ? "机器人" : "人工"}</p></div>
                  <div><span className="text-muted-foreground/50">首次响应</span><p className="font-medium">{selected.first_response_ms != null ? `${(selected.first_response_ms / 1000).toFixed(1)}s` : "—"}</p></div>
                  <div><span className="text-muted-foreground/50">时间</span><p className="font-medium">{formatDateTime(selected.created_at)}</p></div>
                </div>
                {selected.transfer_reason && (
                  <div className="rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground/70">转人工原因：{selected.transfer_reason}</div>
                )}
                {selected.tags && selected.tags.length > 0 && (
                  <div>
                    <p className="text-xs text-muted-foreground/50 mb-1.5">标签</p>
                    <div className="flex flex-wrap gap-1.5">
                      {selected.tags.filter((t: string) => t !== "demo" && !t.startsWith("demo")).map((tag: string, i: number) => (
                        <Badge key={i} variant="outline" className="text-[11px]">{tag}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                <div>
                  <p className="text-xs text-muted-foreground/50 mb-2">对话记录</p>
                  <ConversationBubbles conversation={selected.conversation} />
                </div>
                <div className="text-[10px] text-muted-foreground/30 font-mono break-all border-t pt-2">
                  {selected.external_session_id || selected.id}
                </div>
              </div>
            )}
          </SheetContent>
        </Sheet>
      </div>
    </Panel>
  );
}
