import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { createCorrelationId } from "@/lib/correlation";
import { textToEmbedding } from "@/lib/embedding";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;

    const { data, error } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("*, platforms(name)")
      .eq("id", id)
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    const session = { ...data, platform_name: data.platforms?.name || null, platforms: undefined };

    return NextResponse.json({ session });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ChatSessions] GET/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

/** Evaluate a bot chat session using the existing LLM-as-Judge pipeline */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;

    // Fetch session
    const { data: session } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("*")
      .eq("id", id)
      .single();

    if (!session) return NextResponse.json({ error: "Session not found" }, { status: 404 });

    // Forward to existing evaluate endpoint pattern
    const evaluateRes = await fetch(
      `${process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3001"}/api/qa/evaluate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation: session.conversation,
          ticket_id: session.external_session_id || session.id,
          skip_feishu: true,
          review_mode: "shadow",
          created_at: session.created_at,
        }),
      }
    );

    const evaluateData = await evaluateRes.json();

    // Link the quality report back to this bot session
    if (evaluateData.report_id) {
      await supabaseAdmin
        .from("quality_reports")
        .update({
          is_bot_session: true,
          bot_session_id: id,
          platform_id: session.platform_id,
        })
        .eq("id", evaluateData.report_id);
    }

    return NextResponse.json({
      session_id: id,
      evaluation: evaluateData,
    }, { status: evaluateRes.ok ? 200 : 502 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ChatSessions] Evaluate error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
