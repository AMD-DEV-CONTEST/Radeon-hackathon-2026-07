import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding } from "@/lib/embedding";
import type { TopicCluster } from "@/lib/types/bot";
import { recordLLMCall } from "@/lib/llm-metrics";
import { callLLM, getCached, setCache } from "@/lib/llm-provider";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platformId = searchParams.get("platform_id");
    const limit = Math.min(parseInt(searchParams.get("limit") || "20"), 50);

    // Fetch bot chat sessions where bot couldn't handle (transferred or low satisfaction)
    let query = supabaseAdmin
      .from("bot_chat_sessions")
      .select("id, conversation, transfer_reason, satisfaction")
      .eq("bot_handled", false)
      .order("created_at", { ascending: false })
      .limit(limit);

    if (platformId) query = query.eq("platform_id", platformId);

    const { data: sessions, error } = await query;

    if (error) throw error;
    if (!sessions || sessions.length === 0) {
      return NextResponse.json({ gaps: [], message: "No unresolved sessions to analyze" });
    }

    // Extract user questions
    const userQuestions: string[] = [];
    for (const s of sessions) {
      const lines = s.conversation.split("\n");
      for (const line of lines) {
        const m = line.match(/^(?:用户|顾客|Customer)[：:]\s*(.+)/i);
        if (m) userQuestions.push(m[1]);
      }
    }

    if (userQuestions.length === 0) {
      return NextResponse.json({ gaps: [] });
    }

    // Check against knowledge base using RAG
    const gaps: { question: string; best_match?: string; similarity: number }[] = [];
    for (const q of userQuestions.slice(0, 30)) {
      const embedding = textToEmbedding(q);
      const vecStr = `[${embedding.map((v) => v.toFixed(6)).join(",")}]`;
      const { data: matches } = await supabaseAdmin.rpc("match_knowledge_entries", {
        query_embedding: vecStr,
        match_count: 3,
      });

      const best = matches?.[0];
      if (!best || best.similarity < 0.15) {
        gaps.push({ question: q, similarity: best?.similarity || 0 });
      }
    }

    // If LLM available, generate clustered gap analysis
    let clusters: TopicCluster[] = [];
    if (gaps.length >= 3) {
      clusters = await generateGapClusters(gaps.map((g) => g.question));
    }

    return NextResponse.json({ gaps, clusters, total_unhandled: sessions.length });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge] Gaps error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

async function generateGapClusters(questions: string[]): Promise<TopicCluster[]> {
  const cacheKey = `kg:gaps:${questions.slice(0, 5).join("|").slice(0, 200)}`;

  const cached = getCached(cacheKey);
  if (cached) {
    try {
      const parsed = JSON.parse(cached);
      recordLLMCall({ endpoint: "/api/qa/knowledge/gaps", model: "auto", responseTimeMs: 0, tokensUsed: 0, success: true, cached: true });
      return parsed;
    } catch { /* fall through to LLM call */ }
  }

  const systemPrompt = `你是知识库管理专家。请对未命中的用户问题做聚类，给出知识缺口分析。

输出纯 JSON 数组：
[
  {
    "topic": "string (问题簇标签)",
    "count": number,
    "examples": ["string", "string"],
    "suggestion": "string (建议创建什么知识条目来填补缺口)"
  }
]`;

  const t0 = Date.now();

  try {
    const content = await callLLM({
      prompt: `以下用户问题在知识库中没有匹配到：\n${questions.map((q, i) => `${i + 1}. ${q}`).join("\n")}`,
      systemPrompt,
      temperature: 0.1,
      maxTokens: 2048,
    });

    const elapsed = Date.now() - t0;

    if (!content) {
      recordLLMCall({ endpoint: "/api/qa/knowledge/gaps", model: "auto", responseTimeMs: elapsed, tokensUsed: 0, success: false });
      return [];
    }

    recordLLMCall({ endpoint: "/api/qa/knowledge/gaps", model: "auto", responseTimeMs: elapsed, tokensUsed: Math.ceil(content.length / 2), success: true, cached: false });

    const raw = content.replace(/```json\s*/gi, "").replace(/```\s*/gi, "").trim();
    const arrStart = raw.indexOf("[");
    const arrEnd = raw.lastIndexOf("]");
    if (arrStart !== -1 && arrEnd !== -1 && arrEnd > arrStart) {
      const result = JSON.parse(raw.substring(arrStart, arrEnd + 1));
      setCache(cacheKey, JSON.stringify(result), Math.ceil(content.length / 2), "auto");
      return result;
    }
    return [];
  } catch {
    const elapsed = Date.now() - t0;
    recordLLMCall({ endpoint: "/api/qa/knowledge/gaps", model: "auto", responseTimeMs: elapsed, tokensUsed: 0, success: false });
    return [];
  }
}
