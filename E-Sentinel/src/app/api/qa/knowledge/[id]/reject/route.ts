import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;
    const body = await request.json().catch(() => ({}));
    const reason = body.reason || "";

    // Get the entry to verify it exists and is in draft
    const { data: entry, error: fetchErr } = await supabaseAdmin
      .from("knowledge_entries")
      .select("id, title, status")
      .eq("id", id)
      .single();

    if (fetchErr || !entry) {
      return NextResponse.json({ error: "Knowledge entry not found" }, { status: 404 });
    }

    if (entry.status !== "draft") {
      return NextResponse.json({ error: `Cannot reject: entry is in "${entry.status}" status` }, { status: 400 });
    }

    const correlationId = createCorrelationId("kn");

    // Archive the rejected entry
    const { error: updateErr } = await supabaseAdmin
      .from("knowledge_entries")
      .update({
        status: "archived",
        updated_at: new Date().toISOString(),
      })
      .eq("id", id);

    if (updateErr) throw updateErr;

    // Log with rejection reason
    await supabaseAdmin.from("knowledge_update_logs").insert({
      knowledge_id: id,
      update_type: "archive",
      field_changed: "status",
      old_value: "draft",
      new_value: "archived",
      correlation_id: correlationId,
    });

    await logAudit({
      action: "knowledge_reject",
      resource_type: "knowledge_entries",
      resource_id: id,
      detail: { title: entry.title, reason },
      correlation_id: correlationId,
    });

    return NextResponse.json({ success: true, entry: { ...entry, status: "archived" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge Reject] POST error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
