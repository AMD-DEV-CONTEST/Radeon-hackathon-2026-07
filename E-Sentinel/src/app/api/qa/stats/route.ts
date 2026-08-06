import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET() {
  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
  }

  try {
    const sevenDaysAgo = new Date(Date.now() - 7 * 86400000).toISOString();

    // Total count — using exact same pattern as overview endpoint
    const { data: allReports, error: allErr } = await supabaseAdmin
      .from("quality_reports")
      .select("risk_level, total_score, status, violations, created_at")
      .gte("created_at", sevenDaysAgo)
      .order("created_at", { ascending: false });

    if (allErr) {
      return NextResponse.json({ error: allErr.message }, { status: 500 });
    }

    const reports = (allReports || []) as Array<{
      violations?: Array<{ category?: string }>;
      risk_level?: string;
      total_score?: number;
      status?: string;
      created_at?: string;
    }>;

    // Total count from separate query
    const { count: total } = await supabaseAdmin
      .from("quality_reports")
      .select("*", { count: "exact", head: true });

    // Today count
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const todayIso = todayStart.toISOString();
    const todayCount = reports.filter((r) => r.created_at && r.created_at >= todayIso).length;

    // Aggregate
    const categoryCount: Record<string, number> = {};
    let totalScoreSum = 0;
    let scoreCount = 0;
    let pendingReview = 0;
    let criticalCount = 0;
    let highCount = 0;

    for (const r of reports) {
      let violations: Array<{ category?: string }> = [];
      try {
        const raw: unknown = r.violations;
        if (Array.isArray(raw)) {
          violations = raw as Array<{ category?: string }>;
        } else if (typeof raw === "string" && (raw as string).length > 0) {
          const parsed = JSON.parse(raw as string);
          if (Array.isArray(parsed)) violations = parsed;
        }
      } catch { /* keep empty */ }
      for (const v of violations) {
        const cat = v.category || "其他";
        categoryCount[cat] = (categoryCount[cat] || 0) + 1;
      }
      totalScoreSum += r.total_score || 0;
      scoreCount++;
      if (r.risk_level === "critical") criticalCount++;
      if (r.risk_level === "high") highCount++;
      if (r.status === "pending_review") pendingReview++;
    }

    const avgScore = scoreCount > 0 ? Math.round(totalScoreSum / scoreCount) : 100;

    // Most recent report timestamp for "data as of" display
    const dataRefreshedAt = reports.length > 0 ? reports[0].created_at || null : null;

    // Previous period high-risk count for change comparison (8-14 days ago)
    const prevStart = new Date(Date.now() - 14 * 86400000).toISOString();
    const prevEnd = new Date(Date.now() - 7 * 86400000).toISOString();
    const { data: prevReports } = await supabaseAdmin
      .from("quality_reports")
      .select("risk_level")
      .gte("created_at", prevStart)
      .lt("created_at", prevEnd);
    const previousHighCount = (prevReports || []).filter(
      (r: any) => r.risk_level === "critical" || r.risk_level === "high"
    ).length;

    return NextResponse.json({
      total: total ?? reports.length,
      todayCount,
      avgScore,
      pendingReview,
      criticalCount,
      highCount,
      previousHighCount,
      dataRefreshedAt,
      violationsByCategory: Object.entries(categoryCount).map(([name, value]) => ({ name, value })),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
