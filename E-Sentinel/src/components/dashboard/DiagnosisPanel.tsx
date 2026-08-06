"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  FileSearch,
  Lightbulb,
  RefreshCw,
  Search,
  X,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import Panel from "@/components/dashboard/Panel";
import type {
  DiagnosisFinding,
  ReasonCategory,
  ConfidenceLevel,
  EvidenceRef,
} from "@/lib/diagnosis/engine";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REASON_LABELS: Record<ReasonCategory, string> = {
  traffic_quality: "流量质量",
  product_mismatch: "商品不匹配",
  price_objection: "价格异议",
  trust_deficit: "信任不足",
  service_failure: "客服问题",
  inventory_fulfillment: "库存/履约",
  payment_followup: "支付/跟进",
  unknown: "原因不明",
};

const CONFIDENCE_LABELS: Record<ConfidenceLevel, string> = {
  high: "高置信",
  medium: "中等",
  low: "低置信",
  insufficient: "证据不足",
};

const CONFIDENCE_CLASS: Record<ConfidenceLevel, string> = {
  high: "border-emerald-200 bg-emerald-50 text-emerald-700",
  medium: "border-amber-200 bg-amber-50 text-amber-700",
  low: "border-orange-200 bg-orange-50 text-orange-700",
  insufficient: "border-border bg-muted/50 text-muted-foreground/50",
};

const REASON_CLASS: Record<ReasonCategory, string> = {
  traffic_quality: "bg-blue-100 text-blue-700",
  product_mismatch: "bg-purple-100 text-purple-700",
  price_objection: "bg-red-100 text-red-700",
  trust_deficit: "bg-amber-100 text-amber-700",
  service_failure: "bg-orange-100 text-orange-700",
  inventory_fulfillment: "bg-teal-100 text-teal-700",
  payment_followup: "bg-indigo-100 text-indigo-700",
  unknown: "bg-muted text-muted-foreground",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DiagnosisSession {
  id: string;
  status: string;
  conversation_ids: string[];
  summary: {
    total_conversations: number;
    diagnosed_count: number;
    top_reasons: { category: ReasonCategory; count: number }[];
    roi_claimable: boolean;
    roi_disclaimer: string | null;
  } | null;
  created_at: string;
}

interface FindingWithReviews extends DiagnosisFinding {
  id?: string;
  reviews?: { id: string; decision: string; rejection_reason?: string }[];
}

// ---------------------------------------------------------------------------
// Evidence Drawer
// ---------------------------------------------------------------------------

function EvidenceDrawer({
  finding,
  onClose,
  onReview,
}: {
  finding: FindingWithReviews;
  onClose: () => void;
  onReview: (findingId: string, decision: "accepted" | "rejected") => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-[420px] max-w-full bg-background border-l border-border shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-background border-b border-border px-4 py-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold">诊断证据</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Category + Confidence */}
          <div className="flex items-center gap-2">
            <Badge className={REASON_CLASS[finding.reason_category]}>
              {REASON_LABELS[finding.reason_category]}
            </Badge>
            <Badge variant="outline" className={CONFIDENCE_CLASS[finding.confidence]}>
              {CONFIDENCE_LABELS[finding.confidence]}
              {finding.confidence_score > 0 && ` (${(finding.confidence_score * 100).toFixed(0)}%)`}
            </Badge>
          </div>

          {/* Fact */}
          <div>
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
              事实
            </div>
            <p className="text-xs leading-relaxed">{finding.fact_statement}</p>
          </div>

          {/* Inference */}
          {finding.inference_statement && (
            <div>
              <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
                推断
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground italic">
                {finding.inference_statement}
              </p>
            </div>
          )}

          {/* Counter-evidence */}
          {finding.counter_evidence && (
            <div>
              <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
                反证
              </div>
              <p className="text-xs leading-relaxed text-amber-700">{finding.counter_evidence}</p>
            </div>
          )}

          {/* Suggestion */}
          {finding.suggestion && (
            <div className="rounded-lg border border-border p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <Lightbulb className="w-3 h-3 text-amber-500" />
                <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                  建议
                </span>
                {finding.suggestion_actionable && (
                  <Badge variant="outline" className="text-[9px] px-1 py-0">可执行</Badge>
                )}
              </div>
              <p className="text-xs leading-relaxed">{finding.suggestion}</p>
            </div>
          )}

          {/* Evidence refs */}
          <div>
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">
              证据引用
            </div>
            <div className="space-y-1.5">
              {(finding.evidence_refs ?? []).map((ref: EvidenceRef, i: number) => (
                <div key={i} className="flex items-start gap-2 text-xs rounded border border-border px-2 py-1.5">
                  <FileSearch className="w-3 h-3 mt-0.5 shrink-0 text-muted-foreground" />
                  <div>
                    <span className="font-medium">{ref.label}</span>
                    {ref.excerpt && (
                      <span className="text-muted-foreground ml-1">— {ref.excerpt}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Funnel stage */}
          {finding.funnel_stage && (
            <div className="text-[10px] text-muted-foreground">
              漏斗阶段: <span className="font-medium">{finding.funnel_stage}</span>
            </div>
          )}

          {/* Review actions */}
          {finding.id && (!finding.reviews || finding.reviews.length === 0) && (
            <div className="flex gap-2 pt-2 border-t border-border">
              <Button
                size="sm"
                className="flex-1 text-xs"
                onClick={() => onReview(finding.id!, "accepted")}
              >
                <CheckCircle2 className="w-3 h-3 mr-1" />
                接受并创建任务
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="flex-1 text-xs"
                onClick={() => onReview(finding.id!, "rejected")}
              >
                <XCircle className="w-3 h-3 mr-1" />
                驳回
              </Button>
            </div>
          )}

          {/* Existing reviews */}
          {finding.reviews && finding.reviews.length > 0 && (
            <div className="text-xs text-muted-foreground border-t border-border pt-2">
              已复核: {finding.reviews[0].decision === "accepted" ? "已接受" : "已驳回"}
              {finding.reviews[0].rejection_reason && ` — ${finding.reviews[0].rejection_reason}`}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Panel
// ---------------------------------------------------------------------------

export default function DiagnosisPanel() {
  const [sessions, setSessions] = useState<DiagnosisSession[]>([]);
  const [findings, setFindings] = useState<FindingWithReviews[]>([]);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [drawerFinding, setDrawerFinding] = useState<FindingWithReviews | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/qa/diagnosis?limit=20");
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions ?? []);
      } else {
        setError("加载诊断记录失败");
      }
    } catch {
      setError("网络请求失败");
    }
    setLoading(false);
  }, []);

  const fetchSessionDetail = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/qa/diagnosis/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        setFindings(data.findings ?? []);
      }
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  useEffect(() => {
    if (selectedSession) fetchSessionDetail(selectedSession);
    else setFindings([]);
  }, [selectedSession, fetchSessionDetail]);

  const handleReview = async (findingId: string, decision: "accepted" | "rejected") => {
    if (!selectedSession) return;
    try {
      const res = await fetch(`/api/qa/diagnosis/${selectedSession}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ finding_id: findingId, decision }),
      });
      if (res.ok) {
        setDrawerFinding(null);
        fetchSessionDetail(selectedSession);
      }
    } catch {
      // silent
    }
  };

  const activeSession = sessions.find((s) => s.id === selectedSession);

  return (
    <Panel
      title="未成交诊断"
      subtitle="对流失会话生成原因假设，分层展示事实、推断、置信度与建议"
      loading={loading}
      error={error}
      onRetry={fetchSessions}
      empty={!loading && !error && sessions.length === 0}
      emptyTitle="暂无诊断记录"
      emptyDescription="通过 API 或批量任务对未成交会话发起诊断后，结果将在此展示"
    >
      <div className="space-y-4">
        {/* Session list */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {sessions.slice(0, 6).map((session) => (
            <Card
              key={session.id}
              className={`cursor-pointer transition-colors ${
                selectedSession === session.id ? "border-primary ring-1 ring-primary/20" : "hover:border-primary/40"
              }`}
              onClick={() => setSelectedSession(session.id === selectedSession ? null : session.id)}
            >
              <CardContent className="p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] text-muted-foreground font-mono">
                    {session.id.slice(0, 8)}
                  </span>
                  <Badge variant="outline" className="text-[9px]">
                    {session.status === "completed" ? "已完成" : session.status}
                  </Badge>
                </div>
                <div className="text-xs font-medium">
                  {session.conversation_ids?.length ?? 0} 条会话
                </div>
                {session.summary?.top_reasons && session.summary.top_reasons.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {session.summary.top_reasons.map((r) => (
                      <Badge key={r.category} className={`text-[9px] px-1 py-0 ${REASON_CLASS[r.category]}`}>
                        {REASON_LABELS[r.category]} ×{r.count}
                      </Badge>
                    ))}
                  </div>
                )}
                {session.summary?.roi_disclaimer && (
                  <div className="flex items-center gap-1 mt-1.5 text-[9px] text-amber-600">
                    <AlertTriangle className="w-2.5 h-2.5" />
                    {session.summary.roi_disclaimer}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Findings table */}
        {selectedSession && findings.length > 0 && (
          <Card>
            <CardHeader className="pb-2 px-4 pt-3">
              <CardTitle className="text-xs font-semibold">
                诊断发现 ({findings.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              <div className="space-y-2">
                {findings.map((finding, i) => (
                  <button
                    key={finding.id ?? i}
                    type="button"
                    onClick={() => setDrawerFinding(finding)}
                    className="w-full flex items-center gap-3 rounded-lg border border-border px-3 py-2 text-left hover:bg-muted/50 transition-colors"
                  >
                    <Badge className={`text-[9px] px-1.5 py-0 shrink-0 ${REASON_CLASS[finding.reason_category]}`}>
                      {REASON_LABELS[finding.reason_category]}
                    </Badge>
                    <span className="flex-1 text-xs truncate">{finding.fact_statement}</span>
                    <Badge variant="outline" className={`text-[9px] shrink-0 ${CONFIDENCE_CLASS[finding.confidence]}`}>
                      {CONFIDENCE_LABELS[finding.confidence]}
                    </Badge>
                    {finding.reviews && finding.reviews.length > 0 && (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500 shrink-0" />
                    )}
                    <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ROI disclaimer banner */}
        {activeSession?.summary?.roi_disclaimer && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            {activeSession.summary.roi_disclaimer}
          </div>
        )}
      </div>

      {/* Evidence drawer */}
      {drawerFinding && (
        <EvidenceDrawer
          finding={drawerFinding}
          onClose={() => setDrawerFinding(null)}
          onReview={handleReview}
        />
      )}
    </Panel>
  );
}
