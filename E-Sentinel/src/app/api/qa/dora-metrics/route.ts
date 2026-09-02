import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

/**
 * Sprint 8: DORA Metrics API
 * 采集和展示软件交付性能指标
 * - Change Lead Time (提交到生产的时间)
 * - Deployment Frequency (部署频率)
 * - Change Fail Rate (变更失败率)
 * - Recovery Time (MTTR)
 * - Deployment Rework Rate
 */

interface DORAMetricRecord {
  recorded_at: string;
  recording_period: string;
  change_lead_time_p50_hours: number | null;
  change_lead_time_p95_hours: number | null;
  change_lead_time_avg_hours: number | null;
  deployment_count: number;
  deployment_frequency_per_day: number;
  failed_deployments: number;
  total_deployments: number;
  change_fail_rate: number;
  recovery_time_p50_minutes: number | null;
  recovery_time_p95_minutes: number | null;
  recovery_time_avg_minutes: number | null;
  rework_deployments: number;
  rework_rate: number;
}

// GET: 获取 DORA 指标
export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  const { searchParams } = new URL(request.url);
  const period = searchParams.get("period") || "weekly";
  const days = parseInt(searchParams.get("days") || "30");

  if (!supabaseAdmin) {
    return NextResponse.json(
      { error: "Database not configured" },
      { status: 503 }
    );
  }

  try {
    const startDate = new Date();
    startDate.setDate(startDate.getDate() - days);

    const { data, error } = await supabaseAdmin
      .from("dora_metrics")
      .select("*")
      .eq("tenant_id", tenantId)
      .eq("recording_period", period)
      .gte("recorded_at", startDate.toISOString())
      .order("recorded_at", { ascending: false });

    if (error) {
      console.error("[dora-metrics] DB error:", error);
      return NextResponse.json(
        { error: "Failed to query DORA metrics" },
        { status: 500 }
      );
    }

    // 无数据时返回空指标，不填充任何估算值
    if (!data || data.length === 0) {
      return NextResponse.json({
        period,
        days,
        recorded_at: new Date().toISOString(),
        ...getEmptyMetrics(),
        daily_records: [],
      });
    }

    // 计算聚合指标
    const metrics = data as DORAMetricRecord[];
    const aggregated = aggregateMetrics(metrics);

    return NextResponse.json({
      period,
      days,
      recorded_at: new Date().toISOString(),
      ...aggregated,
      daily_records: metrics.slice(0, 30),
    });
  } catch (error) {
    console.error("[dora-metrics] Error:", error);
    return NextResponse.json(
      { error: "Failed to query DORA metrics" },
      { status: 500 }
    );
  }
}

// POST: 记录 DORA 指标 (由 CI/CD 系统调用)
export async function POST(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  if (!supabaseAdmin) {
    return NextResponse.json(
      { error: "Database not configured" },
      { status: 500 }
    );
  }

  try {
    const body = await request.json();

    const record = {
      tenant_id: tenantId,
      recording_period: body.recording_period || "daily",
      change_lead_time_p50_hours: body.change_lead_time_p50_hours || null,
      change_lead_time_p95_hours: body.change_lead_time_p95_hours || null,
      change_lead_time_avg_hours: body.change_lead_time_avg_hours || null,
      deployment_count: body.deployment_count || 0,
      deployment_frequency_per_day: body.deployment_frequency_per_day || 0,
      failed_deployments: body.failed_deployments || 0,
      total_deployments: body.total_deployments || 0,
      change_fail_rate: body.change_fail_rate || 0,
      recovery_time_p50_minutes: body.recovery_time_p50_minutes || null,
      recovery_time_p95_minutes: body.recovery_time_p95_minutes || null,
      recovery_time_avg_minutes: body.recovery_time_avg_minutes || null,
      rework_deployments: body.rework_deployments || 0,
      rework_rate: body.rework_rate || 0,
      application_name: body.application_name || "qa-system",
      environment: body.environment || "production",
    };

    const { data, error } = await supabaseAdmin
      .from("dora_metrics")
      .insert(record)
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ record: data }, { status: 201 });
  } catch (error) {
    console.error("[dora-metrics] Error:", error);
    return NextResponse.json(
      { error: "Failed to record DORA metrics" },
      { status: 500 }
    );
  }
}

// 聚合多个记录
function aggregateMetrics(metrics: DORAMetricRecord[]) {
  if (metrics.length === 0) {
    return getEmptyMetrics();
  }

  const totalDeployments = metrics.reduce(
    (sum, m) => sum + (m.total_deployments || 0),
    0
  );
  const totalFailed = metrics.reduce(
    (sum, m) => sum + (m.failed_deployments || 0),
    0
  );
  const totalReworks = metrics.reduce(
    (sum, m) => sum + (m.rework_deployments || 0),
    0
  );

  const avgLeadTime =
    metrics.reduce((sum, m) => sum + (m.change_lead_time_avg_hours || 0), 0) /
    metrics.length;
  const avgRecoveryTime =
    metrics.reduce(
      (sum, m) => sum + (m.recovery_time_avg_minutes || 0),
      0
    ) / metrics.length;

  return {
    change_lead_time: {
      p50_hours: metrics[0]?.change_lead_time_p50_hours ?? null,
      p95_hours: metrics[0]?.change_lead_time_p95_hours ?? null,
      avg_hours: Math.round(avgLeadTime * 100) / 100,
      rating: getLeadTimeRating(avgLeadTime),
    },
    deployment_frequency: {
      total_deployments: totalDeployments,
      frequency_per_day:
        metrics.reduce((sum, m) => sum + (m.deployment_frequency_per_day || 0), 0) /
        metrics.length,
      rating: getFrequencyRating(totalDeployments / 30),
    },
    change_fail_rate: {
      failed_deployments: totalFailed,
      total_deployments: totalDeployments,
      rate:
        totalDeployments > 0
          ? Math.round((totalFailed / totalDeployments) * 10000) / 10000
          : 0,
      rating: getFailRateRating(
        totalDeployments > 0 ? totalFailed / totalDeployments : 0
      ),
    },
    recovery_time: {
      p50_minutes: metrics[0]?.recovery_time_p50_minutes ?? null,
      p95_minutes: metrics[0]?.recovery_time_p95_minutes ?? null,
      avg_minutes: Math.round(avgRecoveryTime * 100) / 100,
      rating: getRecoveryTimeRating(avgRecoveryTime),
    },
    rework_rate: {
      rework_deployments: totalReworks,
      total_deployments: totalDeployments,
      rate:
        totalDeployments > 0
          ? Math.round((totalReworks / totalDeployments) * 10000) / 10000
          : 0,
    },
  };
}

function getEmptyMetrics() {
  return {
    change_lead_time: {
      p50_hours: null,
      p95_hours: null,
      avg_hours: null,
      rating: "unknown" as const,
    },
    deployment_frequency: {
      total_deployments: 0,
      frequency_per_day: 0,
      rating: "unknown" as const,
    },
    change_fail_rate: {
      failed_deployments: 0,
      total_deployments: 0,
      rate: 0,
      rating: "unknown" as const,
    },
    recovery_time: {
      p50_minutes: null,
      p95_minutes: null,
      avg_minutes: null,
      rating: "unknown" as const,
    },
    rework_rate: {
      rework_deployments: 0,
      total_deployments: 0,
      rate: 0,
    },
  };
}

// DORA 等级评估函数
function getLeadTimeRating(hours: number): "elite" | "high" | "medium" | "low" | "unknown" {
  if (hours < 1) return "elite";
  if (hours < 7 * 24) return "high"; // < 1 week
  if (hours < 30 * 24) return "medium"; // < 1 month
  return "low";
}

function getFrequencyRating(perDay: number): "elite" | "high" | "medium" | "low" | "unknown" {
  if (perDay >= 1) return "elite"; // 每天多次
  if (perDay >= 1 / 7) return "high"; // 每周多次
  if (perDay >= 1 / 30) return "medium"; // 每月多次
  return "low";
}

function getFailRateRating(rate: number): "elite" | "high" | "medium" | "low" | "unknown" {
  if (rate < 0.05) return "elite"; // < 5%
  if (rate < 0.15) return "high"; // < 15%
  if (rate < 0.3) return "medium"; // < 30%
  return "low";
}

function getRecoveryTimeRating(minutes: number): "elite" | "high" | "medium" | "low" | "unknown" {
  if (minutes < 60) return "elite"; // < 1 hour
  if (minutes < 24 * 60) return "high"; // < 1 day
  if (minutes < 7 * 24 * 60) return "medium"; // < 1 week
  return "low";
}