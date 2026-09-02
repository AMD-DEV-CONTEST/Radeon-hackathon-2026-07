import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLM } from "@/lib/llm-provider";
import { logAudit, logLlmCall } from "@/lib/audit";
import { triggerTaskPipeline } from "@/lib/pipeline";
import { parseLlmJson } from "@/lib/parse-llm-response";

export async function POST(request: Request) {
  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { session_ids } = body as { session_ids?: string[] };

    let sessions: any[];
    if (session_ids && session_ids.length > 0) {
      const { data } = await supabaseAdmin
        .from("bot_chat_sessions")
        .select("id, conversation, satisfaction, session_type")
        .in("id", session_ids.slice(0, 20));
      sessions = data || [];
    } else {
      const { data } = await supabaseAdmin
        .from("bot_chat_sessions")
        .select("id, conversation, satisfaction, session_type")
        .in("satisfaction", ["bad", "neutral"])
        .order("created_at", { ascending: false })
        .limit(15);
      sessions = data || [];
    }

    if (!sessions || sessions.length === 0) {
      return NextResponse.json({ error: "No bad/neutral sessions found" }, { status: 404 });
    }

    const convoText = sessions.map((s: any) =>
      `[${s.satisfaction}] session_type=${s.session_type}\n${s.conversation.slice(0, 400)}`
    ).join("\n---\n");

    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是客服体验优化专家。请分析差评/中评对话，找出不满意的根因和优化方向。

输出纯 JSON：
{
  "causes": [{ "cause": "string", "count": number, "examples": ["原文引用"], "fix_suggestion": "string" }],
  "priority_actions": ["string (TOP3 最优先改进项)"]
}`,
        },
        { role: "user", content: `分析以下 ${sessions.length} 条差评/中评对话：\n\n${convoText.slice(0, 10000)}` },
      ],
      max_tokens: 4096,
    });

    await logLlmCall({ model, prompt_type: "satisfaction_analyze", latency_ms: Date.now() - t0, was_fallback: wasFallback, cached, correlation_id: "satisfaction-analyze" });

    const parsed = parseLlmJson(content);
    const result = parsed || { causes: [], priority_actions: [content.slice(0, 500)] };

    // Auto-create optimization tasks from findings (closing the loop)
    const pipeline = await triggerTaskPipeline({
      source_type: "satisfaction",
      session_ids: sessions.map((s: any) => s.id),
      context: { cause_count: (result as any).causes?.length || 0 },
    });

    return NextResponse.json({ ...result, _pipeline_tasks_created: pipeline.tasks_created });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Satisfaction] Analyze error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
