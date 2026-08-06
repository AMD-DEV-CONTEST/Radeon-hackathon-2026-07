"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Panel from "./Panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Users, TrendingUp, TrendingDown, Minus, AlertTriangle, ArrowRight } from "lucide-react";
import type { DashboardTab } from "@/components/dashboard/SidebarNav";
import { cn } from "@/lib/utils";

interface AgentPerformance {
  id: string;
  name: string;
  team_id: string | null;
  total_reports: number;
  avg_score: number | null;
  min_score: number | null;
  max_score: number | null;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  total_violations: number;
  trend: string;
  category_breakdown: Record<string, number>;
}

interface PerformanceData {
  period: string;
  total_agents: number;
  evaluated_agents: number;
  overall_avg_score: number | null;
  overall_critical_count: number;
  overall_violations: number;
  agents: AgentPerformance[];
}

const TREND_META: Record<string, { label: string; icon: React.ReactNode; cls: string }> = {
  improving: { label: "上升", icon: <TrendingUp className="w-3 h-3" strokeWidth={2.5} />, cls: "bg-success/10 text-success border-success/20" },
  declining: { label: "下降", icon: <TrendingDown className="w-3 h-3" strokeWidth={2.5} />, cls: "bg-destructive/10 text-destructive border-destructive/20" },
  stable: { label: "稳定", icon: <Minus className="w-3 h-3" strokeWidth={2.5} />, cls: "bg-muted text-muted-foreground border-border" },
  insufficient_data: { label: "数据不足", icon: <Minus className="w-3 h-3" strokeWidth={2.5} />, cls: "bg-muted/60 text-muted-foreground/70 border-border/60" },
  no_data: { label: "暂无数据", icon: <Minus className="w-3 h-3" strokeWidth={2.5} />, cls: "bg-muted/40 text-muted-foreground/50 border-border/40" },
};

const THRESHOLD = 75;

export default function AgentPerformancePanel({
  onNavigate,
}: {
  onNavigate?: (tab: DashboardTab) => void;
} = {}) {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);
  const [sortBy, setSortBy] = useState<"critical" | "score_asc" | "score_desc" | "trend" | "violations">("critical");

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`/api/qa/agent-performance?days=${days}`);
      const json = await res.json();
      if (json.error) { setError(json.error); return; }
      setData(json);
    } catch {
      setError("加载绩效数据失败");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { fetchData(); }, [fetchData]);

  /** 低于阈值坐席：avg_score 非空且 < THRESHOLD，或存在红灯/高风险工单 */
  const belowThreshold = useMemo(() => {
    if (!data) return 0;
    return data.agents.filter((a) => (a.avg_score !== null && a.avg_score < THRESHOLD) || (a.critical_count + a.high_count) > 0).length;
  }, [data]);

  /** 排序后的坐席列表 */
  const sortedAgents = useMemo(() => {
    if (!data) return [];
    const list = [...data.agents];
    if (sortBy === "critical") list.sort((a, b) => (b.critical_count + b.high_count) - (a.critical_count + a.high_count));
    else if (sortBy === "score_asc") list.sort((a, b) => (a.avg_score ?? 101) - (b.avg_score ?? 101));
    else if (sortBy === "score_desc") list.sort((a, b) => (b.avg_score ?? -1) - (a.avg_score ?? -1));
    else if (sortBy === "violations") list.sort((a, b) => b.total_violations - a.total_violations);
    else if (sortBy === "trend") list.sort((a, b) => (a.trend === "declining" ? -1 : 0) - (b.trend === "declining" ? -1 : 0));
    return list;
  }, [data, sortBy]);

  const getScoreTone = (score: number | null): "text-success" | "text-foreground" | "text-warning" | "text-destructive" | "text-muted-foreground/30" => {
    if (score === null) return "text-muted-foreground/30";
    if (score >= 90) return "text-success";
    if (score >= THRESHOLD) return "text-foreground";
    if (score >= 60) return "text-warning";
    return "text-destructive";
  };

  const getScoreBarTone = (score: number | null) => {
    if (score === null) return "bg-border";
    if (score >= 90) return "bg-success";
    if (score >= THRESHOLD) return "bg-primary";
    if (score >= 60) return "bg-warning";
    return "bg-destructive";
  };

  return (
    <Panel
      title="坐席绩效评估"
      subtitle={`近${days}天 · 已评估 ${data?.evaluated_agents ?? 0}/${data?.total_agents ?? 0} 人 · 团队均分 ${data?.overall_avg_score ?? "—"}`}
      loading={loading}
      error={error}
      onRetry={fetchData}
      empty={!loading && (!data || data.agents.length === 0)}
      emptyIcon={<Users className="h-10 w-10" />}
      emptyTitle="已识别坐席，等待绩效画像"
      emptyDescription={`已识别 ${data?.total_agents ?? 0} 位坐席，等待质检数据生成绩效画像`}
      emptyAction={{ label: "前往质检中枢", onClick: () => onNavigate?.("qa") }}
    >
      {/* Period selector + 排序 */}
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex gap-1 bg-muted rounded-lg p-1">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={cn(
                "px-3 py-1 rounded text-xs font-medium transition-colors",
                days === d ? "bg-white text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              {d}天
            </button>
          ))}
        </div>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
          className="px-3 py-1.5 text-xs border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/20"
          aria-label="坐席排序"
        >
          <option value="critical">风险优先</option>
          <option value="score_asc">低分优先</option>
          <option value="score_desc">高分优先</option>
          <option value="trend">趋势下降</option>
          <option value="violations">违规数优先</option>
        </select>
      </div>

      {/* 决策卡 + 统计卡 */}
      {data && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          <div className="bg-white border rounded-lg p-3">
            <div className="text-xs text-muted-foreground/70">团队均分</div>
            <div className={cn("text-2xl font-bold mt-0.5 tabular-nums", getScoreTone(data.overall_avg_score))}>
              {data.overall_avg_score ?? "—"}
            </div>
            <div className="text-xs text-muted-foreground/50 mt-0.5">统计卡 · 团队健康度</div>
          </div>
          <div className="bg-white border rounded-lg p-3 relative overflow-hidden">
            <div className="text-xs text-muted-foreground/70">低于阈值坐席</div>
            <div className={cn("text-2xl font-bold mt-0.5 tabular-nums", belowThreshold > 0 ? "text-warning" : "text-foreground")}>
              {belowThreshold}
            </div>
            <div className="text-xs text-muted-foreground/50 mt-0.5">均分 &lt; {THRESHOLD} 或含红灯 · 决策卡</div>
            {belowThreshold > 0 && <span aria-hidden className="absolute left-0 top-0 bottom-0 w-[3px] bg-warning" />}
          </div>
          <div className="bg-white border rounded-lg p-3 relative overflow-hidden">
            <div className="text-xs text-muted-foreground/70">红灯工单</div>
            <div className={cn("text-2xl font-bold mt-0.5 tabular-nums", data.overall_critical_count > 0 ? "text-destructive" : "text-foreground")}>
              {data.overall_critical_count}
            </div>
            <div className="text-xs text-muted-foreground/50 mt-0.5">决策卡 · 需立即处置</div>
            {data.overall_critical_count > 0 && <span aria-hidden className="absolute left-0 top-0 bottom-0 w-[3px] bg-destructive" />}
          </div>
          <div className="bg-white border rounded-lg p-3">
            <div className="text-xs text-muted-foreground/70">总违规数</div>
            <div className={cn("text-2xl font-bold mt-0.5 tabular-nums", data.overall_violations > 0 ? "text-warning" : "text-foreground")}>
              {data.overall_violations}
            </div>
            <div className="text-xs text-muted-foreground/50 mt-0.5">统计卡 · 周期累计</div>
          </div>
        </div>
      )}

      {/* Ranking table */}
      {data && sortedAgents.length > 0 && (
        <div className="bg-white border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted border-b">
                <th className="text-left px-4 py-3 font-medium text-muted-foreground w-8">#</th>
                <th className="text-left px-4 py-3 font-medium text-muted-foreground">坐席</th>
                <th className="text-center px-4 py-3 font-medium text-muted-foreground w-40">均分</th>
                <th className="text-center px-4 py-3 font-medium text-muted-foreground w-16">最低</th>
                <th className="text-center px-4 py-3 font-medium text-muted-foreground w-16">质检数</th>
                <th className="text-center px-4 py-3 font-medium text-muted-foreground w-20">红灯/高</th>
                <th className="text-center px-4 py-3 font-medium text-muted-foreground w-16">违规</th>
                <th className="text-center px-4 py-3 font-medium text-muted-foreground w-24">趋势</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {sortedAgents.map((agent, index) => {
                const trend = TREND_META[agent.trend] || TREND_META.no_data;
                const riskCount = agent.critical_count + agent.high_count;
                return (
                  <tr key={agent.id} className={cn("hover:bg-muted/40 transition-colors", riskCount > 0 && "bg-destructive/[0.02]")}>
                    <td className="px-4 py-3 text-xs text-muted-foreground/50">{index + 1}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium">{agent.name}</div>
                      <div className="text-xs text-muted-foreground/50">{agent.total_reports} 次质检</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-muted rounded-full h-1.5 overflow-hidden">
                          <div className={cn("h-full rounded-full", getScoreBarTone(agent.avg_score))} style={{ width: `${agent.avg_score ?? 0}%` }} />
                        </div>
                        <span className={cn("font-mono text-xs font-medium tabular-nums w-7 text-right", getScoreTone(agent.avg_score))}>
                          {agent.avg_score ?? "—"}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-xs text-muted-foreground/70">{agent.min_score ?? "—"}</td>
                    <td className="px-4 py-3 text-center text-xs text-muted-foreground/70 tabular-nums">{agent.total_reports}</td>
                    <td className="px-4 py-3 text-center">
                      {riskCount > 0 ? (
                        <Badge className="bg-destructive/10 text-destructive border border-destructive/20 text-xs tabular-nums">
                          {agent.critical_count} / {agent.high_count}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground/30">0</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center text-xs text-muted-foreground/70 tabular-nums">{agent.total_violations}</td>
                    <td className="px-4 py-3 text-center">
                      <Badge variant="outline" className={cn("text-[10px] gap-1", trend.cls)}>
                        {trend.icon}
                        {trend.label}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

    </Panel>
  );
}
