import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";

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

    const { data: draft, error: fetchErr } = await supabaseAdmin
      .from("bot_configs")
      .select("id, config_key, config_type, status, version")
      .eq("id", id)
      .single();

    if (fetchErr || !draft) {
      return NextResponse.json({ error: "Config not found" }, { status: 404 });
    }

    if (draft.status !== "draft") {
      return NextResponse.json({ error: `Cannot reject: config is in "${draft.status}" status` }, { status: 400 });
    }

    const { error: updateErr } = await supabaseAdmin
      .from("bot_configs")
      .update({ status: "archived", updated_at: new Date().toISOString() })
      .eq("id", id);

    if (updateErr) throw updateErr;

    await logAudit({
      action: "bot_config_reject",
      resource_type: "bot_configs",
      resource_id: id,
      detail: {
        config_key: draft.config_key,
        config_type: draft.config_type,
        version: draft.version,
        reason,
      },
    });

    return NextResponse.json({ success: true, config: { ...draft, status: "archived" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[BotConfigs Reject] POST error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
