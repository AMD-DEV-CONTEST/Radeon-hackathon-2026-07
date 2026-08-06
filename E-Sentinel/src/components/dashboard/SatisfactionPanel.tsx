"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatPercent, formatDateTime } from "@/lib/utils";
import Panel from "@/components/dashboard/Panel";
import MetricCard from "@/components/dashboard/MetricCard";
import ConversationBubbles from "@/components/dashboard/ConversationBubbles";
import LlmAnalysisCard from "@/components/dashboard/LlmAnalysisCard";
import {
  ComposedChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as ReTooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { BotChatSession } from "@/lib/types/bot";

const SATISFACTION_COLORS: Record<string, string> = {
  good: "bg-emerald-100 text-emerald-700",
  neutral: "bg-yellow-100 text-yellow-700",
  bad: "bg-red-100 text-red-700",
};

/* ──────────────── 自定义 Tooltip ──────────────── */
function SatisfactionTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: Record<string, unknown> }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload as Record<string, number>;
  const total = (d.total as number) || 0;
  const good = (d.good as number) || 0;
  const neutral = (d.neutral as number) || 0;
  const bad = (d.bad as number) || 0;
  return (
    <div className="rounded-lg border border-border bg-white px-3 py-2 shadow-md text-xs">
      <p className="font-medium text-foreground mb-1">
        好评 {good} / 中评 {neutral} / 差评 {bad} &middot; 共 {total} 条
      </p>
      <p className="text-muted-foreground/70">
        好评率 {formatPercent(total > 0 ? good / total : 0)}
      </p>
      {total < 5 && (
        <p className="text-amber-600 mt-0.5">样本较少，仅供参考</p>
      )}
    </div>
  );
}

/* ──────────────── 自定义 X 轴刻度（日期 + 样本量） ──────────────── */
function CustomXAxisTick(props: {
  x?: number;
  y?: number;
  payload?: { value: string };
  sampleTotal?: number;
}) {
  const { x = 0, y = 0, payload } = props;
  if (!payload) return null;
  const dateStr = payload.value;
  const sampleTotal = (props as any).sampleTotal;
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={0} y={0} dy={12} textAnchor="middle" fill="var(--muted-foreground)" fontSize={11}>
        {dateStr}
      </text>
      <text x={0} y={0} dy={26} textAnchor="middle" fill="var(--muted-foreground)" fontSize={10} opacity={0.6}>
        {sampleTotal != null ? `${sampleTotal}单` : ""}
      </text>
    </g>
  );
}

export default function SatisfactionPanel() {
  const [metrics, setMetrics] = useState<any>(null);
  const [sessions, setSessions] = useState<BotChatSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<"all" | "bad" | "neutral" | "good">("all");
  const [page, setPage] = useState(0);
  const [chartView, setChartView] = useState<"trend" | "structure">("trend");

  // Preprocess trend data for chart display
  const trendData = (metrics?.trend || []).map((d: any) => ({
    ...d,
    dateShort: d.date?.slice(5) || d.date, // "07-27"
    neutral_rate: d.total > 0 ? d.neutral / d.total : 0,
    bad_rate: d.total > 0 ? d.bad / d.total : 0,
  }));

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch("/api/qa/satisfaction");
      if (res.ok) setMetrics(await res.json());
    } catch { /* metrics are optional */ }
  }, []);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "15", offset: String(page * 15) });
      if (filter !== "all") params.set("satisfaction", filter);
      const res = await fetch(`/api/qa/chat-sessions?${params}`);
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      } else {
        const errData = await res.json().catch(() => ({ error: "加载失败" }));
        setError(errData.error || "加载评价数据失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setLoading(false);
  }, [filter, page]);

  useEffect(() => {
    void fetchMetrics();
  }, [fetchMetrics]);

  useEffect(() => {
    void fetchSessions();
  }, [fetchSessions]);

  const isEmpty = !loading && !error && sessions.length === 0;

  return (
    <Panel
      title="满意度分析"
      subtitle="监控用户满意度趋势，分析差评原因"
      loading={loading}
      error={error}
      onRetry={fetchSessions}
      empty={isEmpty}
      emptyTitle="暂无评价数据"
      emptyDescription="导入机器人聊天记录后，满意度数据将在此展示"
    >
      <div className="space-y-4">
        {/* Metrics */}
        {metrics && (
          <div className="grid grid-cols-4 gap-3">
            <MetricCard
              label="好评率"
              value={formatPercent(metrics.good_rate)}
              intent={metrics.good_rate >= 0.8 ? "success" : "warning"}
              sub={
                metrics.trend_change_pp != null
                  ? `较前 7 日 ${metrics.trend_change_pp > 0 ? "↑" : metrics.trend_change_pp < 0 ? "↓" : ""}${Math.abs(metrics.trend_change_pp).toFixed(1)}pp`
                  : undefined
              }
            />
            <MetricCard
              label="差评率"
              value={formatPercent(metrics.bad_rate)}
              intent={metrics.bad_rate > 0.1 ? "danger" : "neutral"}
            />
            <MetricCard
              label="好评数"
              value={metrics.good_count || 0}
            />
            <MetricCard
              label="差评数"
              value={metrics.bad_count || 0}
              intent={metrics.bad_rate > 0.1 ? "danger" : "neutral"}
            />
          </div>
        )}

        {/* 7-day trend chart */}
        {trendData.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-medium">7日满意度趋势</CardTitle>
                <div className="flex items-center gap-3">
                  {metrics?.trend_change_pp != null && (
                    <span className={`text-xs font-medium ${metrics.trend_change_pp > 0 ? "text-emerald-600" : metrics.trend_change_pp < 0 ? "text-red-500" : "text-muted-foreground"}`}>
                      较前 7 日 {metrics.trend_change_pp > 0 ? "上升" : metrics.trend_change_pp < 0 ? "下降" : "持平"} {Math.abs(metrics.trend_change_pp).toFixed(1)} 个百分点
                    </span>
                  )}
                  <div className="flex rounded-md border border-border overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setChartView("trend")}
                      className={`px-2.5 py-1 text-[11px] font-medium transition-colors ${chartView === "trend" ? "bg-zinc-800 text-white" : "bg-white text-muted-foreground hover:bg-muted"}`}
                    >
                      好评率趋势
                    </button>
                    <button
                      type="button"
                      onClick={() => setChartView("structure")}
                      className={`px-2.5 py-1 text-[11px] font-medium transition-colors border-l border-border ${chartView === "structure" ? "bg-zinc-800 text-white" : "bg-white text-muted-foreground hover:bg-muted"}`}
                    >
                      评价结构
                    </button>
                  </div>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {chartView === "trend" ? (
                <ResponsiveContainer width="100%" height={220}>
                  <ComposedChart data={trendData} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                    <XAxis
                      dataKey="dateShort"
                      tick={(props: any) => (
                        <CustomXAxisTick {...props} sampleTotal={props.payload?.total} />
                      )}
                      interval={0}
                    />
                    <YAxis
                      tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                      domain={[0, 1]}
                      tick={{ fontSize: 11 }}
                      width={36}
                    />
                    <ReTooltip content={<SatisfactionTooltip />} />
                    <ReferenceLine
                      y={0.7}
                      stroke="#94a3b8"
                      strokeDasharray="4 4"
                      strokeWidth={1}
                      label={{ value: "目标 70%", position: "right", fontSize: 10, fill: "#94a3b8" }}
                    />
                    <Line
                      type="monotone"
                      dataKey="good_rate"
                      stroke="#0ea5e9"
                      strokeWidth={2}
                      dot={(props: any) => {
                        const { cx, cy, payload } = props;
                        if (cx == null || cy == null) return null;
                        const isSmallSample = (payload?.total || 0) < 5;
                        if (isSmallSample) {
                          return <circle cx={cx} cy={cy} r={4} stroke="#0ea5e9" strokeWidth={2} fill="white" />;
                        }
                        return <circle cx={cx} cy={cy} r={3.5} fill="#0ea5e9" />;
                      }}
                      activeDot={{ r: 5, fill: "#0ea5e9" }}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={trendData} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                    <XAxis
                      dataKey="dateShort"
                      tick={(props: any) => (
                        <CustomXAxisTick {...props} sampleTotal={props.payload?.total} />
                      )}
                      interval={0}
                    />
                    <YAxis
                      tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                      domain={[0, 1]}
                      tick={{ fontSize: 11 }}
                      width={36}
                    />
                    <ReTooltip content={<SatisfactionTooltip />} />
                    <Bar dataKey="good_rate" stackId="1" fill="#10b981" name="好评" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="neutral_rate" stackId="1" fill="#eab308" name="中评" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="bad_rate" stackId="1" fill="#ef4444" name="差评" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        )}

        <LlmAnalysisCard
          title="LLM 差评根因分析"
          endpoint="/api/qa/satisfaction/analyze"
          triggerLabel="分析"
          placeholder={
            metrics?.bad_count > 0
              ? `近 7 日共 ${metrics.bad_count} 条差评，建议先分析差评会话，定位高频问题。`
              : "点击「分析」按钮，AI 将自动提取差评根因并给出改进建议"
          }
          renderResult={(raw) => {
            const d = raw as Record<string, unknown>;
            const causes = d.causes as Array<{ cause: string; count: number; examples?: string[]; fix_suggestion?: string }> | undefined;
            const priorities = d.priority_actions as string[] | undefined;
            return (
              <div className="space-y-3">
                {causes && causes.length > 0 && causes.map((item, idx) => (
                  <div key={idx} className="p-3 border rounded-md bg-white">
                    <div className="flex items-center justify-between mb-1">
                      <h4 className="font-semibold text-sm text-red-700">{item.cause}</h4>
                      <span className="text-xs bg-red-50 text-red-600 px-2 py-0.5 rounded-full">
                        出现 {item.count} 次
                      </span>
                    </div>
                    {item.examples && item.examples.length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {item.examples.map((ex, i) => (
                          <li key={i} className="text-xs text-muted-foreground/70 pl-3 border-l-2 border-border">
                            &ldquo;{ex}&rdquo;
                          </li>
                        ))}
                      </ul>
                    )}
                    {item.fix_suggestion && (
                      <p className="mt-2 text-xs text-blue-700 bg-blue-50 p-2 rounded">
                        建议：{item.fix_suggestion}
                      </p>
                    )}
                  </div>
                ))}
                {priorities && priorities.length > 0 && (
                  <div className="p-3 bg-blue-50 rounded-md">
                    <p className="text-xs font-semibold text-blue-800 mb-2">TOP 优先改进项</p>
                    <ol className="list-decimal list-inside space-y-1">
                      {priorities.map((p, i) => (
                        <li key={i} className="text-xs text-blue-700">{p}</li>
                      ))}
                    </ol>
                  </div>
                )}
              </div>
            );
          }}
        />

        {/* Filter tabs */}
        <div className="flex gap-2">
          {(["all", "bad", "neutral", "good"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => { setFilter(f); setPage(0); setExpandedId(null); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                filter === f ? "bg-zinc-900 text-white" : "bg-muted text-muted-foreground hover:bg-border"
              }`}
            >
              {f === "all" ? "全部" : f === "bad" ? "差评" : f === "neutral" ? "中评" : "好评"}
            </button>
          ))}
        </div>

        {/* Sessions */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium flex items-center justify-between">
              <span>评价明细</span>
              <span className="text-xs text-muted-foreground/50 font-normal">
                {page > 0 && (
                  <button className="hover:underline mr-2" onClick={() => setPage((p) => Math.max(0, p - 1))}>
                    ← 上一页
                  </button>
                )}
                <button className="hover:underline" onClick={() => setPage((p) => p + 1)}>下一页 →</button>
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>会话ID</TableHead>
                  <TableHead>平台</TableHead>
                  <TableHead>满意度</TableHead>
                  <TableHead>情绪值</TableHead>
                  <TableHead>消息数</TableHead>
                  <TableHead>询单结果</TableHead>
                  <TableHead>时间</TableHead>
                  <TableHead className="text-right">对话</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((s, i) => (
                  <TableRow key={s.id || i} className={`hover:bg-muted/50 ${expandedId === i ? "bg-muted/50" : ""}`}>
                    <TableCell className="font-mono text-xs">
                      {s.external_session_id?.slice(-10) || s.id?.slice(-8) || "—"}
                    </TableCell>
                    <TableCell className="text-xs">{s.platform_name || "—"}</TableCell>
                    <TableCell>
                      <Badge className={SATISFACTION_COLORS[s.satisfaction || ""] || ""}>
                        {s.satisfaction === "good" ? "好评" : s.satisfaction === "neutral" ? "中评" : s.satisfaction === "bad" ? "差评" : "—"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">{s.sentiment_score ?? "—"}</TableCell>
                    <TableCell className="text-xs">{s.total_messages}</TableCell>
                    <TableCell className="text-xs">
                      {s.inquiry_result === "converted" ? "已转化" : s.inquiry_result === "lost" ? "已流失" : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground/70">
                      {formatDateTime(s.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <button
                        className="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors"
                        onClick={() => setExpandedId(expandedId === i ? null : i)}
                      >
                        {expandedId === i ? "收起" : "展开"}
                      </button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Expanded conversation detail */}
        {expandedId !== null && sessions[expandedId] && (
          <Card className="border-blue-100">
            <CardContent className="py-3">
              <ConversationBubbles conversation={sessions[expandedId].conversation} />
            </CardContent>
          </Card>
        )}
      </div>
    </Panel>
  );
}
