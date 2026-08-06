// ============================================================================
// Unresolved Questions — Single entry: PATCH (status), DELETE
// ============================================================================

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;
    const body = await request.json().catch(() => ({}));
    const {
      status, assigned_to, note, category, tags, priority, resolved_by,
    } = body;

    // Validate status transitions
    const allowedStatuses = ["pending", "processing", "resolved", "rejected", "exported"];
    if (status && !allowedStatuses.includes(status)) {
      return NextResponse.json({ error: `Invalid status. Must be one of: ${allowedStatuses.join(", ")}` }, { status: 400 });
    }

    const updateData: Record<string, unknown> = {};
    if (status) updateData.status = status;
    if (assigned_to !== undefined) updateData.assigned_to = assigned_to;
    if (note !== undefined) updateData.note = note;
    if (category !== undefined) updateData.category = category;
    if (tags !== undefined) updateData.tags = tags;
    if (priority !== undefined) updateData.priority = priority;
    if (status === "resolved") {
      updateData.resolved_by = resolved_by || "system";
      updateData.resolved_at = new Date().toISOString();
    }

    if (Object.keys(updateData).length === 0) {
      return NextResponse.json({ error: "No fields to update" }, { status: 400 });
    }

    const { data, error } = await supabaseAdmin
      .from("unresolved_questions")
      .update(updateData)
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (error) throw error;

    // 写操作日志
    const action = status === "resolved" ? "resolve" as const
      : status === "rejected" ? "reject" as const
      : status === "exported" ? "export" as const
      : assigned_to ? "assign" as const
      : "update_status" as const;

    await supabaseAdmin.from("unresolved_question_logs").insert({
      unresolved_id: id,
      action,
      operator: resolved_by || assigned_to || null,
      detail: updateData,
    });

    await logAudit({
      action: "unresolved_questions_update",
      resource_type: "unresolved_questions",
      resource_id: id,
      detail: updateData,
    });

    return NextResponse.json({ entry: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Unresolved] PATCH error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
