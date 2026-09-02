import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeRequest } from "@/lib/api-auth";
import { logAudit } from "@/lib/audit";
import { canWrite, loadGovernanceContext } from "@/lib/governance/roles";
import { recordQualityOverturn } from "@/lib/governance/quality-loop";

export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;
  const context = auth.user ? await loadGovernanceContext(auth.user.id) : null;
  if (auth.user && (!context || !canWrite(context.role))) {
    return NextResponse.json({ error: "Operator role required" }, { status: 403 });
  }

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => null);
    const reportId = typeof body?.report_id === "string" ? body.report_id : null;
    const correctedBy = typeof body?.corrected_by === "string" ? body.corrected_by : null;
    const reason = typeof body?.reason === "string" ? body.reason.trim() : "";
    const corrected = body?.corrected_judgment || null;

    if (!reportId || (!correctedBy && !auth.user) || !reason) {
      return NextResponse.json(
        { error: "report_id, corrected_by, and reason are required" },
        { status: 400 }
      );
    }

    const effectiveCorrectedBy = auth.user?.id || correctedBy;

    // 取原始报告
    const { data: original, error: fetchErr } = await supabaseAdmin
      .from("quality_reports")
      .select("id, status, total_score, risk_level, violations")
      .eq("id", reportId)
      .single();

    if (fetchErr || !original) {
      return NextResponse.json({ error: "Report not found" }, { status: 404 });
    }

    if (original.status !== "pending_review") {
      return NextResponse.json(
        { error: `Report already ${original.status}` },
        { status: 409 }
      );
    }

    // 事务性写入：更新报告状态 + 写入 bad_cases + 记录 human_score（用于影子模式对齐）
    const humanScore =
      corrected?.total_score != null
        ? Math.max(0, Math.min(100, corrected.total_score))
        : original.total_score;

    const { error: updateErr } = await supabaseAdmin
      .from("quality_reports")
      .update({
        status: "overturned",
        overturned_by: effectiveCorrectedBy,
        overturned_reason: reason,
        human_score: humanScore,
        ...(corrected
          ? {
              total_score: corrected.total_score ?? original.total_score,
              risk_level: corrected.risk_level ?? original.risk_level,
              violations: corrected.violations ?? original.violations,
            }
          : {}),
      })
      .eq("id", reportId)
      .eq("status", "pending_review");

    if (updateErr) {
      console.error("[QA] Overturn update failed:", updateErr.message);
      return NextResponse.json({ error: "更新报告失败" }, { status: 500 });
    }

    const { error: badCaseErr } = await supabaseAdmin.from("bad_cases").insert({
      quality_report_id: reportId,
      original_judgment: {
        score: original.total_score,
        risk_level: original.risk_level,
        violations: original.violations,
      },
      corrected_judgment: corrected || {
        score: original.total_score,
        risk_level: original.risk_level,
        violations: original.violations,
      },
      overturn_reason: reason,
      corrected_by: effectiveCorrectedBy,
    });

    if (badCaseErr) {
      console.error("[QA] Bad case insert failed:", badCaseErr.message);
      // 非致命，报告已更新
    }

    const governanceResult = await recordQualityOverturn({
      reportId,
      tenantId: context?.tenantId || "default",
      approverId: auth.user?.id || null,
      reason,
    });

    console.log(`[QA] Report ${reportId} overturned by ${correctedBy}`);
    await logAudit({
      action: "overturn",
      user_id: auth.user?.id || correctedBy,
      resource_type: "quality_report",
      resource_id: reportId,
      detail: { reason, bad_case_saved: !badCaseErr },
    });
    return NextResponse.json({
      status: "overturned",
      report_id: reportId,
      bad_case_saved: !badCaseErr,
      governance: governanceResult,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[QA] Overturn error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
