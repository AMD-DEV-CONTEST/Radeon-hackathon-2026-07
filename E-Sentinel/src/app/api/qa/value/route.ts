import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

function parseViolations(raw: unknown): Array<{ category?: string }> {
  if (Array.isArray(raw)) return raw as Array<{ category?: string }>;
  if (typeof raw === "string" && raw.length > 0) {
    try { const p = JSON.parse(raw); if (Array.isArray(p)) return p; } catch { /* empty */ }
  }
  return [];
}

const AI_COST_PER_CALL = 0.004; // Moonshot ~$0.004 per evaluation
const MANUAL_COST_PER_MIN = 0.5; // 人工时薪 ~30元/时 = 0.5元/分
const MANUAL_MINUTES_PER_REVIEW = 5; // 人工质检单条耗时 ~5分钟
const AVG_PLATFORM_FINE = 2000; // 平台平均罚款金额（广告法/客诉升级）
const HIGH_RISK_FINE_MULTIPLIER = 1.5; // critical 对应更高潜在罚款

export async function GET() {
  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
  }

  // Run all 4 queries in parallel
  const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString();
  const fourteenDaysAgo = new Date(Date.now() - 14 * 86400000).toISOString();

  const [totalResult, recentData, trendData, agentData] = await Promise.all([
    // Query 1: Total count
    supabaseAdmin.from("quality_reports").select("id", { count: "exact", head: true }),

    // Query 2: All recent reports (consolidated: risk_level, status, review_mode, violations, created_at)
    supabaseAdmin
      .from("quality_reports")
      .select("risk_level, status, review_mode, violations, created_at, agent_id, total_score")
      .gte("created_at", thirtyDaysAgo)
      .order("created_at", { ascending: false }),

    // Query 3: Trend data (last 14 days, ascending)
    supabaseAdmin
      .from("quality_reports")
      .select("violations, created_at")
      .gte("created_at", fourteenDaysAgo)
      .order("created_at", { ascending: true }),

    // Query 4: Agent summary
    supabaseAdmin
      .from("quality_reports")
      .select("agent_id, total_score, risk_level, violations")
      .gte("created_at", thirtyDaysAgo),
  ]);

  const total = totalResult.count || 0;
  const recent = recentData.data || [];
  const trendRows = trendData.data || [];
  const agentRows = agentData.data || [];

  const monthlyTotal = recent.length;
  const criticalCount = recent.filter(r => r.risk_level === "critical").length;
  const highCount = recent.filter(r => r.risk_level === "high").length;
  const activeCount = recent.filter(r => r.review_mode === "active" || !r.review_mode).length;

  // Cost calculations
  const aiCost = monthlyTotal * AI_COST_PER_CALL;
  const manualCost = monthlyTotal * MANUAL_COST_PER_MIN * MANUAL_MINUTES_PER_REVIEW;
  const costSavings = manualCost - aiCost;
  const savingsRate = manualCost > 0 ? costSavings / manualCost : 0;

  // Risk avoidance
  const criticalBlocked = criticalCount;
  const highRiskBlocked = highCount;
  const estimatedFinesAvoided =
    criticalBlocked * AVG_PLATFORM_FINE * HIGH_RISK_FINE_MULTIPLIER +
    highRiskBlocked * AVG_PLATFORM_FINE;

  // Efficiency metrics
  const aiHoursSaved = monthlyTotal * (MANUAL_MINUTES_PER_REVIEW / 60) - (monthlyTotal * 0.1 / 60);

  // Violation category breakdown (from already-fetched recent data)
  const categoryCount: Record<string, number> = {};
  let totalViolations = 0;
  recent.forEach(r => {
    const violations = parseViolations(r.violations);
    violations.forEach((v: any) => {
      const cat = v.category || "其他";
      categoryCount[cat] = (categoryCount[cat] || 0) + 1;
      totalViolations++;
    });
  });

  // Root cause: top violation categories
  const topViolations = Object.entries(categoryCount)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5)
    .map(([name, value]) => ({
      name,
      value,
      percentage: totalViolations > 0 ? Math.round((value / totalViolations) * 100) : 0,
    }));

  // Trend: daily violation count for last 14 days
  const dailyMap: Record<string, number> = {};
  trendRows.forEach(r => {
    const day = (r.created_at || "").slice(0, 10);
    dailyMap[day] = (dailyMap[day] || 0) + parseViolations(r.violations).length;
  });

  const trend = Object.entries(dailyMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, count]) => ({ date, count }));

  // Agent summary (from already-fetched agent data)
  const agentMap: Record<string, { count: number; totalScore: number; violations: number; critical: number }> = {};
  (agentRows || []).forEach((r: any) => {
    const id = r.agent_id || "unknown";
    if (!agentMap[id]) {
      agentMap[id] = { count: 0, totalScore: 0, violations: 0, critical: 0 };
    }
    agentMap[id].count++;
    agentMap[id].totalScore += r.total_score || 0;
    agentMap[id].violations += parseViolations(r.violations).length;
    if (r.risk_level === "critical") agentMap[id].critical++;
  });

  // Get agent names separately (this query is lightweight)
  const agentIds = Object.keys(agentMap).filter(id => id !== "unknown");
  const { data: profiles } = agentIds.length > 0
    ? await supabaseAdmin.from("profiles").select("id, name").in("id", agentIds)
    : { data: [] };

  const profileMap: Record<string, string> = {};
  (profiles || []).forEach((p: any) => { profileMap[p.id] = p.name || "未知客服"; });

  const agents = Object.entries(agentMap)
    .map(([id, data]) => ({
      id,
      name: profileMap[id] || "未知客服",
      reviewCount: data.count,
      avgScore: data.count > 0 ? Math.round(data.totalScore / data.count) : 0,
      totalViolations: data.violations,
      criticalCount: data.critical,
      violationRate: data.count > 0 ? (data.violations / data.count).toFixed(1) : "0.0",
    }))
    .sort((a, b) => b.totalViolations - a.totalViolations);

  return NextResponse.json({
    summary: {
      total: total || 0,
      monthlyTotal,
      activeCount,
      totalViolations,
    },
    cost: {
      aiCost: Math.round(aiCost * 100) / 100,
      manualEquivalentCost: Math.round(manualCost * 100) / 100,
      monthlySavings: Math.round(costSavings * 100) / 100,
      savingsRate,
      aiHoursSaved: Math.round(aiHoursSaved * 10) / 10,
    },
    riskAvoidance: {
      criticalBlocked,
      highRiskBlocked,
      estimatedFinesAvoided: Math.round(estimatedFinesAvoided),
      platformFineBaseline: AVG_PLATFORM_FINE,
    },
    rootCause: topViolations,
    trend,
    agents,
  });
}
