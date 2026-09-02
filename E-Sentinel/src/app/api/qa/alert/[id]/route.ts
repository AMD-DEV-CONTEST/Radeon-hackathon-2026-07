import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { dispatchAlert } from "@/lib/feishu";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;

    const { data: report, error: fetchErr } = await supabaseAdmin
      .from("quality_reports")
      .select("*")
      .eq("id", id)
      .single();

    if (fetchErr || !report) {
      return NextResponse.json({ error: "Report not found" }, { status: 404 });
    }

    if (report.review_mode === "shadow") {
      return NextResponse.json(
        { error: "影子模式报告不发送飞书预警，请先将 review_mode 改为 active" },
        { status: 400 }
      );
    }

    if (report.risk_level !== "high" && report.risk_level !== "critical") {
      return NextResponse.json(
        { error: `当前风险等级为 ${report.risk_level}，仅 high/critical 触发派发` },
        { status: 400 }
      );
    }

    // Resolve target profile — from explicit target_profile_id, or fall back to agent's team_lead
    let agentName = "未知客服";
    let reviewerOpenId: string | null = null;
    const reviewerWebhook: string | null = null;
    let targetName: string | null = null;

    const body = await request.json().catch(() => ({}));
    const targetProfileId = body.target_profile_id as string | undefined;

    if (targetProfileId) {
      const { data: targetProfile } = await supabaseAdmin
        .from("profiles")
        .select("name, feishu_open_id")
        .eq("id", targetProfileId)
        .maybeSingle();
      if (targetProfile) {
        targetName = targetProfile.name || null;
        reviewerOpenId = targetProfile.feishu_open_id || null;
      }
    }

    // Fallback to agent's team_lead if no explicit target or target not found
    if (!reviewerOpenId && !reviewerWebhook && report.agent_id) {
      const { data: profile } = await supabaseAdmin
        .from("profiles")
        .select("name, feishu_open_id")
        .eq("id", report.agent_id)
        .maybeSingle();
      if (profile) {
        agentName = profile.name || "未知客服";
        reviewerOpenId = profile.feishu_open_id || null;
      }
    }

    if (targetName) agentName = targetName;

    const result = await dispatchAlert(
      {
        reportId: report.id,
        ticketId: report.ticket_id,
        agentName,
        totalScore: report.total_score,
        riskLevel: report.risk_level,
        sentimentScore: report.sentiment_score,
        violations: Array.isArray(report.violations) ? report.violations : (typeof report.violations === "string" ? JSON.parse(report.violations) : []),
        correlationId: report.correlation_id,
      },
      reviewerOpenId,
      reviewerWebhook
    );

    console.log(`[QA] Alert re-dispatched for ${report.id}: ${result.method}`);

    return NextResponse.json({
      report_id: report.id,
      alert_method: result.method,
      target: result.target,
      success: result.method !== "none",
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[QA] Alert error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
