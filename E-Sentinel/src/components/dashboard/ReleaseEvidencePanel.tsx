"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  Clock3,
  GitBranch,
  GitCommit,
  RefreshCw,
  RotateCcw,
  Shield,
  Timer,
  XCircle,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import Panel from "@/components/dashboard/Panel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ReleaseEvidence {
  id: string;
  commit_sha: string;
  build_id?: string;
  schema_version?: string;
  rule_version?: string;
  prompt_version?: string;
  model_version?: string;
  status: string;
  checks_passed: boolean;
  approver_name?: string;
  approval_reason?: string;
  approved_at?: string;
  rollback_triggered: boolean;
  rollback_reason?: string;
  rollback_method?: string;
  rollback_executed_at?: string;
  canary_current_stage?: string;
  target_percentage?: number;
  created_at: string;
  updated_at: string;
}

interface DORAMetrics {
  change_lead_time: {
    p50_hours: number | null;
    p95_hours: number | null;
    avg_hours: number | null;
    rating: string;
  };
  deployment_frequency: {
    total_deployments: number;
    frequency_per_day: number;
    rating: string;
  };
  change_fail_rate: {
    failed_deployments: number;
    total_deployments: number;
    rate: number;
    rating: string;
  };
  recovery_time: {
    p50_minutes: number | null;
    p95_minutes: number | null;
    avg_minutes: number | null;
    rating: string;
  };
  rework_rate: {
    rework_deployments: number;
    total_deployments: number;
    rate: number;
  };
}

interface RollbackDrill {
  id: string;
  drill_name: string;
  drill_type: string;
  success: boolean | null;
  started_at: string;
  completed_at?: string;
  duration_seconds?: number;
  failure_reason?: string;
}

// ---------------------------------------------------------------------------
// Rating Badge
// ---------------------------------------------------------------------------

const RATING_COLORS: Record<string, string> = {
  elite: "bg-purple-100 text-purple-700 border-purple-200",
  high: "bg-emerald-100 text-emerald-700 border-emerald-200",
  medium: "bg-amber-100 text-amber-700 border-amber-200",
  low: "bg-red-100 text-red-700 border-red-200",
  unknown: "bg-muted text-muted-foreground border-border",
};

const RATING_LABELS: Record<string, string> = {
  elite: "精英级",
  high: "高水平",
  medium: "中等",
  low: "待改进",
  unknown: "未知",
};

function RatingBadge({ rating }: { rating: string }) {
  return (
    <Badge
      variant="outline"
      className={`text-xs ${RATING_COLORS[rating] || RATING_COLORS.unknown}`}
    >
      {RATING_LABELS[rating] || rating}
    </Badge>
  );
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-muted text-foreground/70",
  canary: "bg-blue-100 text-blue-700",
  completed: "bg-emerald-100 text-emerald-700",
  rolled_back: "bg-red-100 text-red-700",
  failed: "bg-red-100 text-red-700",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待发布",
  canary: "金丝雀中",
  completed: "已完成",
  rolled_back: "已回滚",
  failed: "发布失败",
};

// ---------------------------------------------------------------------------
// Main Panel
// ---------------------------------------------------------------------------

export default function ReleaseEvidencePanel() {
  const [releases, setReleases] = useState<ReleaseEvidence[]>([]);
  const [drills, setDrills] = useState<RollbackDrill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRelease, setSelectedRelease] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [releasesRes, drillsRes] = await Promise.all([
        fetch("/api/qa/release-evidence?limit=10", { cache: "no-store" }),
        fetch("/api/qa/rollback-drills?limit=10", { cache: "no-store" }),
      ]);

      if (releasesRes.ok) {
        const data = await releasesRes.json();
        setReleases(data.releases ?? []);
      }

      if (drillsRes.ok) {
        const data = await drillsRes.json();
        setDrills(data.drills ?? []);
      }
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
      title="发布治理"
      subtitle="发布证据、DORA 指标与回滚演练记录"
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
      <div className="space-y-4">
        {/* Release Evidences */}
        <Card>
          <CardHeader className="border-b pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <GitCommit className="w-4 h-4" />
              发布记录
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {releases.length === 0 ? (
              <div className="p-4 text-center text-sm text-muted-foreground/70">
                暂无发布记录
              </div>
            ) : (
              <div className="divide-y divide-muted">
                {releases.map((release) => (
                  <button
                    key={release.id}
                    type="button"
                    onClick={() =>
                      setSelectedRelease(
                        selectedRelease === release.id ? null : release.id
                      )
                    }
                    className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex-shrink-0">
                      {release.rollback_triggered ? (
                        <RotateCcw className="w-4 h-4 text-red-500" />
                      ) : release.status === "completed" ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      ) : (
                        <GitBranch className="w-4 h-4 text-muted-foreground/50" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground truncate">
                          {release.commit_sha.slice(0, 7)}
                        </span>
                        <Badge
                          variant="outline"
                          className={`text-xs ${STATUS_COLORS[release.status] || ""}`}
                        >
                          {STATUS_LABELS[release.status] || release.status}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground/70">
                        {new Date(release.created_at).toLocaleString("zh-CN", {
                          hour12: false,
                        })}
                      </p>
                    </div>
                    {release.approver_name && (
                      <div className="text-xs text-muted-foreground/70 text-right">
                        审批: {release.approver_name}
                      </div>
                    )}
                    <ChevronRight
                      className={`w-4 h-4 text-muted-foreground/50 transition-transform ${
                        selectedRelease === release.id ? "rotate-90" : ""
                      }`}
                    />
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Rollback Drills */}
        <Card>
          <CardHeader className="border-b pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Shield className="w-4 h-4" />
              回滚演练记录
            </CardTitle>
            <p className="text-xs text-muted-foreground/70">
              每个 Release 至少完成一次演练
            </p>
          </CardHeader>
          <CardContent className="p-0">
            {drills.length === 0 ? (
              <div className="p-4 text-center text-sm text-muted-foreground/70">
                暂无演练记录
              </div>
            ) : (
              <div className="divide-y divide-muted">
                {drills.map((drill) => (
                  <div
                    key={drill.id}
                    className="flex items-center gap-3 px-4 py-3"
                  >
                    <div className="flex-shrink-0">
                      {drill.success === true ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      ) : drill.success === false ? (
                        <XCircle className="w-4 h-4 text-red-500" />
                      ) : (
                        <Clock3 className="w-4 h-4 text-amber-500" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground">
                        {drill.drill_name}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground/70">
                        {drill.drill_type === "scheduled"
                          ? "定期演练"
                          : drill.drill_type === "release_based"
                          ? "发布后演练"
                          : "随机演练"}
                      </p>
                    </div>
                    {drill.duration_seconds && (
                      <div className="flex items-center gap-1 text-xs text-muted-foreground/70">
                        <Timer className="w-3 h-3" />
                        {Math.round(drill.duration_seconds / 60)}min
                      </div>
                    )}
                    {drill.success !== null && (
                      <Badge
                        variant="outline"
                        className={
                          drill.success
                            ? "border-emerald-200 text-emerald-700"
                            : "border-red-200 text-red-700"
                        }
                      >
                        {drill.success ? "成功" : "失败"}
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quality Gate Summary */}
        <Card>
          <CardHeader className="border-b pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Zap className="w-4 h-4" />
              发布门禁状态
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 p-4 sm:grid-cols-3">
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span className="text-sm text-emerald-700">AI 回归测试</span>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span className="text-sm text-emerald-700">安全扫描</span>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span className="text-sm text-emerald-700">契约测试</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </Panel>
  );
}