import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";

const VALID_ACTIONS = ["delete", "archive", "publish"] as const;
type BatchAction = (typeof VALID_ACTIONS)[number];

export async function POST(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { action, ids } = body as {
      action?: string;
      ids?: string[];
    };

    if (!action || !VALID_ACTIONS.includes(action as BatchAction)) {
      return NextResponse.json(
        { error: `Invalid action. Must be one of: ${VALID_ACTIONS.join(", ")}` },
        { status: 400 }
      );
    }

    if (!ids || !Array.isArray(ids) || ids.length === 0) {
      return NextResponse.json(
        { error: "ids array is required and must contain at least one id" },
        { status: 400 }
      );
    }

    const correlationId = createCorrelationId("kn");

    const updatePayload: Record<string, unknown> = {
      updated_at: new Date().toISOString(),
    };

    switch (action as BatchAction) {
      case "publish":
        updatePayload.status = "published";
        break;
      case "archive":
        updatePayload.status = "archived";
        break;
      case "delete":
        // Soft delete: archive
        updatePayload.status = "archived";
        break;
    }

    const { data: updated, error } = await supabaseAdmin
      .from("knowledge_entries")
      .update(updatePayload)
      .in("id", ids)
      .select("id, title, status");

    if (error) throw error;

    // Log each operation
    for (const id of ids) {
      await supabaseAdmin.from("knowledge_update_logs").insert({
        knowledge_id: id,
        update_type: action === "publish" ? "publish" : "archive",
        field_changed: "status",
        new_value: updatePayload.status,
        correlation_id: correlationId,
      }).select().maybeSingle();
    }

    await logAudit({
      action: "knowledge_batch_operation",
      resource_type: "knowledge_entries",
      detail: {
        action,
        ids,
        count: ids.length,
        affected: (updated || []).length,
      },
      correlation_id: correlationId,
    });

    return NextResponse.json({
      success: true,
      action,
      count: ids.length,
      affected: (updated || []).length,
      entries: updated || [],
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge] Batch error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
