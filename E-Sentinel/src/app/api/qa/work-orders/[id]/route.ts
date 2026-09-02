import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";

// GET /api/qa/work-orders/[id] — single work order detail
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;
    const { data, error } = await supabaseAdmin
      .from("work_orders")
      .select("*, actions:work_order_actions(*)")
      .eq("id", id)
      .single();

    if (error || !data) {
      return NextResponse.json({ error: "Work order not found" }, { status: 404 });
    }

    return NextResponse.json({ work_order: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// PUT /api/qa/work-orders/[id] — update status or assign
export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;
    const body = await request.json();
    const correlationId = createCorrelationId("wo");

    const { data: existing, error: fetchErr } = await supabaseAdmin
      .from("work_orders")
      .select("id, status, title")
      .eq("id", id)
      .single();

    if (fetchErr || !existing) {
      return NextResponse.json({ error: "Work order not found" }, { status: 404 });
    }

    const updates: Record<string, unknown> = {};
    if (body.status) updates.status = body.status;
    if (body.priority) updates.priority = body.priority;
    if (body.assigned_to !== undefined) updates.assigned_to = body.assigned_to;
    if (body.resolution) updates.resolution = body.resolution;
    if (body.category) updates.category = body.category;
    if (body.source_id !== undefined) updates.source_id = body.source_id; // 支持关联 EvidenceEvent / Finding

    // Set timestamps based on status transition
    if (body.status === "resolved" || body.status === "closed") {
      updates.resolved_at = new Date().toISOString();
      updates.resolved_by = body.resolved_by || null;
    }
    if (body.status === "closed") {
      updates.closed_at = new Date().toISOString();
    }

    // Sprint 2 闭环要求：关闭 WorkItem 必须提供证据或豁免理由（可回溯来源）
    if (body.status === "closed") {
      const hasEvidence = !!(body.resolution || body.closure_evidence || body.exemption_reason);
      if (!hasEvidence) {
        return NextResponse.json(
          { error: "关闭工单必须提供 resolution、closure_evidence 或 exemption_reason 作为证据或豁免理由", code: "CLOSURE_EVIDENCE_REQUIRED" },
          { status: 400 }
        );
      }
      // 优先将证据存入 resolution，便于查询
      if (!updates.resolution) {
        updates.resolution = body.closure_evidence || body.exemption_reason;
      }
    }

    const { data, error } = await supabaseAdmin
      .from("work_orders")
      .update(updates)
      .eq("id", id)
      .select()
      .single();

    if (error) throw error;

    // Log action
    const actionType = body.status === "in_progress" ? "in_progress"
      : body.status === "resolved" ? "resolved"
      : body.status === "closed" ? "closed"
      : "assigned";

    const actionMetadata: Record<string, unknown> = {};
    if (body.closure_evidence) actionMetadata.closure_evidence = body.closure_evidence;
    if (body.exemption_reason) actionMetadata.exemption_reason = body.exemption_reason;
    if (body.source_id) actionMetadata.source_id = body.source_id;

    await supabaseAdmin.from("work_order_actions").insert({
      work_order_id: id,
      action: actionType,
      comment: body.comment || body.exemption_reason || null,
      performed_by: body.resolved_by || null,
      metadata: Object.keys(actionMetadata).length > 0 ? actionMetadata : undefined,
    });

    await logAudit({
      action: "knowledge_create",
      resource_type: "work_orders",
      resource_id: id,
      detail: { from_status: existing.status, to_status: body.status, title: existing.title },
      correlation_id: correlationId,
    });

    return NextResponse.json({ work_order: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
