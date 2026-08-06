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
import type { BotChatSession } from "@/lib/types/bot";

export default function InquiryLossPanel() {
  const [metrics, setMetrics] = useState<any>(null);
  const [lossSessions, setLossSessions] = useState<BotChatSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [page, setPage] = useState(0);

  const fetchMetrics = useCallback(async () => {
    const res = await fetch("/api/qa/inquiry-loss");
    if (res.ok) setMetrics(await res.json());
  }, []);

  const fetchLossSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/qa/inquiry-loss/detail?limit=10&offset=${page * 10}`);
      if (res.ok) {
        const data = await res.json();
        setLossSessions(data.sessions || []);
      } else {
        const errData = await res.json().catch(() => ({ error: "加载失败" }));
        setError(errData.error || "加载流失会话失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setLoading(false);
  }, [page]);

  useEffect(() => {
    fetchMetrics();
    fetchLossSessions();
  }, [fetchMetrics, fetchLossSessions]);

  const isEmpty = !loading && !error && lossSessions.length === 0;

  return (
    <Panel
      title="询单流失分析"
      subtitle="追踪询单转化漏斗，定位流失根因"
      loading={loading}
      error={error}
      onRetry={fetchLossSessions}
      empty={isEmpty}
      emptyTitle="暂无流失会话数据"
      emptyDescription="导入机器人聊天记录后，流失会话将在此展示"
    >
      <div className="space-y-4">
        {/* Metrics */}
        {metrics && (
          <div className="grid grid-cols-4 gap-3">
            <MetricCard label="总询单数" value={metrics.total_inquiries || 0} intent="neutral" />
            <MetricCard
              label="转化率"
              value={formatPercent(metrics.conversion_rate)}
              intent={metrics.conversion_rate > 0.6 ? "success" : "warning"}
            />
            <MetricCard label="流失数" value={metrics.lost ?? 0} intent="danger" />
            <MetricCard
              label="流失率"
              value={formatPercent(metrics.total_inquiries > 0 ? (metrics.lost ?? 0) / metrics.total_inquiries : 0)}
              intent={metrics.total_inquiries > 0 ? (metrics.lost ?? 0) / metrics.total_inquiries < 0.2 ? "success" : "danger" : "neutral"}
            />
          </div>
        )}

        {/* Loss by reason */}
        {(() => {
          const reasons = metrics?.loss_by_reason as Array<{ reason: string; count: number }> | undefined;
          if (!reasons || reasons.length === 0) return null;
          const maxCount = Math.max(...reasons.map(r => r.count));
          return (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-medium">流失原因分布</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {reasons.map((item, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <span className="text-xs w-24 truncate">{item.reason}</span>
                      <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                        <div
                          className="h-full bg-red-400 rounded-full"
                          style={{ width: `${Math.max((item.count / maxCount) * 100, 2)}%` }}
                        />
                      </div>
                      <span className="text-xs text-muted-foreground/70 w-8 text-right">{item.count}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          );
        })()}

        <LlmAnalysisCard
          title="LLM 流失根因分析"
          endpoint="/api/qa/inquiry-loss/analyze"
          triggerLabel="分析"
          placeholder="点击「分析」按钮，AI 将自动定位询单流失根因并给出优化建议"
          renderResult={(raw) => {
            const d = raw as Record<string, unknown>;
            const causes = d.root_causes as Array<{ cause: string; count: number; examples?: string[]; suggestion?: string }> | undefined;
            const overview = d.overall_analysis as string | undefined;
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
                    {item.suggestion && (
                      <p className="mt-2 text-xs text-blue-700 bg-blue-50 p-2 rounded">
                        建议：{item.suggestion}
                      </p>
                    )}
                  </div>
                ))}
                {overview && (
                  <div className="p-3 bg-muted/50 rounded-md">
                    <p className="text-xs text-muted-foreground leading-relaxed">{overview}</p>
                  </div>
                )}
              </div>
            );
          }}
        />

        {/* Lost sessions */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium flex items-center justify-between">
              <span>流失会话明细</span>
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
                  <TableHead>类型</TableHead>
                  <TableHead>消息数</TableHead>
                  <TableHead>转人工原因</TableHead>
                  <TableHead>时间</TableHead>
                  <TableHead className="text-right">对话</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lossSessions.map((s, i) => (
                  <TableRow key={s.id || i} className={`hover:bg-muted/50 ${expandedId === i ? "bg-muted/50" : ""}`}>
                    <TableCell className="font-mono text-xs">
                      {s.external_session_id?.slice(-10) || s.id?.slice(-8) || "—"}
                    </TableCell>
                    <TableCell className="text-xs">{s.platform_name || "—"}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {s.session_type === "pre_sale" ? "售前" : "售后"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">{s.total_messages}</TableCell>
                    <TableCell className="text-xs text-red-600 max-w-[150px] truncate">
                      {s.transfer_reason || "—"}
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
        {expandedId !== null && lossSessions[expandedId] && (
          <Card className="border-blue-100">
            <CardContent className="py-3">
              <ConversationBubbles conversation={lossSessions[expandedId].conversation} />
            </CardContent>
          </Card>
        )}
      </div>
    </Panel>
  );
}
