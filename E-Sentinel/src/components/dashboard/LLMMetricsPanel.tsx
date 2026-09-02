"use client";

import { useState, useEffect, useCallback } from "react";
import Panel from "./Panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Zap, Coins } from "lucide-react";
import { formatCurrency, formatCompactPercent, formatDecimal } from "@/lib/utils";

interface LLMMetricsData {
  metrics: {
    totalCalls: number;
    successRate: number;
    avgResponseTimeMs: number;
    totalTokens: number;
    totalCost: number;
    cacheHitRate: number;
    byModel: Record<string, { calls: number; avgMs: number; tokens: number; cost: number }>;
    byEndpoint: Record<string, { calls: number; avgMs: number; errorCount: number }>;
    recentErrors: Array<{ endpoint: string; model: string; time: string }>;
  };
  slow_queries: Array<{
    endpoint: string;
    model: string;
    response_time_ms: number;
    tokens: number;
    cached: boolean;
    success: boolean;
    timestamp: string;
  }>;
  cache: { hits: number; misses: number; size: number; hitRate: number };
  thresholds: {
    alert_error_rate: number;
    alert_slow_ms: number;
    alert_cost_per_hour: number;
  };
}

export default function LLMMetricsPanel() {
  const [data, setData] = useState<LLMMetricsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [windowMs, setWindowMs] = useState(3600000);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`/api/qa/llm-metrics?window_ms=${windowMs}`);
      const json = await res.json();
      if (json.error) { setError(json.error); return; }
      setData(json);
    } catch {
      setError("Failed to load LLM metrics");
    } finally {
      setLoading(false);
    }
  }, [windowMs]);

  useEffect(() => { fetchData(); const interval = setInterval(fetchData, 30000); return () => clearInterval(interval); }, [fetchData]);

  const m = data?.metrics;
  const alertError = m && data && (1 - m.successRate) > data.thresholds.alert_error_rate;
  const alertSlow = m && m.avgResponseTimeMs > 8000;
  const alertCost = m && m.totalCost > 50;

  return (
    <Panel
      title="大模型可观测性"
      subtitle={`${m?.totalCalls || 0} 次调用${m ? ` · 成功率 ${m.totalCalls === 0 ? "—" : formatCompactPercent(m.successRate)}` : ""} · 均时 ${m?.avgResponseTimeMs || 0}ms`}
      loading={loading}
      error={error}
      onRetry={fetchData}
      empty={!loading && !error && (!data || (m && m.totalCalls === 0 && data.slow_queries.length === 0))}
      emptyTitle="暂无调用数据"
      emptyDescription="LLM 调用记录将在 API 调用时自动采集，数据每 30 秒刷新一次。"
    >
      {/* Time window selector */}
      <div className="flex gap-1 mb-4">
        {[{ label: "1小时", ms: 3600000 }, { label: "6小时", ms: 21600000 }, { label: "24小时", ms: 86400000 }].map((w) => (
          <button
            key={w.ms}
            onClick={() => setWindowMs(w.ms)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              windowMs === w.ms ? "bg-foreground text-white" : "bg-muted text-muted-foreground hover:bg-border"
            }`}
          >
            {w.label}
          </button>
        ))}
      </div>

      {/* Alert banners */}
      <div className="space-y-1 mb-4">
        {alertError && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-700 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
            错误率 {formatCompactPercent(1 - (m?.successRate || 0))} 超过阈值 {formatCompactPercent(data?.thresholds.alert_error_rate || 0.05)}
          </div>
        )}
        {alertSlow && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg px-3 py-2 text-xs text-yellow-700 flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
            平均响应时间 {m?.avgResponseTimeMs}ms 超过阈值 {data?.thresholds.alert_slow_ms || 8000}ms
          </div>
        )}
        {alertCost && (
          <div className="bg-orange-50 border border-orange-200 rounded-lg px-3 py-2 text-xs text-orange-700 flex items-center gap-1.5">
            <Coins className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
            费用 {formatCurrency(m?.totalCost)} 超过阈值 {formatCurrency(data?.thresholds.alert_cost_per_hour || 50)}/小时
          </div>
        )}
      </div>

      {/* Summary cards */}
      {m && (
        <div className="grid grid-cols-6 gap-3 mb-5">
          <div className="bg-white border rounded-lg p-3"><div className="text-xs text-muted-foreground/70">调用次数</div><div className="text-xl font-bold mt-0.5">{m.totalCalls}</div></div>
          <div className={`bg-white border rounded-lg p-3 ${alertError ? "border-red-300" : ""}`}><div className="text-xs text-muted-foreground/70">成功率</div><div className={`text-xl font-bold mt-0.5 ${m.successRate < 0.95 ? "text-red-600" : "text-green-600"}`}>{m.totalCalls === 0 ? "—" : formatCompactPercent(m.successRate)}</div></div>
          <div className={`bg-white border rounded-lg p-3 ${alertSlow ? "border-yellow-300" : ""}`}><div className="text-xs text-muted-foreground/70">平均响应</div><div className="text-xl font-bold mt-0.5">{m.avgResponseTimeMs}ms</div></div>
          <div className="bg-white border rounded-lg p-3"><div className="text-xs text-muted-foreground/70">Token 消耗</div><div className="text-xl font-bold mt-0.5">{(m.totalTokens / 1000).toFixed(1)}K</div></div>
          <div className={`bg-white border rounded-lg p-3 ${alertCost ? "border-orange-300" : ""}`}><div className="text-xs text-muted-foreground/70">预估费用</div><div className="text-xl font-bold mt-0.5">{formatCurrency(m.totalCost)}</div></div>
          <div className="bg-white border rounded-lg p-3"><div className="text-xs text-muted-foreground/70">缓存命中率</div><div className="text-xl font-bold mt-0.5">{m.totalCalls === 0 ? "—" : formatCompactPercent(m.cacheHitRate)}</div></div>
        </div>
      )}

      {/* By model breakdown */}
      {m && Object.keys(m.byModel).length > 0 && (
        <div className="bg-white border rounded-lg overflow-hidden mb-5">
          <div className="px-4 py-2 bg-muted/50 border-b text-xs font-medium text-muted-foreground">按模型统计</div>
          <table className="w-full text-sm">
            <thead><tr className="bg-muted/50 border-b"><th className="text-left px-4 py-2 text-xs text-muted-foreground/70">模型</th><th className="text-right px-4 py-2 text-xs text-muted-foreground/70">调用数</th><th className="text-right px-4 py-2 text-xs text-muted-foreground/70">均时</th><th className="text-right px-4 py-2 text-xs text-muted-foreground/70">Token</th><th className="text-right px-4 py-2 text-xs text-muted-foreground/70">费用</th></tr></thead>
            <tbody className="divide-y">
              {Object.entries(m.byModel).map(([model, stats]) => (
                <tr key={model}><td className="px-4 py-2 font-medium text-xs">{model}</td><td className="px-4 py-2 text-right text-xs">{stats.calls}</td><td className="px-4 py-2 text-right text-xs">{stats.avgMs}ms</td><td className="px-4 py-2 text-right text-xs">{(stats.tokens / 1000).toFixed(1)}K</td><td className="px-4 py-2 text-right text-xs">{formatCurrency(stats.cost)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* By endpoint breakdown */}
      {m && Object.keys(m.byEndpoint).length > 0 && (
        <div className="bg-white border rounded-lg overflow-hidden mb-5">
          <div className="px-4 py-2 bg-muted/50 border-b text-xs font-medium text-muted-foreground">按接口统计</div>
          <table className="w-full text-sm">
            <thead><tr className="bg-muted/50 border-b"><th className="text-left px-4 py-2 text-xs text-muted-foreground/70">接口</th><th className="text-right px-4 py-2 text-xs text-muted-foreground/70">调用数</th><th className="text-right px-4 py-2 text-xs text-muted-foreground/70">均时</th><th className="text-right px-4 py-2 text-xs text-muted-foreground/70">错误数</th></tr></thead>
            <tbody className="divide-y">
              {Object.entries(m.byEndpoint).map(([ep, stats]) => (
                <tr key={ep}><td className="px-4 py-2 font-mono text-xs">{ep}</td><td className="px-4 py-2 text-right text-xs">{stats.calls}</td><td className="px-4 py-2 text-right text-xs">{stats.avgMs}ms</td><td className="px-4 py-2 text-right text-xs">{stats.errorCount > 0 ? <span className="text-destructive font-medium">{stats.errorCount}</span> : <span className="text-muted-foreground/50">0</span>}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Cache stats */}
      {data?.cache && (
        <div className="grid grid-cols-4 gap-3 mb-5">
          <div className="bg-white border rounded-lg p-3"><div className="text-xs text-muted-foreground/70">缓存命中</div><div className="text-lg font-bold mt-0.5">{data.cache.hits}</div></div>
          <div className="bg-white border rounded-lg p-3"><div className="text-xs text-muted-foreground/70">缓存未命中</div><div className="text-lg font-bold mt-0.5">{data.cache.misses}</div></div>
          <div className="bg-white border rounded-lg p-3"><div className="text-xs text-muted-foreground/70">命中率</div><div className="text-lg font-bold mt-0.5">{formatCompactPercent(data.cache.hitRate)}</div></div>
          <div className="bg-white border rounded-lg p-3"><div className="text-xs text-muted-foreground/70">缓存条目</div><div className="text-lg font-bold mt-0.5">{data.cache.size}</div></div>
        </div>
      )}

      {/* Slow queries */}
      {data?.slow_queries && data.slow_queries.length > 0 && (
        <div className="bg-white border rounded-lg overflow-hidden mb-5">
          <div className="px-4 py-2 bg-red-50 border-b text-xs font-medium text-red-700">慢查询 ({data.slow_queries.length})</div>
          <table className="w-full text-sm">
            <thead><tr className="bg-muted/50 border-b"><th className="text-left px-4 py-2 text-xs text-muted-foreground/70">端点</th><th className="text-left px-4 py-2 text-xs text-muted-foreground/70">模型</th><th className="text-right px-4 py-2 text-xs text-muted-foreground/70">响应时间</th><th className="text-center px-4 py-2 text-xs text-muted-foreground/70">时间</th></tr></thead>
            <tbody className="divide-y">
              {data.slow_queries.map((q, i) => (
                <tr key={i}><td className="px-4 py-2 text-xs font-mono">{q.endpoint}</td><td className="px-4 py-2 text-xs">{q.model}</td><td className="px-4 py-2 text-right text-xs text-red-600 font-mono">{q.response_time_ms}ms</td><td className="px-4 py-2 text-center text-xs text-muted-foreground/50">{new Date(q.timestamp).toLocaleTimeString("zh-CN")}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent errors */}
      {m && m.recentErrors.length > 0 && (
        <div className="bg-white border rounded-lg overflow-hidden">
          <div className="px-4 py-2 bg-red-50 border-b text-xs font-medium text-red-700">最近错误 ({m.recentErrors.length})</div>
          <table className="w-full text-sm">
            <thead><tr className="bg-muted/50 border-b"><th className="text-left px-4 py-2 text-xs text-muted-foreground/70">端点</th><th className="text-left px-4 py-2 text-xs text-muted-foreground/70">模型</th><th className="text-left px-4 py-2 text-xs text-muted-foreground/70">时间</th></tr></thead>
            <tbody className="divide-y">
              {m.recentErrors.map((err, i) => (
                <tr key={i}><td className="px-4 py-2 text-xs font-mono">{err.endpoint}</td><td className="px-4 py-2 text-xs">{err.model}</td><td className="px-4 py-2 text-xs text-muted-foreground/50">{new Date(err.time).toLocaleString("zh-CN")}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4 text-xs text-muted-foreground/50">数据每 30 秒自动刷新 · 最多保留 1000 条记录</div>
    </Panel>
  );
}
