import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLM } from "@/lib/llm-provider";
import { logAudit, logLlmCall } from "@/lib/audit";
import { triggerTaskPipeline } from "@/lib/pipeline";
import type { InspectResult } from "@/lib/types/bot";
import { parseLlmJsonArray } from "@/lib/parse-llm-response";

export async function POST(request: Request) {
  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { session_ids } = body as { session_ids?: string[] };

    if (!session_ids || session_ids.length === 0) {
      return NextResponse.json({ error: "session_ids[] is required" }, { status: 400 });
    }

    if (session_ids.length > 20) {
      return NextResponse.json({ error: "Max 20 sessions per batch" }, { status: 400 });
    }

    const { data: sessions } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("id, conversation, platform_id")
      .in("id", session_ids);

    if (!sessions || sessions.length === 0) {
      return NextResponse.json({ error: "No sessions found" }, { status: 404 });
    }

    const convoText = sessions
      .map((s: any, i: number) => `[${i}] session_id=${s.id}\n${s.conversation}`)
      .join("\n\n---\n\n");

    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是电商客服机器人运营专家。请逐条分析客服机器人对话，发现话术缺陷、知识缺口、逻辑问题。

对每条对话输出：
{
  "session_id": "string",
  "issues": [{ "category": "string", "severity": "minor|major|critical", "description": "string", "source_quote": "原文引用" }],
  "suggestions": [{ "type": "script|knowledge|logic|policy", "title": "string", "detail": "string", "expected_impact": "string" }],
  "quality_label": "good|needs_improvement|problematic",
  "independent_rate_impact": "positive|neutral|negative"
}

输出纯 JSON 数组，不包裹 markdown 代码块。`,
        },
        { role: "user", content: `请分析以下 ${sessions.length} 条客服对话：\n\n${convoText.slice(0, 12000)}` },
      ],
      max_tokens: 4096,
    });

    const results = parseInspectJSON(content, sessions.map((s: any) => s.id));

    await logLlmCall({ model, prompt_type: "chat_inspect", latency_ms: Date.now() - t0, was_fallback: wasFallback, cached, correlation_id: "inspect" });

    // Auto-create optimization tasks from inspection findings
    const problematicIds = results
      .filter((r) => r.quality_label !== "good")
      .map((r) => r.session_id);

    if (problematicIds.length > 0) {
      await triggerTaskPipeline({
        source_type: "chat_inspection",
        session_ids: problematicIds,
        context: { total_inspected: sessions.length, problems_found: problematicIds.length },
      });
    }

    return NextResponse.json({ results });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Inspect] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function parseInspectJSON(content: string, sessionIds: string[]): InspectResult[] {
  const parsed = parseLlmJsonArray(content);
  if (parsed) return parsed as InspectResult[];
  return sessionIds.map((id) => ({
    session_id: id,
    issues: [],
    suggestions: [],
    quality_label: "needs_improvement" as const,
    independent_rate_impact: "neutral" as const,
  }));
}
