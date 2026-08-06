"use client";

import { useEffect, useState, useCallback } from "react";
import Panel from "./Panel";
import { formatCompactPercent, formatCurrency } from "@/lib/utils";

interface CostSavingsData {
  thisMonth: {
    aiSessions: number;
    hoursSaved: number;
    costSaved: number;
  };
  monthlyTrend: Array<{ month: string; aiSessions: number }>;
  today: {
    total: number;
    aiHandled: number;
    humanHandled: number;
    aiRate: number;
  };
}

function SkeletonCard() {
  return <div className="h-24 bg-muted rounded-lg animate-pulse" />;
}

function SkeletonBar() {
  return <div className="h-32 bg-muted rounded-lg animate-pulse" />;
}

function SkeletonRow() {
  return <div className="h-10 bg-muted rounded animate-pulse" />;
}

export default function CostSavingsPanel() {
  const [data, setData] = useState<CostSavingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/qa/cost-savings");
      if (!res.ok) {
        const errData = await res.json().catch(() => ({ error: "request failed" }));
        setError(errData.error || "加载成本数据失败");
        return;
      }
      const json = await res.json();
      setData(json);
    } catch {
      setError("网络请求失败，请检查后端服务");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const isEmpty = !loading && !error && data !== null && data.monthlyTrend.length === 0;

  // Find max sessions for bar chart scale
  const maxSessions = data?.monthlyTrend.reduce(
    (max, m) => Math.max(max, m.aiSessions),
    0
  ) ?? 1;

  return (
    <Panel
      title="降本看板"
      subtitle="AI 客服降本增效数据可视看板"
      loading={loading}
      error={error}
      onRetry={fetchData}
      empty={isEmpty}
      emptyTitle="暂无数据"
      emptyDescription="bot_chat_sessions 表中暂无 AI 处理记录"
    >
      {/* Top row: 3 stat cards */}
      {loading && !error && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
          <SkeletonBar />
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </div>
      )}

      {data && !loading && !error && !isEmpty && (
        <div className="space-y-6">
          {/* Stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-white rounded-lg shadow-sm p-5 border border-border">
              <p className="text-xs font-medium text-muted-foreground/70 uppercase tracking-wide mb-1">
                本月 AI 处理量
              </p>
              <p className="text-3xl font-bold text-foreground">
                {data.thisMonth.aiSessions.toLocaleString()}
              </p>
              <p className="text-xs text-muted-foreground/50 mt-1">AI 独立完成的会话数</p>
            </div>

            <div className="bg-white rounded-lg shadow-sm p-5 border border-border">
              <p className="text-xs font-medium text-muted-foreground/70 uppercase tracking-wide mb-1">
                节省工时
              </p>
              <p className="text-3xl font-bold text-foreground">
                {data.thisMonth.hoursSaved.toLocaleString()}
                <span className="text-lg font-normal text-muted-foreground/70 ml-1">小时</span>
              </p>
              <p className="text-xs text-muted-foreground/50 mt-1">
                按每条 AI 回复节省 2 分钟计算
              </p>
            </div>

            <div className="bg-white rounded-lg shadow-sm p-5 border border-brand-200 bg-gradient-to-br from-brand-50 to-white">
              <p className="text-xs font-medium text-brand-600 uppercase tracking-wide mb-1">
                节省成本
              </p>
              <p className="text-3xl font-bold text-brand-600">
                ¥{data.thisMonth.costSaved.toLocaleString()}
              </p>
              <p className="text-xs text-brand-400 mt-1">
                按客服时薪 25 元/时计算
              </p>
            </div>
          </div>

          {/* Monthly trend chart */}
          <div className="bg-white rounded-lg shadow-sm border border-border p-5">
            <h3 className="text-sm font-semibold text-foreground/70 mb-4">
              月度 AI 处理趋势（近 6 个月）
            </h3>
            <div className="space-y-2">
              {data.monthlyTrend.map((m) => {
                const pct = maxSessions > 0 ? (m.aiSessions / maxSessions) * 100 : 0;
                const [year, monthNum] = m.month.split("-");
                return (
                  <div key={m.month} className="flex items-center gap-3">
                    <span className="text-xs text-muted-foreground/70 w-16 shrink-0 text-right">
                      {Number(monthNum)} 月
                    </span>
                    <div className="flex-1 bg-muted rounded-full h-6 overflow-hidden">
                      <div
                        className="h-full bg-brand-500 rounded-full transition-all duration-500 flex items-center justify-end pr-2 min-w-[2rem]"
                        style={{ width: `${Math.max(pct, 2)}%` }}
                      >
                        {pct > 10 && (
                          <span className="text-[10px] text-white font-medium">
                            {m.aiSessions.toLocaleString()}
                          </span>
                        )}
                      </div>
                    </div>
                    {pct <= 10 && (
                      <span className="text-xs text-muted-foreground/70 w-16 shrink-0">
                        {m.aiSessions.toLocaleString()}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Today's overview table */}
          <div className="bg-white rounded-lg shadow-sm border border-border overflow-hidden">
            <h3 className="text-sm font-semibold text-foreground/70 px-5 pt-5 pb-3">
              今日概览
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-muted">
                  <th className="text-left px-5 py-2 font-medium text-muted-foreground/70 text-xs uppercase tracking-wide">
                    指标
                  </th>
                  <th className="text-right px-5 py-2 font-medium text-muted-foreground/70 text-xs uppercase tracking-wide">
                    数值
                  </th>
                  <th className="text-right px-5 py-2 font-medium text-muted-foreground/70 text-xs uppercase tracking-wide">
                    占比
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-muted/50">
                <tr>
                  <td className="px-5 py-3 text-foreground/70">今日总会话</td>
                  <td className="px-5 py-3 text-right font-semibold text-foreground">
                    {data.today.total.toLocaleString()}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground/50">100%</td>
                </tr>
                <tr>
                  <td className="px-5 py-3 text-foreground/70">
                    <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 mr-2" />
                    AI 处理量
                  </td>
                  <td className="px-5 py-3 text-right font-semibold text-emerald-600">
                    {data.today.aiHandled.toLocaleString()}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground/50">
                    {data.today.total > 0
                      ? formatCompactPercent(data.today.aiHandled / data.today.total)
                      : "—"}
                  </td>
                </tr>
                <tr>
                  <td className="px-5 py-3 text-foreground/70">
                    <span className="inline-block w-2 h-2 rounded-full bg-amber-500 mr-2" />
                    人工接管量
                  </td>
                  <td className="px-5 py-3 text-right font-semibold text-amber-600">
                    {data.today.humanHandled.toLocaleString()}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground/50">
                    {data.today.total > 0
                      ? formatCompactPercent(data.today.humanHandled / data.today.total)
                      : "—"}
                  </td>
                </tr>
                <tr className="bg-muted/50">
                  <td className="px-5 py-3 font-medium text-foreground">AI 解决率</td>
                  <td className="px-5 py-3 text-right">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-brand-100 text-brand-700">
                      {data.today.aiRate}%
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right text-xs text-muted-foreground/50">
                    AI 处理 / 总会话
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Panel>
  );
}
