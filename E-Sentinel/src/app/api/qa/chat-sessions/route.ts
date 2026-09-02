import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { createCorrelationId } from "@/lib/correlation";
import { getPublicErrorMessage, toUtcRangeEnd } from "@/lib/api-error";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platformId = searchParams.get("platform_id");
    const sessionType = searchParams.get("session_type");
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");
    const satisfaction = searchParams.get("satisfaction");
    const isInquiry = searchParams.get("is_inquiry");
    const botHandled = searchParams.get("bot_handled");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);
    const offset = parseInt(searchParams.get("offset") || "0");
    const sort = searchParams.get("sort") || "risk";
    const pendingOnly = searchParams.get("pending_only") === "true";

    let query = supabaseAdmin
      .from("bot_chat_sessions")
      .select("*, platforms!inner(name)", { count: "exact" });

    // Filters
    if (platformId) query = query.eq("platform_id", platformId);
    if (sessionType) query = query.eq("session_type", sessionType);
    if (dateFrom) query = query.gte("created_at", dateFrom);
    if (dateTo) query = query.lte("created_at", toUtcRangeEnd(dateTo));
    if (satisfaction) query = query.eq("satisfaction", satisfaction);
    if (isInquiry) query = query.eq("is_inquiry", isInquiry === "true");
    if (botHandled) query = query.eq("bot_handled", botHandled === "true");

    // Pending-only: bad satisfaction, lost inquiry, or high risk (low sentiment)
    if (pendingOnly) {
      query = query.or("satisfaction.eq.bad,inquiry_result.eq.lost,and(sentiment_score.not.is.null,sentiment_score.lt.2.5)");
    }

    // Sort: risk-first or latest-first
    if (sort === "risk") {
      // Risk priority encoded in ordering: bad satisfaction first, then low sentiment, then lost, then newest
      query = query.order("created_at", { ascending: false });
    } else {
      query = query.order("created_at", { ascending: false });
    }

    query = query.range(offset, offset + limit - 1);

    const { data, error, count } = await query;

    if (error) throw error;

    const sessions = (data || []).map((row: any) => ({
      ...row,
      platform_name: row.platforms?.name || null,
      platforms: undefined,
    }));

    return NextResponse.json({ sessions, total: count });
  } catch (error) {
    const message = getPublicErrorMessage(error, "加载会话数据失败");
    console.error("[ChatSessions] GET error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { platform_id, sessions } = body as {
      platform_id: string;
      sessions: {
        session_type: string;
        external_session_id?: string;
        customer_id?: string;
        bot_handled?: boolean;
        transfer_reason?: string;
        is_inquiry?: boolean;
        inquiry_result?: string;
        sentiment_score?: number;
        satisfaction?: string;
        total_messages?: number;
        first_response_ms?: number;
        resolution_ms?: number;
        tags?: string[];
        conversation: string;
        created_at?: string;
      }[];
    };

    if (!platform_id || !sessions || sessions.length === 0) {
      return NextResponse.json({ error: "platform_id and sessions[] are required" }, { status: 400 });
    }

    const imported: unknown[] = [];
    const correlationId = createCorrelationId("chat");

    for (const s of sessions) {
      const { data, error } = await supabaseAdmin
        .from("bot_chat_sessions")
        .insert({
          platform_id,
          session_type: s.session_type || "post_sale",
          external_session_id: s.external_session_id || null,
          customer_id: s.customer_id || null,
          bot_handled: s.bot_handled ?? true,
          transfer_reason: s.transfer_reason || null,
          is_inquiry: s.is_inquiry ?? false,
          inquiry_result: s.inquiry_result || null,
          sentiment_score: s.sentiment_score || null,
          satisfaction: s.satisfaction || null,
          total_messages: s.total_messages || 0,
          first_response_ms: s.first_response_ms || null,
          resolution_ms: s.resolution_ms || null,
          tags: s.tags || [],
          conversation: s.conversation,
          correlation_id: correlationId,
          created_at: s.created_at || new Date().toISOString(),
        })
        .select()
        .single();

      if (data) imported.push(data);
      if (error) console.error("[ChatSessions] Import error:", error.message);
    }

    return NextResponse.json({ imported, count: imported.length }, { status: 201 });
  } catch (error) {
    const message = getPublicErrorMessage(error, "导入会话失败");
    console.error("[ChatSessions] POST error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
