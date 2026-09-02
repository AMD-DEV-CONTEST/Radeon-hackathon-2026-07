import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding, embeddingToPgVector } from "@/lib/embedding";
import { callLLM } from "@/lib/llm-provider";
import { createCorrelationId } from "@/lib/correlation";
import { logAudit, logLlmCall } from "@/lib/audit";
import { resolveCategory, parseImportJSON } from "@/lib/knowledge-import-utils";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

const SYSTEM_PROMPT = `你是一个知识库管理助手。从以下文本中提取所有问答对（FAQ）。
对于每对问答，提取：问答标题、问题、答案、分类（物流/产品/售后/政策/通用）。

请以JSON数组格式返回：
[{"title":"...","content":"问题:xxx\\n答案:yyy","category":"物流"}]

如果没有找到明确的问答对，请根据文本内容生成3-5个常见问答。`;

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

    let text: string | null = null;
    const contentType = request.headers.get("content-type") || "";

    if (contentType.includes("multipart/form-data")) {
      const formData = await request.formData();
      const file = formData.get("file") as File | null;
      const textField = formData.get("text") as string | null;

      if (file) {
        // Validate file extension
        const fileName = file.name.toLowerCase();
        const allowedExtensions = [".txt", ".csv", ".md"];
        const hasAllowedExt = allowedExtensions.some((ext) => fileName.endsWith(ext));
        if (!hasAllowedExt) {
          return NextResponse.json(
            { error: "Unsupported file type. Please upload .txt, .csv, or .md files." },
            { status: 400 },
          );
        }
        // Limit file size to 5MB
        if (file.size > 5 * 1024 * 1024) {
          return NextResponse.json(
            { error: "File too large. Maximum size is 5MB." },
            { status: 400 },
          );
        }
        text = await file.text();
      } else if (textField && textField.trim()) {
        text = textField;
      }
    } else {
      const body = await request.json().catch(() => ({}));
      text = body.text || null;
    }

    if (!text || !text.trim()) {
      return NextResponse.json({ error: "No text content provided" }, { status: 400 });
    }

    const trimmedText = text.trim().slice(0, 8000);

    // Call LLM to extract Q&A pairs
    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: `文本内容：\n${trimmedText}` },
      ],
      max_tokens: 4096,
      useCache: false,
    });

    await logLlmCall({
      model,
      prompt_type: "faq_import_extract",
      latency_ms: Date.now() - t0,
      was_fallback: wasFallback,
      cached,
      correlation_id: createCorrelationId("import"),
    });

    const parsed = parseImportJSON(content);

    if (parsed.length === 0) {
      return NextResponse.json(
        { error: "未能从文本中提取到问答对，请检查文本内容后重试" },
        { status: 422 },
      );
    }

    const created: Record<string, unknown>[] = [];

    for (const entry of parsed) {
      const entryTitle = typeof entry.title === "string" ? entry.title.trim() : "";
      const entryContent = typeof entry.content === "string" ? entry.content.trim() : "";

      if (!entryTitle || !entryContent) continue;

      const category = resolveCategory(
        typeof entry.category === "string" ? entry.category : undefined,
      );
      const embedding = textToEmbedding(`${entryTitle} ${entryContent}`);

      const { data: row, error } = await supabaseAdmin
        .from("knowledge_entries")
        .insert({
          category,
          title: entryTitle,
          content: entryContent,
          keywords: [],
          tags: ["ai_imported"],
          tone: "professional",
          priority: 5,
          source: "batch_import",
          status: "draft",
          embedding: embeddingToPgVector(embedding),
          version: 1,
          tenant_id: tenantId,
        })
        .select()
        .single();

      if (row) created.push(row);
      if (error) console.error("[Knowledge Import] Insert error:", error.message);
    }

    await logAudit({
      action: "campaign_import",
      resource_type: "knowledge_entries",
      detail: { count: created.length },
      correlation_id: createCorrelationId("import"),
    });

    return NextResponse.json({ imported: created.length, entries: created });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge Import] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
