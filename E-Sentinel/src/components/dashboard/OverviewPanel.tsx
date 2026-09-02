"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Clock3,
  MessageSquare,
  RefreshCw,
  Shield,
  Users,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import Panel from "@/components/dashboard/Panel";

interface OverviewData {
  generated_at: string;
  ai_service_value: {
    total_conversations: number;
    ai_handled: number;
    ai_handle_rate: number;
    transferred_to_human: number;
  };
  diagnosis: {
    total_sessions: number;
    diagnosed_findings: number;
    top_reasons: { category: string; count: number }[];
  };
  work_orders: {
    total: number;
    pending: number;
    in_progress: number;
    completed: number;
    overdue: number;
  };
  knowledge_base: {
    total_entries: number;
    pending_approval: number;
  };
  quality: {
    total_reports: number;
    critical_count: number;
    pending_review: number;
    avg_score: number;
  };
}

const REASON_LABELS: Record<string, string> = {
  traffic_quality: "流量质量",
  product_mismatch: "商品不匹配",
  price_objection: "价格异议",
  trust_deficit: "信任不足",
  service_failure: "客服问题",
  inventory_fulfillment: "库存/履约",
  payment_followup: "支付/跟进",
};

function formatNumber(value: number): string {
  return value.toLocaleString("zh-CN");
}

function MetricCard({
  title,
  value,
  unit,
  icon: Icon,
  trend,
  trendUp,
  subtitle,
}: {
  title: string;
  value: string | number;
  unit?: string;
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  trend?: string;
  trendUp?: boolean;
  subtitle?: string;
}) {
  return (
    <Card size="sm" className="min-w-0">
      <CardHeader className="pb-1">
        <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
          <Icon className="w-3.5 h-3.5 text-primary" strokeWidth={2} />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-bold tracking-[-0.02em] tabular-nums text-foreground">
            {value}
          </span>
          {unit && <span className="text-xs text-muted-foreground/70">{unit}</span>}
        </div>
        {trend && (
          <div className="flex items-center gap-1 mt-1">
            {trendUp ? (
              <ArrowUpRight className="w-3 h-3 metric-up" />
            ) : (
              <ArrowDownRight className="w-3 h-3 metric-down" />
            )}
            <span className={`text-xs ${trendUp ? "metric-up" : "metric-down"}`}>
              {trend}
            </span>
          </div>
        )}
        {subtitle && (
          <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function OverviewPanel() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/qa/overview", { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || "加载失败");
      setData(body as OverviewData);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchData();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [fetchData]);

  return (
    <Panel
      title="经营总览"
      subtitle="AI 电商运营核心指标与证据追溯"
      loading={loading}
      error={error}
      onRetry={fetchData}
      actions={
        <Button size="sm" variant="outline" onClick={fetchData} disabled={loading}>
          <RefreshCw aria-hidden="true" className={loading ? "animate-spin" : undefined} />
          刷新
        </Button>
      }
    >
      {data && (
        <div className="space-y-4">
          {/* 数据生成时间 */}
          <div className="flex items-center justify-end gap-1 text-xs text-muted-foreground">
            <Clock3 className="w-3.5 h-3.5" />
            数据更新于{" "}
            {new Date(data.generated_at).toLocaleString("zh-CN", {
              hour12: false,
            })}
          </div>

          {/* 核心指标概览 */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="总咨询量"
              value={formatNumber(data.ai_service_value.total_conversations)}
              unit="次"
              icon={MessageSquare}
            />
            <MetricCard
              title="AI 接待量"
              value={formatNumber(data.ai_service_value.ai_handled)}
              unit="次"
              icon={Bot}
              subtitle={`接待率 ${data.ai_service_value.ai_handle_rate}%`}
            />
            <MetricCard
              title="转人工"
              value={formatNumber(data.ai_service_value.transferred_to_human)}
              unit="次"
              icon={Users}
            />
            <MetricCard
              title="知识库条目"
              value={formatNumber(data.knowledge_base.total_entries)}
              unit="条"
              icon={Activity}
              subtitle={`待审核 ${data.knowledge_base.pending_approval}`}
            />
          </div>

          {/* Diagnosis & Work Orders */}
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Diagnosis Stats */}
            <Card>
              <CardHeader className="border-b pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Zap className="w-4 h-4" />
                  未成交诊断
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-xs text-muted-foreground">诊断会话</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {formatNumber(data.diagnosis.total_sessions)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">发现原因</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {formatNumber(data.diagnosis.diagnosed_findings)}
                    </p>
                  </div>
                </div>
                {data.diagnosis.top_reasons.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {data.diagnosis.top_reasons.map((reason) => (
                      <Badge
                        key={reason.category}
                        variant="outline"
                        className="text-xs"
                      >
                        {REASON_LABELS[reason.category] || reason.category} ×
                        {reason.count}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Work Orders */}
            <Card>
              <CardHeader className="border-b pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Shield className="w-4 h-4" />
                  运营任务
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4">
                <div className="grid gap-3 sm:grid-cols-4">
                  <div>
                    <p className="text-xs text-muted-foreground">待处理</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums text-warning">
                      {data.work_orders.pending}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">进行中</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums text-info">
                      {data.work_orders.in_progress}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">已完成</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums text-success">
                      {data.work_orders.completed}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">合计</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {data.work_orders.total}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* 质检统计（近 7 天） */}
          <Card>
            <CardHeader className="border-b pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4" />
                质检统计
                <span className="text-xs font-normal text-muted-foreground">
                  近 7 天
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 p-4 sm:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">质检报告</p>
                <p className="mt-1 text-lg font-semibold tabular-nums">
                  {formatNumber(data.quality.total_reports)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">平均分</p>
                <p className="mt-1 text-lg font-semibold tabular-nums">
                  {data.quality.total_reports > 0 ? data.quality.avg_score : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Critical 风险</p>
                <p
                  className={`mt-1 text-lg font-semibold tabular-nums ${
                    data.quality.critical_count === 0
                      ? "text-success"
                      : "text-destructive"
                  }`}
                >
                  {data.quality.critical_count}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">待复核</p>
                <p className="mt-1 text-lg font-semibold tabular-nums text-warning">
                  {data.quality.pending_review}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </Panel>
  );
}