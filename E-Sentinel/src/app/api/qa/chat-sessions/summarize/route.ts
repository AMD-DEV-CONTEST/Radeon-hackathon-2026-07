import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLM } from "@/lib/llm-provider";
import { logLlmCall } from "@/lib/audit";
import { parseLlmJson } from "@/lib/parse-llm-response";

export async function POST(request: Request) {
  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { date_from, date_to, platform_id } = body as {
      date_from?: string;
      date_to?: string;
      platform_id?: string;
    };

    let query = supabaseAdmin
      .from("bot_chat_sessions")
      .select("id, conversation, bot_handled, transfer_reason, satisfaction, sentiment_score, is_inquiry, inquiry_result, session_type");

    if (date_from) query = query.gte("created_at", date_from);
    if (date_to) query = query.lte("created_at", date_to + "T23:59:59.999Z");
    if (platform_id) query = query.eq("platform_id", platform_id);

    const { data: sessions } = await query;
    if (!sessions || sessions.length === 0) {
      return NextResponse.json({ summary: "所选时间范围内无聊天记录", top_questions: [], independent_rate: 0 });
    }

    const total = sessions.length;
    const botHandled = sessions.filter((s: any) => s.bot_handled).length;
    const independentRate = total > 0 ? (botHandled / total) * 100 : 0;
    const transfers = sessions.filter((s: any) => !s.bot_handled);
    const badRated = sessions.filter((s: any) => s.satisfaction === "bad");
    const lostInquiries = sessions.filter((s: any) => s.is_inquiry && s.inquiry_result === "lost");

    const conversationsSample = sessions.slice(0, 30).map((s: any) =>
      s.conversation.slice(0, 300)
    ).join("\n---\n");

    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是电商客服机器人运营专家。请根据提供的统计数据生成每日摘要。

输出纯 JSON：
{
  "summary": "string (200字以内的整体摘要)",
  "top_questions": [{ "question": "string", "count": number }],
  "emerging_issues": ["string"],
  "independent_rate_analysis": "string"
}`,
        },
        {
          role: "user",
          content: [
            `总对话数：${total}`,
            `机器人独立处理：${botHandled} (${independentRate.toFixed(1)}%)`,
            `转人工：${transfers.length}`,
            `差评：${badRated.length}`,
            `询单流失：${lostInquiries.length}`,
            `对话样本：\n${conversationsSample}`,
          ].join("\n"),
        },
      ],
      max_tokens: 4096,
    });

    await logLlmCall({ model, prompt_type: "summarize", latency_ms: Date.now() - t0, was_fallback: wasFallback, cached, correlation_id: "summarize" });

    const parsed = parseLlmJson(content);
    const summary = parsed || { summary: content.slice(0, 500), top_questions: [], independent_rate_analysis: "" };

    return NextResponse.json({
      ...summary,
      independent_rate: independentRate,
      stats: { total, bot_handled: botHandled, transfer_count: transfers.length, bad_count: badRated.length, lost_inquiry_count: lostInquiries.length },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Summarize] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
