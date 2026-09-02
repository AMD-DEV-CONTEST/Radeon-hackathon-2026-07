import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLM } from "@/lib/llm-provider";
import { logLlmCall } from "@/lib/audit";
import { triggerTaskPipeline } from "@/lib/pipeline";
import { extractUserQuestions } from "@/lib/chat-parser";
import { parseLlmJsonArray } from "@/lib/parse-llm-response";
import type { TopicCluster } from "@/lib/types/bot";

export async function POST(request: Request) {
  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { session_ids, date_from, date_to, platform_id } = body as {
      session_ids?: string[];
      date_from?: string;
      date_to?: string;
      platform_id?: string;
    };

    let sessions: any[] = [];
    if (session_ids && session_ids.length > 0) {
      const { data } = await supabaseAdmin
        .from("bot_chat_sessions")
        .select("id, conversation")
        .in("id", session_ids.slice(0, 30));
      sessions = data || [];
    } else {
      let query = supabaseAdmin
        .from("bot_chat_sessions")
        .select("id, conversation")
        .order("created_at", { ascending: false })
        .limit(20);

      if (date_from) query = query.gte("created_at", date_from);
      if (date_to) query = query.lte("created_at", date_to + "T23:59:59.999Z");
      if (platform_id) query = query.eq("platform_id", platform_id);

      const { data } = await query;
      sessions = data || [];
    }

    if (sessions.length === 0) {
      return NextResponse.json({ clusters: [] });
    }

    const inputs = extractUserQuestions(sessions as any);
    const questionList = inputs.flatMap((item: any) => item.user_questions || []).filter(Boolean);

    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是电商客服数据分析师。请对用户问题进行语义聚类，发现高频话题簇。

输出纯 JSON 数组：
[
  {
    "topic": "话题标签（10字以内）",
    "count": 数字,
    "examples": ["示例问题1", "示例问题2"],
    "suggestion": "针对此类问题的优化建议"
  }
]

最多输出 8 个话题簇，按 count 降序。`,
        },
        { role: "user", content: `对以下 ${questionList.length} 条用户问题进行聚类：\n${questionList.map((q: string, i: number) => `${i + 1}. ${q}`).join("\n").slice(0, 12000)}` },
      ],
      max_tokens: 4096,
    });

    await logLlmCall({ model, prompt_type: "cluster", latency_ms: Date.now() - t0, was_fallback: wasFallback, cached, correlation_id: "cluster" });

    const parsed = parseLlmJsonArray(content);
    const clusters: TopicCluster[] = (parsed as TopicCluster[]) || [{ topic: "未分类", count: sessions.length, examples: [], suggestion: "" }];

    // Auto-create tasks from clusters
    await triggerTaskPipeline({
      source_type: "chat_inspection",
      session_ids: sessions.map((s: any) => s.id),
      context: { clusters: clusters.map((c: TopicCluster) => ({ topic: c.topic, count: c.count })) },
    });

    return NextResponse.json({ clusters });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Cluster] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
