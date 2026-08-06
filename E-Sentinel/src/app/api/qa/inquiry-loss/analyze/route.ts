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
        .select("id, conversation, transfer_reason")
        .in("id", session_ids.slice(0, 20));
      sessions = data || [];
    } else {
      const { data } = await supabaseAdmin
        .from("bot_chat_sessions")
        .select("id, conversation, transfer_reason")
        .eq("is_inquiry", true)
        .eq("inquiry_result", "lost")
        .order("created_at", { ascending: false })
        .limit(15);
      sessions = data || [];
    }

    if (!sessions || sessions.length === 0) {
      return NextResponse.json({ error: "No lost inquiry sessions found" }, { status: 404 });
    }

    const convoText = sessions.map((s: any) =>
      `[session_id=${s.id}] transfer_reason=${s.transfer_reason || "未知"}\n${s.conversation.slice(0, 500)}`
    ).join("\n---\n");

    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是电商转化优化专家。请分析询单流失对话，找出转化失败的根因和改进建议。

输出纯 JSON：
{
  "root_causes": [{ "cause": "string", "count": number, "examples": ["原文引用"], "suggestion": "改进建议" }],
  "overall_analysis": "string (整体分析，200字以内)"
}`,
        },
        { role: "user", content: `分析以下 ${sessions.length} 条流失询单对话：\n\n${convoText.slice(0, 10000)}` },
      ],
      max_tokens: 4096,
    });

    await logLlmCall({ model, prompt_type: "inquiry_loss_analyze", latency_ms: Date.now() - t0, was_fallback: wasFallback, cached, correlation_id: "inquiry-loss-analyze" });

    const parsed = parseLlmJson(content);
    const result = parsed || { root_causes: [], overall_analysis: "" };

    // Fallback: if LLM JSON is truncated, show what we got
    if (!parsed && content.length > 0) {
      result.overall_analysis = `LLM 返回格式异常（可能因内容过长被截断）。原始响应：\n${content.slice(0, 1000)}`;
    }

    // Auto-create optimization tasks (closing the loop)
    const pipeline = await triggerTaskPipeline({
      source_type: "inquiry_loss",
      session_ids: sessions.map((s: any) => s.id),
      context: { root_cause_count: (result as any).root_causes?.length || 0 },
    });

    return NextResponse.json({ ...result, _pipeline_tasks_created: pipeline.tasks_created });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[InquiryLoss] Analyze error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
