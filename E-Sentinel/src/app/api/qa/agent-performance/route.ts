import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

// GET /api/qa/agent-performance — agent performance reports
export async function GET(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const days = parseInt(searchParams.get("days") || "30");
    const agentId = searchParams.get("agent_id");
    const teamId = searchParams.get("team_id");

    const cutoff = new Date(Date.now() - Math.min(days, 90) * 86400000).toISOString();

    // Get agents to evaluate
    let agentFilter = supabaseAdmin
      .from("profiles")
      .select("id, name, team_id");

    if (agentId) agentFilter = agentFilter.eq("id", agentId);
    else if (teamId) agentFilter = agentFilter.eq("team_id", teamId);
    else agentFilter = agentFilter.eq("role", "agent");

    const { data: agents } = await agentFilter;
    if (!agents || agents.length === 0) {
      return NextResponse.json({ agents: [] });
    }

    const results = [];
    for (const agent of agents as Array<Record<string, unknown>>) {
      // Quality reports for this agent in the period
      const { data: reports } = await supabaseAdmin
        .from("quality_reports")
        .select("id, total_score, risk_level, sentiment_score, violations, created_at")
        .eq("agent_id", agent.id)
        .gte("created_at", cutoff)
        .order("created_at", { ascending: false });

      const agentReports = (reports || []) as Array<Record<string, unknown>>;
      const totalReports = agentReports.length;
      if (totalReports === 0) {
        results.push({
          id: agent.id,
          name: agent.name,
          team_id: agent.team_id,
          total_reports: 0,
          avg_score: null,
          min_score: null,
          max_score: null,
          critical_count: 0,
          high_count: 0,
          medium_count: 0,
          low_count: 0,
          total_violations: 0,
          avg_response_time_ms: null,
          trend: "no_data",
        });
        continue;
      }

      const scores = agentReports.map((r) => Number(r.total_score) || 0);
      const avgScore = scores.reduce((a, b) => a + b, 0) / scores.length;
      const minScore = Math.min(...scores);
      const maxScore = Math.max(...scores);

      const criticalCount = agentReports.filter((r) => r.risk_level === "critical").length;
      const highCount = agentReports.filter((r) => r.risk_level === "high").length;
      const mediumCount = agentReports.filter((r) => r.risk_level === "medium").length;
      const lowCount = agentReports.filter((r) => r.risk_level === "low").length;

      const totalViolations = agentReports.reduce((sum, r) => {
        const v = r.violations;
        return sum + (Array.isArray(v) ? v.length : 0);
      }, 0);

      // Trend: compare first half vs second half
      const mid = Math.floor(agentReports.length / 2);
      const firstHalf = agentReports.slice(0, mid);
      const secondHalf = agentReports.slice(mid);
      const firstAvg = firstHalf.length > 0
        ? firstHalf.reduce((a, r) => a + (Number(r.total_score) || 0), 0) / firstHalf.length
        : null;
      const secondAvg = secondHalf.length > 0
        ? secondHalf.reduce((a, r) => a + (Number(r.total_score) || 0), 0) / secondHalf.length
        : null;
      const trend = firstAvg !== null && secondAvg !== null
        ? secondAvg > firstAvg ? "improving" : secondAvg < firstAvg ? "declining" : "stable"
        : "insufficient_data";

      // Category breakdown
      const categoryCounts: Record<string, number> = {};
      for (const r of agentReports) {
        const violations = Array.isArray(r.violations) ? r.violations : [];
        for (const v of violations as Array<{ category?: string }>) {
          const cat = v.category || "其他";
          categoryCounts[cat] = (categoryCounts[cat] || 0) + 1;
        }
      }

      results.push({
        id: agent.id,
        name: agent.name,
        team_id: agent.team_id,
        total_reports: totalReports,
        avg_score: Math.round(avgScore * 10) / 10,
        min_score: minScore,
        max_score: maxScore,
        critical_count: criticalCount,
        high_count: highCount,
        medium_count: mediumCount,
        low_count: lowCount,
        total_violations: totalViolations,
        trend,
        category_breakdown: categoryCounts,
      });
    }

    // Sort by avg_score descending (nulls last)
    results.sort((a, b) => {
      if (a.avg_score === null && b.avg_score === null) return 0;
      if (a.avg_score === null) return 1;
      if (b.avg_score === null) return -1;
      return b.avg_score - a.avg_score;
    });

    // Summary stats
    const scoredAgents = results.filter((r) => r.avg_score !== null);
    const overallAvg = scoredAgents.length > 0
      ? scoredAgents.reduce((a, r) => a + (r.avg_score || 0), 0) / scoredAgents.length
      : null;
    const overallCritical = results.reduce((a, r) => a + r.critical_count, 0);
    const overallViolations = results.reduce((a, r) => a + r.total_violations, 0);

    return NextResponse.json({
      period: `${days}d`,
      total_agents: results.length,
      evaluated_agents: scoredAgents.length,
      overall_avg_score: overallAvg !== null ? Math.round(overallAvg * 10) / 10 : null,
      overall_critical_count: overallCritical,
      overall_violations: overallViolations,
      agents: results,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
