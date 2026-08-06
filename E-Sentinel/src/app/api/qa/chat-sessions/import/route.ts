import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

interface ImportSession {
  platform_id: string | number;
  external_session_id?: string;
  session_type?: string;
  customer_id?: string;
  conversation: string;
  bot_handled?: boolean;
  is_inquiry?: boolean;
  first_response_ms?: number;
  tags?: string[];
  total_messages?: number;
  satisfaction?: string;
  inquiry_result?: string;
  transfer_reason?: string;
  created_at?: string;
}

export async function POST(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => null);
    if (!body || !Array.isArray(body.sessions)) {
      return NextResponse.json(
        { error: "Request body must contain { sessions: [...] }" },
        { status: 400 },
      );
    }

    const sessions: ImportSession[] = body.sessions;
    if (sessions.length === 0) {
      return NextResponse.json({ imported: 0, skipped: 0, message: "Empty session list" });
    }
    if (sessions.length > 500) {
      return NextResponse.json(
        { error: "Max 500 sessions per batch" },
        { status: 400 },
      );
    }

    // Validate required fields
    const invalid = sessions.filter((s) => !s.platform_id || !s.conversation);
    if (invalid.length > 0) {
      return NextResponse.json(
        {
          error: `${invalid.length} sessions missing required fields (platform_id, conversation)`,
          invalid_indices: invalid.map((_, i) => i),
        },
        { status: 400 },
      );
    }

    // Resolve platform IDs — accept numeric ID or platform code string
    const platformIds = new Set(sessions.map((s) => s.platform_id));
    const platformMap = new Map<string, number>();

    for (const pid of platformIds) {
      if (typeof pid === "number") {
        platformMap.set(String(pid), pid);
      } else {
        const { data } = await supabaseAdmin
          .from("platforms")
          .select("id")
          .or(`code.eq.${pid},id.eq.${isNaN(Number(pid)) ? -1 : Number(pid)}`)
          .maybeSingle();
        if (data) {
          platformMap.set(pid, data.id as number);
        } else {
          // Auto-create platform if code doesn't exist
          const { data: created } = await supabaseAdmin
            .from("platforms")
            .insert({ name: pid, code: pid })
            .select("id")
            .single();
          if (created) platformMap.set(pid, created.id as number);
        }
      }
    }

    // Build insert rows
    const rows = sessions.map((s) => ({
      id: crypto.randomUUID(),
      platform_id: platformMap.get(String(s.platform_id)) || s.platform_id,
      session_type: s.session_type || "pre_sale",
      external_session_id: s.external_session_id || `import_${crypto.randomUUID().slice(0, 12)}`,
      customer_id: s.customer_id || "unknown",
      bot_handled: s.bot_handled ?? true,
      is_inquiry: s.is_inquiry ?? false,
      first_response_ms: s.first_response_ms ?? 0,
      tags: s.tags || [],
      conversation: s.conversation,
      total_messages: s.total_messages ?? 1,
      satisfaction: s.satisfaction || null,
      inquiry_result: s.inquiry_result || null,
      transfer_reason: s.transfer_reason || null,
      ...(s.created_at ? { created_at: s.created_at } : {}),
    }));

    // Pre-filter: check which external_session_ids already exist
    const externalIds = rows.map((r) => r.external_session_id);
    const { data: existingIds } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("external_session_id")
      .in("external_session_id", externalIds);

    const existingSet = new Set((existingIds || []).map((e: any) => e.external_session_id));
    const newRows = rows.filter((r) => !existingSet.has(r.external_session_id));

    if (newRows.length === 0) {
      return NextResponse.json({
        imported: 0,
        skipped: rows.length,
        total: rows.length,
        message: `全部跳过，${rows.length} 条已存在`,
      });
    }

    // Insert in chunks of 100 to avoid payload limits
    let imported = 0;
    let skipped = rows.length - newRows.length;

    for (let i = 0; i < newRows.length; i += 100) {
      const chunk = newRows.slice(i, i + 100);
      const { error } = await supabaseAdmin
        .from("bot_chat_sessions")
        .insert(chunk);

      if (error) {
        console.error("[ChatImport] Chunk error:", error.message);
        skipped += chunk.length;
      } else {
        imported += chunk.length;
      }
    }

    return NextResponse.json({
      imported,
      skipped,
      total: rows.length,
      message: `成功导入 ${imported} 条，跳过 ${skipped} 条`,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ChatImport] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
