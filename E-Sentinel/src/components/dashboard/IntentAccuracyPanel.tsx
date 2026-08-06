"use client";

import { useState, useEffect } from "react";
import Panel from "./Panel";
import MetricCard from "./MetricCard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Target, AlertTriangle } from "lucide-react";
import { formatPercent } from "@/lib/utils";
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as ReTooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

/* ──────────────── Types ──────────────── */
interface AccuracyLatest {
  total: number;
  correct: number;
  incorrect: number;
  accuracy: number;
  coverage_rate: number | null;
  target_met: boolean;
  period_date: string | null;
  is_today: boolean;
}

interface HistoryRow {
  id: string;
  period_date: string;
  total_recognitions: number;
  correct_recognitions: number;
  accuracy: number;
  target_met: boolean;
  platform_id: string | null;
  platform_name: string | null;
}

interface PlatformAccuracy {
  platform_id: string | null;
  platform_name: string;
  total: number;
  correct: number;
  incorrect: number;
  accuracy: number;
}

/* ──────────────── Helpers ──────────────── */
function getStatusTier(accuracy: number): "good" | "watch" | "alert" {
  if (accuracy >= 0.998) return "good";
  if (accuracy >= 0.99) return "watch";
  return "alert";
}

const STATUS_STYLE: Record<string, string> = {
  good: "bg-success/10 text-success border-success/20",
  watch: "bg-warning/10 text-warning border-warning/20",
  alert: "bg-destructive/10 text-destructive border-destructive/20",
};

const STATUS_LABEL: Record<string, string> = {
  good: "达标",
  watch: "关注",
  alert: "告警",
};

/* ──────────────── Custom Tooltip ──────────────── */
function AccuracyTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: Record<string, unknown> }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload as Record<string, number>;
  const accuracy = d.accuracy as number;
  const total = d.total_recognitions as number;
  const incorrect = d.incorrect_recognitions as number;
  return (
    <div className="rounded-lg border border-border bg-white px-3 py-2 shadow-md text-xs">
      <p className="font-medium text-foreground">
        准确率 {formatPercent(accuracy)}
      </p>
      <p className="text-muted-foreground/70">
        识别 {total} 次 &middot; 错误 {incorrect || 0} 次
      </p>
    </div>
  );
}

/* ──────────────── Main Component ──────────────── */
export default function IntentAccuracyPanel() {
  const [latest, setLatest] = useState<AccuracyLatest | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [platforms, setPlatforms] = useState<PlatformAccuracy[]>([]);
  const [mostRecentDate, setMostRecentDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    try {
      setLoading(true);
      const [histRes, platRes] = await Promise.all([
        fetch("/api/qa/intent-accuracy?mode=history&days=30"),
        fetch("/api/qa/intent-accuracy?mode=by_platform&days=7"),
      ]);
      const histData = await histRes.json();
      const platData = await platRes.json();

      if (histData.error) { setError(histData.error); return; }
      setLatest(histData.latest);
      setHistory(histData.history || []);
      setMostRecentDate(histData.most_recent_date || null);
      if (!platData.error) {
        setPlatforms(platData.platforms || []);
      }
    } catch {
      setError("Failed to load accuracy data");
    } finally {
      setLoading(false);
    }
  }

  const hasTodayData = latest?.is_today && latest.total > 0;
  const hasAnyData = latest && latest.total > 0;

  // Preprocess trend data for chart
  const trendData = [...history]
    .reverse()
    .slice(-7)
    .map((r) => ({
      ...r,
      dateShort: r.period_date?.slice(5) || r.period_date,
    }));

  // Alert count: platforms below 99.8%
  const alertPlatforms = platforms.filter((p) => p.accuracy < 0.998);
  const alertCount = alertPlatforms.length;

  // Yesterday comparison
  const yesterdayRow = history.find((r) => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return r.period_date === d.toISOString().split("T")[0];
  });
  const yesterdayAccuracy = yesterdayRow?.accuracy;

  const isEmpty = !loading && !error && !hasAnyData && history.length === 0;

  return (
    <Panel
      title="意图识别监控"
      subtitle="目标 ≥99.8% · 告警线 99%"
      loading={loading}
      error={error}
      onRetry={fetchData}
      empty={isEmpty}
      emptyIcon={<Target className="h-10 w-10" />}
      emptyTitle="暂无意图识别数据"
      emptyDescription="AI客服上线后将自动统计意图准确率"
    >
      <div className="space-y-4">

        {/* ── Top: Smart Overview ── */}
        {!hasTodayData && !loading && (
          <Card className="border-amber-200 bg-amber-50/50">
            <CardContent className="py-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-amber-800">今日暂无识别数据</p>
                  <p className="text-xs text-amber-600/70 mt-0.5">
                    {mostRecentDate
                      ? `最近数据：${mostRecentDate} · 距今 ${(() => {
                          const d = new Date(mostRecentDate);
                          const now = new Date();
                          const hours = Math.round((now.getTime() - d.getTime()) / 3600000);
                          return hours >= 24 ? `${Math.floor(hours / 24)} 天` : `${hours} 小时`;
                        })()}未同步`
                      : "暂无任何历史数据"}
                  </p>
                </div>
                {mostRecentDate && (
                  <span className="text-xs text-muted-foreground/50">
                    最后同步：{mostRecentDate}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── KPI Cards ── */}
        {hasAnyData && (
          <div className="grid grid-cols-4 gap-3">
            <MetricCard
              label="今日准确率"
              value={formatPercent(latest!.accuracy)}
              intent={
                latest!.accuracy < 0.99 ? "danger"
                : latest!.target_met ? "success"
                : "warning"
              }
              sub={
                yesterdayAccuracy != null
                  ? `较昨日 ${latest!.accuracy > yesterdayAccuracy ? "↑" : latest!.accuracy < yesterdayAccuracy ? "↓" : ""}${Math.abs(latest!.accuracy - yesterdayAccuracy) < 0.001 ? "持平" : (Math.abs(latest!.accuracy - yesterdayAccuracy) * 100).toFixed(1) + "pp"}`
                  : undefined
              }
            />
            <MetricCard
              label="识别总数"
              value={latest!.total.toLocaleString()}
            />
            <MetricCard
              label="错误数"
              value={String(latest!.incorrect)}
              intent={latest!.incorrect > 0 ? "danger" : "neutral"}
              sub={
                latest!.total > 0
                  ? `占比 ${((latest!.incorrect / latest!.total) * 100).toFixed(1)}%`
                  : undefined
              }
            />
            <MetricCard
              label="告警项"
              value={String(alertCount)}
              intent={alertCount > 0 ? "danger" : "success"}
              sub={alertCount > 0 ? "需优先处理" : "全部达标"}
            />
          </div>
        )}

        {/* ── 7-Day Accuracy Trend Chart ── */}
        {trendData.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-medium">7日准确率趋势</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={trendData} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                  <XAxis
                    dataKey="dateShort"
                    tick={{ fontSize: 11 }}
                    interval={0}
                  />
                  <YAxis
                    tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`}
                    domain={[0.97, 1]}
                    tick={{ fontSize: 11 }}
                    width={52}
                  />
                  <ReTooltip content={<AccuracyTooltip />} />
                  <ReferenceLine
                    y={0.998}
                    stroke="#0ea5e9"
                    strokeDasharray="4 4"
                    strokeWidth={1}
                    label={{ value: "目标 99.8%", position: "right", fontSize: 10, fill: "#0ea5e9" }}
                  />
                  <ReferenceLine
                    y={0.99}
                    stroke="#f59e0b"
                    strokeDasharray="4 4"
                    strokeWidth={1}
                    label={{ value: "告警 99.0%", position: "right", fontSize: 10, fill: "#f59e0b" }}
                  />
                  {/* Volume bars (secondary axis, subtle) */}
                  <Bar
                    dataKey="total_recognitions"
                    fill="var(--muted-foreground)"
                    opacity={0.12}
                    radius={[2, 2, 0, 0]}
                    yAxisId="volume"
                  />
                  <YAxis
                    yAxisId="volume"
                    orientation="right"
                    hide
                    domain={[0, (max: number) => max * 4]}
                  />
                  <Line
                    type="monotone"
                    dataKey="accuracy"
                    stroke="#0ea5e9"
                    strokeWidth={2}
                    dot={(props: any) => {
                      const { cx, cy, payload } = props;
                      if (cx == null || cy == null) return null;
                      const acc = Number(payload?.accuracy) || 0;
                      const color = acc < 0.99 ? "#ef4444" : acc < 0.998 ? "#f59e0b" : "#0ea5e9";
                      return <circle cx={cx} cy={cy} r={3.5} fill={color} />;
                    }}
                    activeDot={{ r: 5, fill: "#0ea5e9" }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        )}

        {/* ── Anomaly Localization ── */}
        {platforms.length > 0 && (
          <Card>
            <CardHeader className="pb-3 flex flex-row items-center justify-between">
              <CardTitle className="text-sm">异常定位</CardTitle>
              <span className="text-xs text-muted-foreground/50">
                {platforms.length} 个平台 &middot; 近 7 日
              </span>
            </CardHeader>
            <CardContent className="p-0">
              {alertPlatforms.length === 0 ? (
                <div className="text-center py-6">
                  <p className="text-sm text-muted-foreground/70">所有平台识别准确率均达标</p>
                </div>
              ) : (
                <div className="rounded-lg border border-border bg-card overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr className="bg-muted/50 border-b">
                          <th className="text-left px-4 py-3 font-medium text-muted-foreground">优先级</th>
                          <th className="text-left px-4 py-3 font-medium text-muted-foreground">平台</th>
                          <th className="text-right px-4 py-3 font-medium text-muted-foreground">准确率</th>
                          <th className="text-right px-4 py-3 font-medium text-muted-foreground">错误数</th>
                          <th className="text-right px-4 py-3 font-medium text-muted-foreground">识别量</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {alertPlatforms.map((p) => {
                          const tier = getStatusTier(p.accuracy);
                          const priority = tier === "alert" ? "高" : "中";
                          const priorityColor = tier === "alert" ? "text-red-600" : "text-amber-600";
                          return (
                            <tr key={p.platform_id || "__global__"} className="hover:bg-muted/50">
                              <td className="px-4 py-2.5">
                                <span className={`text-xs font-semibold ${priorityColor}`}>{priority}</span>
                              </td>
                              <td className="px-4 py-2.5 font-medium">{p.platform_name}</td>
                              <td className="px-4 py-2.5 text-right font-mono tabular-nums">
                                {formatPercent(p.accuracy)}
                              </td>
                              <td className="px-4 py-2.5 text-right">{p.incorrect}</td>
                              <td className="px-4 py-2.5 text-right text-muted-foreground/70">
                                {p.total.toLocaleString()} 次
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── History Table ── */}
        {history.length > 0 && (
          <Card>
            <CardHeader className="pb-3 flex flex-row items-center justify-between">
              <CardTitle className="text-sm">历史记录</CardTitle>
              <span className="text-xs text-muted-foreground/50">{history.length} 条</span>
            </CardHeader>
            <CardContent className="p-0">
              <div className="rounded-lg border border-border bg-card overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="bg-muted/50 border-b">
                        <th className="text-left px-4 py-3 font-medium text-muted-foreground">日期</th>
                        <th className="text-left px-4 py-3 font-medium text-muted-foreground">平台</th>
                        <th className="text-right px-4 py-3 font-medium text-muted-foreground">识别总数</th>
                        <th className="text-right px-4 py-3 font-medium text-muted-foreground">正确数</th>
                        <th className="text-right px-4 py-3 font-medium text-muted-foreground">准确率</th>
                        <th className="text-center px-4 py-3 font-medium text-muted-foreground">状态</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {history.map((row) => {
                        const tier = getStatusTier(Number(row.accuracy));
                        return (
                          <tr key={row.id} className="hover:bg-muted/50">
                            <td className="px-4 py-3">{row.period_date}</td>
                            <td className="px-4 py-3 text-muted-foreground/70">
                              {row.platform_name || "全局"}
                            </td>
                            <td className="px-4 py-3 text-right">{row.total_recognitions}</td>
                            <td className="px-4 py-3 text-right">{row.correct_recognitions}</td>
                            <td className="px-4 py-3 text-right font-mono tabular-nums">
                              {formatPercent(Number(row.accuracy))}
                            </td>
                            <td className="px-4 py-3 text-center">
                              <Badge className={STATUS_STYLE[tier]}>
                                {STATUS_LABEL[tier]}
                              </Badge>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

      </div>
    </Panel>
  );
}
