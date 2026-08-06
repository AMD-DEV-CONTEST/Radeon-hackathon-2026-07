import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;

    // Fetch knowledge entry to verify existence
    const { data: entry, error: fetchErr } = await supabaseAdmin
      .from("knowledge_entries")
      .select("id, title, content, version")
      .eq("id", id)
      .single();

    if (fetchErr || !entry) {
      return NextResponse.json({ error: "Knowledge entry not found" }, { status: 404 });
    }

    // Fetch update log for this entry
    const { data: logs, error: logErr } = await supabaseAdmin
      .from("knowledge_update_logs")
      .select("update_type, field_changed, old_value, new_value, created_at, updated_by")
      .eq("knowledge_id", id)
      .order("created_at", { ascending: false })
      .limit(20);

    if (logErr) throw logErr;

    return NextResponse.json({
      entry: {
        id: entry.id,
        title: entry.title,
        content: entry.content,
        version: entry.version,
      },
      versions: (logs || []).map((l: Record<string, unknown>) => ({
        type: l.update_type,
        field: l.field_changed,
        old_value: l.old_value,
        new_value: l.new_value,
        at: l.created_at,
        by: l.updated_by,
      })),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge Versions] GET error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
