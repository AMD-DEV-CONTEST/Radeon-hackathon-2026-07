// Report metrics computation, benchmark comparison, and formatting helpers.
// Used by /api/qa/reports/robot/generate and ReportsPanel.

import type { ReportType, IndustryBenchmark } from "./types/bot";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ReportMetrics {
  period: { start: string; end: string; type: string };
  sessions: { total: number; bot_handled: number; independent_reception_rate: number };
  satisfaction: { good: number; bad: number; rated: number; good_rate: number; bad_rate: number };
  inquiries: { total: number; converted: number; lost: number; conversion_rate: number };
  optimization: { open: number; resolved: number };
}

export interface BenchmarkComparison {
  [metric_name: string]: { our: number; industry_avg: number; industry_top: number };
}

// ── Metric metadata ────────────────────────────────────────────────────────────

export const METRIC_META: Record<string, { label: string; type: "percent" | "number" }> = {
  independent_reception_rate: { label: "独立接待率", type: "percent" },
  conversion_rate: { label: "询单转化率", type: "percent" },
  satisfaction_rate: { label: "满意度", type: "percent" },
  transfer_to_human_rate: { label: "转人工率", type: "percent" },
  first_response_time_sec: { label: "首次响应时间(秒)", type: "number" },
  avg_resolution_time_sec: { label: "平均解决时间(秒)", type: "number" },
  bot_handled_rate: { label: "机器人处理率", type: "percent" },
  refund_rate: { label: "退款率", type: "percent" },
  customer_retention_rate: { label: "客户留存率", type: "percent" },
  knowledge_hit_rate: { label: "知识库命中率", type: "percent" },
  script_coverage_rate: { label: "话术覆盖率", type: "percent" },
  inquiry_loss_rate: { label: "询单流失率", type: "percent" },
};

export function formatMetricLabel(key: string): string {
  return METRIC_META[key]?.label ?? key;
}

export function formatMetricValue(key: string, value: number | null | undefined): string {
  if (value == null) return "—";
  const meta = METRIC_META[key];
  if (meta?.type === "number") return value.toFixed(1);
  return `${(value * 100).toFixed(1)}%`;
}

export function getMetricType(key: string): "percent" | "number" {
  return METRIC_META[key]?.type ?? "percent";
}

// ── Period computation ─────────────────────────────────────────────────────────

export function getReportPeriod(
  reportType: ReportType,
  refDate: Date = new Date(),
): { start: string; end: string } {
  const d = new Date(refDate);
  d.setHours(0, 0, 0, 0);

  if (reportType === "daily") {
    const start = new Date(d);
    start.setDate(start.getDate() - 1);
    return { start: start.toISOString(), end: d.toISOString() };
  }
  if (reportType === "weekly") {
    const start = new Date(d);
    start.setDate(start.getDate() - 7);
    return { start: start.toISOString(), end: d.toISOString() };
  }
  // monthly
  const start = new Date(d);
  start.setMonth(start.getMonth() - 1);
  return { start: start.toISOString(), end: d.toISOString() };
}

// ── Metrics computation ────────────────────────────────────────────────────────

export function computeMetrics(
  sessions: Array<Record<string, unknown>>,
  optTasks: Array<Record<string, unknown>>,
  period: { start: string; end: string; type: string },
): ReportMetrics {
  const total = sessions.length;
  const botHandled = sessions.filter((s) => s.bot_handled).length;
  const independentRate = total > 0 ? botHandled / total : 0;

  const good = sessions.filter((s) => s.satisfaction === "good").length;
  const bad = sessions.filter((s) => s.satisfaction === "bad").length;
  const neutral = sessions.filter((s) => s.satisfaction === "neutral").length;
  const rated = good + bad + neutral;

  const inquiries = sessions.filter((s) => s.is_inquiry);
  const converted = inquiries.filter((s) => s.inquiry_result === "converted").length;
  const lost = inquiries.filter((s) => s.inquiry_result === "lost").length;

  const resolved = optTasks.filter((t) => t.status === "resolved").length;
  const open = optTasks.filter((t) => t.status === "open").length;

  return {
    period: { start: period.start, end: period.end, type: period.type },
    sessions: { total, bot_handled: botHandled, independent_reception_rate: independentRate },
    satisfaction: {
      good, bad, rated,
      good_rate: rated > 0 ? good / rated : 0,
      bad_rate: rated > 0 ? bad / rated : 0,
    },
    inquiries: {
      total: inquiries.length,
      converted,
      lost,
      conversion_rate: inquiries.length > 0 ? converted / inquiries.length : 0,
    },
    optimization: { open, resolved },
  };
}

// ── Benchmark comparison ───────────────────────────────────────────────────────

export function compareToBenchmarks(
  metrics: ReportMetrics,
  benchmarks: IndustryBenchmark[],
): BenchmarkComparison {
  const result: BenchmarkComparison = {};

  const ourValues: Record<string, number> = {
    independent_reception_rate: metrics.sessions.independent_reception_rate,
    conversion_rate: metrics.inquiries.conversion_rate,
    satisfaction_rate: metrics.satisfaction.good_rate,
  };

  for (const b of benchmarks) {
    const our = ourValues[b.metric_name];
    if (our !== undefined) {
      result[b.metric_name] = {
        our,
        industry_avg: b.industry_avg,
        industry_top: b.industry_top ?? b.industry_avg,
      };
    }
  }

  return result;
}

// ── Markdown formatting ────────────────────────────────────────────────────────

export function formatReportType(type: ReportType | string): string {
  if (type === "daily") return "日报";
  if (type === "weekly") return "周报";
  if (type === "monthly") return "月报";
  return type;
}

export function formatMetricsMarkdown(metrics: ReportMetrics): string {
  const { sessions, satisfaction, inquiries, optimization } = metrics;

  return [
    `## 整体概览`,
    `- 总会话数：${sessions.total}`,
    `- 机器人独立接待率：${(sessions.independent_reception_rate * 100).toFixed(1)}%`,
    ``,
    `## 满意度`,
    `- 好评率：${(satisfaction.good_rate * 100).toFixed(1)}%（${satisfaction.good}/${satisfaction.rated}）`,
    `- 差评率：${(satisfaction.bad_rate * 100).toFixed(1)}%（${satisfaction.bad}/${satisfaction.rated}）`,
    ``,
    `## 询单转化`,
    `- 询单总数：${inquiries.total}`,
    `- 转化率：${(inquiries.conversion_rate * 100).toFixed(1)}%（${inquiries.converted}）`,
    `- 流失率：${inquiries.total > 0 ? (inquiries.lost / inquiries.total * 100).toFixed(1) : "0.0"}%（${inquiries.lost}）`,
    ``,
    `## 优化进展`,
    `- 已解决：${optimization.resolved}`,
    `- 进行中：${optimization.open}`,
  ].join("\n");
}
