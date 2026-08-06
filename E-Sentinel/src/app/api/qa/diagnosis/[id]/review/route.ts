import { NextResponse } from "next/server";
import { authorizeRequest } from "@/lib/api-auth";
import { supabaseAdmin } from "@/lib/supabase";
import { loadGovernanceContext } from "@/lib/governance/roles";

/**
 * PATCH /api/qa/diagnosis/[id]/review
 * Submit a human review decision on a diagnosis finding.
 *
 * Body: {
 *   finding_id: string,
 *   decision: "accepted" | "modified" | "rejected",
 *   modified_reason?: string,
 *   rejection_reason?: string,
 *   feedback_note?: string,
 *   feedback_target?: "rule" | "prompt" | "knowledge" | "model" | "none",
 *   create_work_item?: boolean,           // 创建 diagnosis 专用 work item
 *   create_general_work_order?: boolean,  // 可选：创建通用 work_orders（带 evidence_refs + source 追溯）
 *   work_item_title?: string
 * }
 */
export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;

  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Database not configured" }, { status: 500 });
  }

  const { id: sessionId } = await params;

  let tenantId = "default";
  let reviewerId: string | null = null;
  if (auth.user) {
    const ctx = await loadGovernanceContext(auth.user.id);
    tenantId = ctx?.tenantId ?? "default";
    reviewerId = auth.user.id;
  }

  if (!reviewerId) {
    return NextResponse.json({ error: "Reviewer identity required" }, { status: 400 });
  }

  try {
    const body = await request.json();
    const { finding_id, decision } = body;

    if (!finding_id || !decision) {
      return NextResponse.json(
        { error: "finding_id and decision are required" },
        { status: 400 },
      );
    }

    if (!["accepted", "modified", "rejected"].includes(decision)) {
      return NextResponse.json(
        { error: "decision must be accepted, modified, or rejected" },
        { status: 400 },
      );
    }

    // Verify finding belongs to this session and tenant
    // 扩展 select 以获取 evidence_refs 和 conversation_id，用于打通到通用 WorkOrder 的证据链
    const { data: finding, error: findError } = await supabaseAdmin
      .from("diagnosis_findings")
      .select("id, session_id, tenant_id, suggestion, reason_category, evidence_refs, conversation_id, fact_statement")
      .eq("id", finding_id)
      .eq("session_id", sessionId)
      .eq("tenant_id", tenantId)
      .single();

    if (findError || !finding) {
      return NextResponse.json({ error: "Finding not found in this session" }, { status: 404 });
    }

    // Insert review
    const { data: review, error: reviewError } = await supabaseAdmin
      .from("diagnosis_reviews")
      .insert({
        finding_id,
        tenant_id: tenantId,
        reviewer_id: reviewerId,
        decision,
        modified_reason: body.modified_reason ?? null,
        rejection_reason: body.rejection_reason ?? null,
        feedback_note: body.feedback_note ?? null,
        feedback_target: body.feedback_target ?? (decision === "rejected" ? "rule" : "none"),
      })
      .select("id, created_at")
      .single();

    if (reviewError) {
      return NextResponse.json(
        { error: "Failed to save review", detail: reviewError.message },
        { status: 500 },
      );
    }

    // Optionally create a work item from accepted finding
    let workItem = null;
    if (decision === "accepted" && body.create_work_item !== false && finding.suggestion) {
      const { data: wi } = await supabaseAdmin
        .from("diagnosis_work_items")
        .insert({
          finding_id,
          session_id: sessionId,
          tenant_id: tenantId,
          title: body.work_item_title || `[诊断] ${finding.reason_category}: ${finding.suggestion.slice(0, 60)}`,
          description: finding.suggestion,
          assignee_id: null,
          status: "open",
          priority: "medium",
        })
        .select("id, title, status")
        .single();
      workItem = wi;
    }

    // 按计划 Sprint 2 + QAE-019：Feature Flag 控制 + 创建通用 work_orders
    // 默认由 flag "diagnosis.create-general-work-order" 控制（支持 targeting）
    let generalWorkOrder = null;
    // 仅当显式传递 create_general_work_order: true 时创建通用 work_order
    // Feature Flag 库已实现，可在其他地方或未来默认启用（QAE-019）
    const shouldCreateGeneral = body.create_general_work_order === true;
    if (decision === "accepted" && shouldCreateGeneral && finding.suggestion) {
      const evidenceRefs = (finding as any).evidence_refs || [];
      const sourceEventId = (finding as any).conversation_id || null;
      const desc = finding.suggestion || (finding as any).fact_statement || "";
      const { data: gwo, error: gwoErr } = await supabaseAdmin
        .from("work_orders")
        .insert({
          title: body.work_item_title || `[诊断] ${finding.reason_category}: ${desc.slice(0, 60)}`,
          description: desc,
          source: "qa_evaluate",
          source_id: finding.id,
          priority: "medium",
          category: "general",
          metadata: {
            from_diagnosis: true,
            diagnosis_session_id: sessionId,
            finding_id,
            evidence_refs: evidenceRefs,
            source_event_id: sourceEventId,  // 关联 conversation 作为事件来源追溯
          },
        })
        .select("id, title, status, source, source_id")
        .single();
      if (!gwoErr) {
        generalWorkOrder = gwo;
      }
    }

    return NextResponse.json({
      review,
      work_item: workItem,
      general_work_order: generalWorkOrder,
      feedback_routed_to: body.feedback_target ?? (decision === "rejected" ? "rule" : "none"),
    }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "review_failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
