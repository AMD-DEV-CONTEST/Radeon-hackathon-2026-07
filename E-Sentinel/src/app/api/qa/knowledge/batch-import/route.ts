import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding, embeddingToPgVector } from "@/lib/embedding";
import { createCorrelationId } from "@/lib/correlation";
import { callLLM } from "@/lib/llm-provider";
import { logAudit, logLlmCall } from "@/lib/audit";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

type ImportEntry = {
  category?: string;
  title?: string;
  content?: string;
  keywords?: string[];
  tags?: string[];
  priority?: number;
};

export async function POST(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { entries, source, platform_id } = body as {
      entries?: { category: string; title: string; content: string; keywords?: string[]; tags?: string[]; priority?: number }[];
      source?: string;
      platform_id?: string;
    };

    // If raw campaign doc is provided, use LLM to extract structured entries
    if (!entries && source) {
      const { content, model, cached, wasFallback } = await callLLM({
        messages: [
          {
            role: "system",
            content: `你是电商客服机器人运营专家。请从活动/产品文档中提取可录入知识库的结构化条目。

对每个条目，归类为以下之一：
- "product": 商品信息（规格、材质、价格等）
- "faq": 常见问题及回答
- "after_sales_policy": 售后政策
- "campaign": 活动话术（促销力度、时间、规则）
- "greeting": 迎宾语/首弹卡片

输出纯 JSON 数组：
[
  {
    "category": "product|faq|after_sales_policy|campaign|greeting",
    "title": "string (简短标题)",
    "content": "string (完整答复内容或知识说明)",
    "keywords": ["string"],
    "tags": ["string"],
    "priority": number (0-10, 越高越优先展示)
  }
]`,
          },
          { role: "user", content: `从以下活动文档中提取知识库条目：\n\n${source.slice(0, 8000)}` },
        ],
        max_tokens: 4096,
      });

      await logLlmCall({ model, prompt_type: "campaign_extract", latency_ms: Date.now() - t0, was_fallback: wasFallback, cached, correlation_id: "batch-import" });

      const parsed = parseImportJSON(content);
      const created: unknown[] = [];
      for (const entry of parsed) {
        if (!entry.title || !entry.content) continue;
        const embedding = textToEmbedding(`${entry.title} ${entry.content}`);
        const { data: row } = await supabaseAdmin
          .from("knowledge_entries")
          .insert({
            category: entry.category || "campaign",
            platform_id: platform_id || null,
            title: entry.title,
            content: entry.content,
            keywords: entry.keywords || [],
            tags: [...(entry.tags || []), "llm_extracted"],
            priority: entry.priority || 0,
            source: "campaign_doc",
            status: "draft",
            embedding: embeddingToPgVector(embedding),
            version: 1,
            tenant_id: tenantId,
          })
          .select()
          .single();
        if (row) created.push(row);
      }

      await logAudit({ action: "campaign_import", resource_type: "knowledge_entries", detail: { count: created.length } });
      return NextResponse.json({ entries: created, count: created.length });
    }

    if (!entries || entries.length === 0) {
      return NextResponse.json({ error: "entries array or source document is required" }, { status: 400 });
    }

    const correlationId = createCorrelationId("kn");
    const created: unknown[] = [];

    for (const entry of entries) {
      const embedding = textToEmbedding(`${entry.title} ${entry.content}`);
      const { data, error } = await supabaseAdmin
        .from("knowledge_entries")
        .insert({
          category: entry.category || "faq",
          platform_id: platform_id || null,
          title: entry.title,
          content: entry.content,
          keywords: entry.keywords || [],
          tags: entry.tags || [],
          priority: entry.priority || 0,
          source: "batch_import",
          status: "draft",
          embedding: embeddingToPgVector(embedding),
          version: 1,
        })
        .select()
        .single();

      if (data) created.push(data);
      if (error) console.error("[Knowledge] Batch import item error:", error.message);
    }

    await supabaseAdmin.from("knowledge_update_logs").insert({
      update_type: "batch_import",
      field_changed: "batch",
      new_value: `${created.length} entries`,
      correlation_id: correlationId,
    }).select().maybeSingle();

    return NextResponse.json({ entries: created, count: created.length }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge] Batch import error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function parseImportJSON(content: string): ImportEntry[] {
  const raw = content.replace(/```json\s*/gi, "").replace(/```\s*/gi, "").trim();
  const arrStart = raw.indexOf("[");
  const arrEnd = raw.lastIndexOf("]");
  if (arrStart !== -1 && arrEnd !== -1 && arrEnd > arrStart) {
    try {
      const parsed: unknown = JSON.parse(raw.substring(arrStart, arrEnd + 1));
      if (!Array.isArray(parsed)) return [];

      return parsed.filter((entry): entry is ImportEntry => {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) return false;
        const candidate = entry as Record<string, unknown>;
        return (candidate.title === undefined || typeof candidate.title === "string")
          && (candidate.content === undefined || typeof candidate.content === "string")
          && (candidate.keywords === undefined || (Array.isArray(candidate.keywords) && candidate.keywords.every((item) => typeof item === "string")))
          && (candidate.tags === undefined || (Array.isArray(candidate.tags) && candidate.tags.every((item) => typeof item === "string")))
          && (candidate.priority === undefined || typeof candidate.priority === "number");
      });
    } catch {}
  }
  return [];
}
