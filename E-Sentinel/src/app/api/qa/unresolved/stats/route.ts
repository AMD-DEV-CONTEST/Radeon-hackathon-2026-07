// ============================================================================
// Unresolved Questions Stats API
// 统计趋势、分类分布、处理时效
// ============================================================================

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const daysBack = Math.min(parseInt(searchParams.get("days") || "7"), 30);

    // 1. 趋势数据（按租户读取，避免无租户 RPC 汇总跨租户数据）
    const startDate = new Date();
    startDate.setDate(startDate.getDate() - (daysBack - 1));
    const { data: trendRows } = await supabaseAdmin
      .from("unresolved_questions")
      .select("created_at, status")
      .eq("tenant_id", tenantId)
      .gte("created_at", startDate.toISOString());
    const trend = buildTrend(trendRows || [], daysBack);

    // 2. 状态分布
    const { data: allRows } = await supabaseAdmin
      .from("unresolved_questions")
      .select("status")
      .eq("tenant_id", tenantId);

    const statusCounts: Record<string, number> = { pending: 0, processing: 0, resolved: 0, rejected: 0, exported: 0 };
    const rows = (allRows || []) as Array<Record<string, string>>;
    for (const row of rows) {
      const s = row.status || "pending";
      statusCounts[s] = (statusCounts[s] || 0) + 1;
    }

    // 3. 分类分布
    const { data: catDist } = await supabaseAdmin
      .from("unresolved_questions")
      .select("category")
      .eq("tenant_id", tenantId)
      .not("category", "is", null);

    const categoryCounts: Record<string, number> = {};
    for (const row of (catDist || []) as Array<Record<string, string>>) {
      const cat = row.category || "uncategorized";
      categoryCounts[cat] = (categoryCounts[cat] || 0) + 1;
    }

    // 4. 平台分布
    const { data: platDist } = await supabaseAdmin
      .from("unresolved_questions")
      .select("platform_code")
      .eq("tenant_id", tenantId);

    const platformCounts: Record<string, number> = {};
    for (const row of (platDist || []) as Array<Record<string, string>>) {
      const pc = row.platform_code || "unknown";
      platformCounts[pc] = (platformCounts[pc] || 0) + 1;
    }

    // 5. 平均解决时间
    const { data: resolvedRows } = await supabaseAdmin
      .from("unresolved_questions")
      .select("created_at, resolved_at")
      .eq("tenant_id", tenantId)
      .eq("status", "resolved")
      .not("resolved_at", "is", null);

    let avgResolutionHours = 0;
    if (resolvedRows && resolvedRows.length > 0) {
      const totalHours = (resolvedRows as Array<Record<string, string>>)
        .map((r) => (new Date(r.resolved_at).getTime() - new Date(r.created_at).getTime()) / 3600000)
        .reduce((sum, h) => sum + h, 0);
      avgResolutionHours = Math.round((totalHours / resolvedRows.length) * 10) / 10;
    }

    return NextResponse.json({
      trend: trend || [],
      status_distribution: statusCounts,
      category_distribution: categoryCounts,
      platform_distribution: platformCounts,
      avg_resolution_hours: avgResolutionHours,
      total: (allRows || []).length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Unresolved Stats] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function buildTrend(rows: Array<Record<string, unknown>>, daysBack: number) {
  const dates = Array.from({ length: daysBack }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (daysBack - 1 - index));
    return date.toISOString().slice(0, 10);
  });
  return dates.map((date) => {
    const dayRows = rows.filter((row) => String(row.created_at || "").slice(0, 10) === date);
    return {
      date_str: date,
      total_count: dayRows.length,
      pending_count: dayRows.filter((row) => row.status === "pending").length,
      resolved_count: dayRows.filter((row) => row.status === "resolved").length,
      exported_count: dayRows.filter((row) => row.status === "exported").length,
    };
  });
}
