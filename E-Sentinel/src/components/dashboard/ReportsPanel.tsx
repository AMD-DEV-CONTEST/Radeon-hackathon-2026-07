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
import {
  Sheet,
  SheetContent,
} from "@/components/ui/sheet";
import { formatDateTime } from "@/lib/utils";
import Panel from "@/components/dashboard/Panel";
import ReportMarkdown from "@/components/dashboard/ReportMarkdown";
import type { RobotReport, IndustryBenchmark } from "@/lib/types/bot";
import { BarChart3, AlertTriangle, FileText } from "lucide-react";

const REPORT_LABELS: Record<string, string> = {
  daily: "日报", weekly: "周报", monthly: "月报",
};

const REPORT_COLORS: Record<string, string> = {
  daily: "bg-blue-100 text-blue-700 border-blue-200",
  weekly: "bg-purple-100 text-purple-700 border-purple-200",
  monthly: "bg-amber-100 text-amber-700 border-amber-200",
};

const METRIC_DICT: Record<string, { label: string; type: "percent" | "number" }> = {
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

function formatMetricValue(key: string, value: number | null | undefined): string {
  if (value == null) return "—";
  const def = METRIC_DICT[key];
  const type = def?.type ?? "percent";
  if (type === "number") return value.toFixed(1);
  return `${(value * 100).toFixed(1)}%`;
}

export default function ReportsPanel() {
  const [reports, setReports] = useState<RobotReport[]>([]);
  const [benchmarks, setBenchmarks] = useState<IndustryBenchmark[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genType, setGenType] = useState<"daily" | "weekly" | "monthly">("daily");
  const [genResult, setGenResult] = useState<RobotReport | null>(null);
  const [selectedReport, setSelectedReport] = useState<RobotReport | null>(null);
  const [viewingMd, setViewingMd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [benchError, setBenchError] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const fetchReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/qa/reports/robot/archive");
      if (res.ok) {
        const data = await res.json();
        setReports(data.reports || []);
      } else {
        const errData = await res.json().catch(() => ({ error: "request failed" }));
        setError(errData.error || "加载报告列表失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setLoading(false);
  }, []);

  const fetchBenchmarks = useCallback(async () => {
    setBenchError(null);
    try {
      const res = await fetch("/api/qa/industry-benchmarks");
      if (res.ok) {
        const data = await res.json();
        setBenchmarks(data.benchmarks || []);
      }
    } catch {
      setBenchError("行业基准数据暂不可用");
    }
  }, []);

  useEffect(() => {
    fetchReports();
    fetchBenchmarks();
  }, [fetchReports, fetchBenchmarks]);

  const getReportPeriod = (type: "daily" | "weekly" | "monthly") => {
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const end = now.toISOString();
    let start: Date;
    if (type === "daily") {
      start = new Date(now);
      start.setDate(start.getDate() - 1);
    } else if (type === "weekly") {
      start = new Date(now);
      start.setDate(start.getDate() - 7);
    } else {
      start = new Date(now);
      start.setMonth(start.getMonth() - 1);
    }
    return { period_start: start.toISOString(), period_end: end };
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setGenResult(null);
    setError(null);
    try {
      const period = getReportPeriod(genType);
      const res = await fetch("/api/qa/reports/robot/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_type: genType, ...period }),
      });
      if (res.ok) {
        const data = await res.json();
        setGenResult(data.report || data);
        fetchReports();
      } else {
        const errData = await res.json().catch(() => ({ error: "生成失败" }));
        setError(errData.error || "LLM 报告生成失败");
      }
    } catch {
      setError("LLM 服务暂不可用");
    }
    setGenerating(false);
  };

  const reportTypeCounts = {
    daily: reports.filter((r) => r.report_type === "daily").length,
    weekly: reports.filter((r) => r.report_type === "weekly").length,
    monthly: reports.filter((r) => r.report_type === "monthly").length,
  };

  const isEmpty = !loading && !error && reports.length === 0;

  return (
    <Panel
      title="数据中心"
      subtitle="机器人运营报告生成与行业对标分析"
      loading={loading}
      error={error}
      onRetry={fetchReports}
      empty={isEmpty}
      emptyTitle="暂无历史报告"
      emptyDescription="点击右上角「LLM 生成报告」按钮生成第一份报告"
      actions={
        <div className="flex items-center gap-2">
          <select
            className="rounded-lg border border-border bg-white px-3 py-1.5 text-xs font-medium text-foreground/70 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={genType}
            onChange={(e) => setGenType(e.target.value as "daily" | "weekly" | "monthly")}
          >
            <option value="daily">日报</option>
            <option value="weekly">周报</option>
            <option value="monthly">月报</option>
          </select>
          <Button size="sm" onClick={handleGenerate} disabled={generating}>
            {generating ? "LLM 生成中..." : "LLM 生成报告"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">

        {/* Report type summary */}
        <div className="flex gap-6 text-sm">
          <span className="text-muted-foreground/70">
            日报 <strong className="text-foreground/70 font-semibold">{reportTypeCounts.daily}</strong> 份
          </span>
          <span className="text-muted-foreground/50">·</span>
          <span className="text-muted-foreground/70">
            周报 <strong className="text-foreground/70 font-semibold">{reportTypeCounts.weekly}</strong> 份
          </span>
          <span className="text-muted-foreground/50">·</span>
          <span className="text-muted-foreground/70">
            月报 <strong className="text-foreground/70 font-semibold">{reportTypeCounts.monthly}</strong> 份
          </span>
        </div>

        {/* Generated report preview */}
        {genResult && (
          <Card className="border-emerald-200 bg-gradient-to-r from-emerald-50 to-white">
            <CardHeader className="pb-2 flex flex-row items-center justify-between">
              <CardTitle className="text-sm text-emerald-700">
                {REPORT_LABELS[genResult.report_type] || genResult.report_type}
                {" · "}
                {genResult.period_start?.slice(0, 10)} ~ {genResult.period_end?.slice(0, 10)}
              </CardTitle>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="text-xs"
                  onClick={() => { setSelectedReport(genResult); setViewingMd(true); }}
                >
                  查看全文
                </Button>
                <button
                  className="text-xs text-muted-foreground/50 hover:text-muted-foreground"
                  onClick={() => setGenResult(null)}
                >
                  收起
                </button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="max-h-[300px] overflow-y-auto">
                <ReportMarkdown content={genResult.summary_md?.slice(0, 2000) || ""} />
              </div>
            </CardContent>
          </Card>
        )}

        {/* Industry benchmarks */}
        {!isMobile && (
        <Card>
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <CardTitle className="text-sm">行业对标数据</CardTitle>
            <span className="text-xs text-muted-foreground/50">{benchmarks.length} 项指标</span>
          </CardHeader>
          <CardContent>
            {benchError ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                {benchError} — 请先执行 migration-003 创建 industry_benchmarks 表
              </div>
            ) : benchmarks.length === 0 ? (
              <div className="text-center py-6">
                <BarChart3 className="w-6 h-6 mx-auto mb-2 text-muted-foreground/30" />
                <p className="text-sm text-muted-foreground/70 mb-1">暂无行业基准数据</p>
                <p className="text-xs text-muted-foreground/50">执行 industry_benchmarks 种子数据后可查看行业对标</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>指标</TableHead>
                    <TableHead>分类</TableHead>
                    <TableHead className="text-right">行业均值</TableHead>
                    <TableHead className="text-right">行业TOP</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {benchmarks.map((b) => (
                    <TableRow key={b.id} className="hover:bg-muted/50">
                      <TableCell className="text-sm font-medium">{METRIC_DICT[b.metric_name]?.label ?? b.metric_name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground/70">{b.category || "—"}</TableCell>
                      <TableCell className="text-right text-sm">{formatMetricValue(b.metric_name, b.industry_avg)}</TableCell>
                      <TableCell className="text-right text-sm">
                        {formatMetricValue(b.metric_name, b.industry_top)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
        )}

        {/* Archived reports */}
        <Card>
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <CardTitle className="text-sm">历史报告</CardTitle>
            <span className="text-xs text-muted-foreground/50">{reports.length} 条记录</span>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3 py-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-10 bg-muted rounded animate-pulse" />
                ))}
              </div>
            ) : error ? (
              <div className="text-center py-8">
                <AlertTriangle className="w-6 h-6 mx-auto mb-2 text-destructive/50" />
                <p className="text-sm text-red-600 mb-1">数据加载失败</p>
                <p className="text-xs text-muted-foreground/50 mb-3">{error}</p>
                <Button size="sm" variant="outline" onClick={fetchReports}>重新加载</Button>
              </div>
            ) : reports.length === 0 ? (
              <div className="text-center py-8">
                <FileText className="w-6 h-6 mx-auto mb-2 text-muted-foreground/30" />
                <p className="text-sm text-muted-foreground/70 mb-1">暂无历史报告</p>
                <p className="text-xs text-muted-foreground/50">点击上方「LLM 生成报告」按钮生成第一份报告</p>
              </div>
            ) : isMobile ? (
              /* Mobile: compact report list */
              <div className="space-y-2 max-h-[360px] overflow-y-auto">
                {reports.slice(0, 10).map((r) => (
                  <button
                    key={r.id}
                    className="w-full text-left flex items-center gap-3 p-2 rounded-lg border hover:bg-muted/50 transition-colors"
                    onClick={() => { setSelectedReport(r); setViewingMd(true); }}
                  >
                    <Badge variant="outline" className={`text-[10px] shrink-0 ${REPORT_COLORS[r.report_type] || ""}`}>
                      {REPORT_LABELS[r.report_type] || r.report_type}
                    </Badge>
                    <span className="text-xs text-muted-foreground flex-1">
                      {r.period_start?.slice(0, 10)} ~ {r.period_end?.slice(0, 10)}
                    </span>
                    <span className="text-xs text-blue-500">查看</span>
                  </button>
                ))}
                {reports.length > 10 && (
                  <p className="text-xs text-muted-foreground/50 text-center py-1">还有 {reports.length - 10} 条报告，请在桌面端查看</p>
                )}
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[80px]">类型</TableHead>
                    <TableHead>周期</TableHead>
                    <TableHead className="w-[80px]">平台</TableHead>
                    <TableHead className="w-[100px]">生成时间</TableHead>
                    <TableHead className="text-right w-[100px]">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reports.map((r) => (
                    <TableRow key={r.id} className="hover:bg-muted/50">
                      <TableCell>
                        <Badge variant="outline" className={`text-[10px] ${REPORT_COLORS[r.report_type] || ""}`}>
                          {REPORT_LABELS[r.report_type] || r.report_type}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground/70">
                        {r.period_start?.slice(0, 10)} ~ {r.period_end?.slice(0, 10)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground/70">
                        {r.platform_id || "全局"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground/70">
                        {r.created_at ? formatDateTime(r.created_at) : "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <button
                          className="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors"
                          onClick={() => { setSelectedReport(r); setViewingMd(true); }}
                        >
                          查看报告
                        </button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Report view sheet */}
        <Sheet open={viewingMd} onOpenChange={setViewingMd}>
          <SheetContent side="right" className="w-[700px] sm:max-w-[700px] overflow-y-auto bg-muted/50">
            {selectedReport && (
              <div className="flex flex-col h-full">
                {/* Header */}
                <div className="mb-5">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground/50 mb-1">
                    {selectedReport.created_at
                      ? new Date(selectedReport.created_at).toLocaleString("zh-CN", {
                          year: "numeric", month: "2-digit", day: "2-digit",
                          hour: "2-digit", minute: "2-digit",
                        })
                      : "—"}
                  </p>
                  <h2 className="text-xl font-bold text-foreground tracking-tight">
                    {REPORT_LABELS[selectedReport.report_type] || selectedReport.report_type}
                    <span className="text-muted-foreground/20 mx-2">·</span>
                    <span className="text-muted-foreground/70 font-normal">
                      {selectedReport.period_start?.slice(0, 10)} ~ {selectedReport.period_end?.slice(0, 10)}
                    </span>
                  </h2>
                </div>

                {/* White content card */}
                <div className="flex-1 bg-white rounded-xl border border-border shadow-sm p-6">
                  <ReportMarkdown content={selectedReport.summary_md} />
                </div>
              </div>
            )}
          </SheetContent>
        </Sheet>
      </div>
    </Panel>
  );
}
