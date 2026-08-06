import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding, embeddingToPgVector } from "@/lib/embedding";
import { callLLM } from "@/lib/llm-provider";
import { parseLlmJsonArray } from "@/lib/parse-llm-response";
import { logAudit, logLlmCall } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";
import { shouldAutoPublish, KNOWLEDGE_SAFE_CATEGORIES } from "@/lib/auto-publish";
import { scanCompliance, quickComplianceCheck, type ComplianceRule } from "@/lib/compliance-engine";
import { getConfigNumber } from "@/lib/system-config";
import { sendFeishuNotification } from "@/lib/feishu";
import { requireApiKey } from "@/lib/api-auth";
import { reportCronFailure } from "@/lib/cron-health";

const DEDUP_WINDOW_DAYS = 7;

const CATEGORY_DESCRIPTIONS: Record<string, { desc: string; examples: string[] }> = {
  faq: {
    desc: "常见问题 — 高频客户问题及标准回答",
    examples: ["发货时效查询", "如何修改地址", "优惠券使用规则"],
  },
  after_sales_policy: {
    desc: "售后政策 — 退换货、赔偿、投诉处理流程",
    examples: ["七天无理由退货流程", "破损件赔偿标准", "投诉升级路径"],
  },
  product: {
    desc: "产品信息 — 商品规格、使用方法、对比推荐",
    examples: ["产品A和B的区别", "如何使用某功能", "材质成分说明"],
  },
  campaign: {
    desc: "活动信息 — 促销活动规则、参与方式、优惠说明",
    examples: ["双11活动满减规则", "会员积分兑换", "限时折扣专区"],
  },
  greeting: {
    desc: "欢迎语 — 品牌问候、店铺介绍、服务承诺",
    examples: ["店铺欢迎语", "品牌故事介绍", "客服服务时间"],
  },
};

export async function GET(request: Request) {
  const auth = requireApiKey(request);
  if (auth.error) return auth.error;

  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ status: "failed", success: false, error: "Supabase not configured" }, { status: 500 });
    }

    // Fetch recent unhandled sessions (last 24h)
    const yesterday = new Date(Date.now() - 86400000).toISOString();
    const { data: sessions } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("id, conversation, transfer_reason")
      .or("bot_handled.eq.false,satisfaction.eq.bad,satisfaction.eq.neutral,transfer_reason.not.is.null")
      .gte("created_at", yesterday)
      .order("created_at", { ascending: false })
      .limit(30);

    if (!sessions || sessions.length === 0) {
      return NextResponse.json({ status: "ok", success: true, gaps: 0, message: "No unhandled sessions in last 24h" });
    }

    // Extract user questions
    const questions: string[] = [];
    for (const s of sessions) {
      const lines = s.conversation.split("\n");
      for (const line of lines) {
        const m = line.match(/^(?:用户|顾客|Customer|买家)[：:]\s*(.+)/i);
        if (m && m[1].length > 3) questions.push(m[1]);
      }
    }

    if (questions.length === 0) {
      return NextResponse.json({ status: "ok", success: true, gaps: 0 });
    }

    // RAG match against knowledge base
    const gaps: { question: string; similarity: number }[] = [];
    for (const q of questions.slice(0, 30)) {
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

    let knowledgeDraftsCreated = 0;
    let autoPublishedCount = 0;
    let dedupSkippedCount = 0;
    const createdKnowledgeIds: string[] = [];

    if (gaps.length >= 3) {
      // ── Dedup: check for existing drafts within DEDUP_WINDOW_DAYS ──
      const dedupCutoff = new Date(Date.now() - DEDUP_WINDOW_DAYS * 86400000).toISOString();
      const { data: existingDrafts } = await supabaseAdmin
        .from("knowledge_entries")
        .select("title, category")
        .eq("status", "draft")
        .gte("created_at", dedupCutoff);

      const existingTitles = new Set((existingDrafts || []).map((d: Record<string, unknown>) => String(d.title || "").trim().toLowerCase()));

      // Build LLM prompt with category descriptions
      const categoryGuide = Object.entries(CATEGORY_DESCRIPTIONS)
        .map(([key, info]) =>
          `- ${key}: ${info.desc}（例：${info.examples.join("、")}）`
        )
        .join("\n");

      const { content, model, cached } = await callLLM({
        messages: [
          {
            role: "system",
            content: `你是电商客服知识库专家。用户提出了一些在现有知识库中没有匹配的问题，请为每个缺口生成一条知识条目草稿。

## 分类说明
${categoryGuide}

## 生成规则
- title: 客户问题的标准表述（一句话，10-30字）
- content: 标准回答，带品牌温度（参考："亲，关于您问的{问题}，我来帮您解答~"），需包含具体信息和可操作步骤
- category: 从上述分类中选择最匹配的一个
- keywords: 搜索关键词数组（3-5个，覆盖客户可能使用的不同问法）
- confidence: 0-1之间的数字，表示对该条知识准确性和完整性的置信度

## 输出格式
返回 JSON 数组：
[{"title": "string", "content": "string", "category": "分类之一", "keywords": ["kw1","kw2"], "confidence": 0.85}]

只返回 JSON 数组，不要其他内容。`,
          },
          {
            role: "user",
            content: `以下用户问题在知识库中没有匹配（含相似度）：\n${gaps.map((g) => `- [相似度: ${g.similarity.toFixed(3)}] ${g.question}`).join("\n")}\n\n请为每个缺口生成知识条目草稿，包含分类和置信度。`,
          },
        ],
        max_tokens: 4096,
      });

      await logLlmCall({
        model,
        prompt_type: "knowledge_gap_cron",
        latency_ms: Date.now() - t0,
        cached,
        correlation_id: "cron-gaps",
      });

      // Parse LLM-generated knowledge entries
      const parsed = parseLlmJsonArray(content);
      if (parsed && Array.isArray(parsed)) {
        for (const item of parsed) {
          const entry = item as Record<string, unknown>;
          const title = String(entry.title || "").trim();
          const contentBody = String(entry.content || "").trim();
          let category = String(entry.category || "faq").trim();
          const keywords = Array.isArray(entry.keywords)
            ? entry.keywords.map((k) => String(k).trim()).filter(Boolean)
            : [];
          const llmConfidence = Math.min(1, Math.max(0, Number(entry.confidence) || 0.8));

          if (!title || !contentBody) continue;

          // Validate category
          const validCategories = ["product", "faq", "after_sales_policy", "campaign", "greeting"];
          if (!validCategories.includes(category)) category = "faq";

          // ── Dedup check (post-LLM, using normalized title) ──
          if (existingTitles.has(title.toLowerCase())) {
            dedupSkippedCount++;
            console.log(`[KnowledgeGaps] Skipping duplicate: ${title}`);
            continue;
          }

          // ── Auto-publish check ──
          const autoPublishThreshold = await getConfigNumber("auto_publish_threshold", 0.95);
          let canAutoPublish = shouldAutoPublish({
            confidence: llmConfidence,
            category,
            safeCategories: KNOWLEDGE_SAFE_CATEGORIES,
            threshold: autoPublishThreshold,
          });

          // ── Compliance scan before auto-publish ──
          if (canAutoPublish) {
            const contentToCheck = `${title} ${contentBody}`;
            let complianceRules: ComplianceRule[] = [];
            const { data: activeRules } = await supabaseAdmin
              .from("compliance_rules")
              .select("id, rule_text, pattern, risk_level, category, action_type, exemption_tags")
              .eq("is_active", true);

            if (activeRules && activeRules.length > 0) {
              complianceRules = activeRules.map((r: Record<string, unknown>) => ({
                id: String(r.id),
                rule_text: String(r.rule_text),
                pattern: String(r.pattern),
                risk_level: Number(r.risk_level),
                category: String(r.category),
                action_type: String(r.action_type) as ComplianceRule["action_type"],
                exemption_tags: Array.isArray(r.exemption_tags) ? r.exemption_tags.map(String) : [],
              }));
            }

            const compResult = complianceRules.length > 0
              ? scanCompliance(contentToCheck, complianceRules)
              : quickComplianceCheck(contentToCheck);

            if (!compResult.passed && compResult.decision === "blocked") {
              // Compliance overrides auto-publish: force draft
              canAutoPublish = false;
              // Log compliance block
              await supabaseAdmin.from("compliance_audit_logs").insert({
                source_type: "knowledge_entry",
                content_snippet: contentToCheck.substring(0, 200),
                risk_level: compResult.highest_risk,
                matched_rules: compResult.matches.map((m) => ({
                  rule_id: m.rule.id,
                  rule_text: m.rule.rule_text,
                  category: m.rule.category,
                  action_type: m.rule.action_type,
                })),
                decision: "blocked",
                correlation_id: "cron-gaps",
              });
              console.log(`[KnowledgeGaps] Compliance blocked auto-publish: ${compResult.summary}`);
            }
          }

          const status = canAutoPublish ? "published" : "draft";

          // Generate embedding for the new entry
          const emb = textToEmbedding(`${title} ${contentBody}`);
          const correlationId = createCorrelationId("kn");

          const { data: inserted, error: insertErr } = await supabaseAdmin
            .from("knowledge_entries")
            .insert({
              category,
              title,
              content: contentBody,
              keywords,
              priority: canAutoPublish ? 5 : 0,
              status,
              source: "knowledge_gap",
              embedding: embeddingToPgVector(emb),
              version: 1,
              effect_metrics: {
                llm_confidence: llmConfidence,
                auto_published: canAutoPublish,
              },
            })
            .select("id")
            .single();

          if (insertErr) {
            console.error("[KnowledgeGaps] Failed to insert knowledge entry:", insertErr.message);
            continue;
          }

          if (inserted) {
            createdKnowledgeIds.push(inserted.id);
            if (canAutoPublish) {
              autoPublishedCount++;
            } else {
              knowledgeDraftsCreated++;
            }

            await supabaseAdmin.from("knowledge_update_logs").insert({
              knowledge_id: inserted.id,
              update_type: canAutoPublish ? "publish" : "create",
              correlation_id: correlationId,
            });

            await logAudit({
              action: canAutoPublish ? "knowledge_publish" : "knowledge_create",
              resource_type: "knowledge_entries",
              resource_id: inserted.id,
              detail: {
                title,
                category,
                confidence: llmConfidence,
                auto_published: canAutoPublish,
                source: "knowledge_gap_cron",
              },
              correlation_id: correlationId,
            });
          }
        }
      }

      // ── Feishu notification for drafts needing review (4-level routing) ──
      if (knowledgeDraftsCreated > 0) {
        sendFeishuNotification({
          header: {
            title: { tag: "plain_text", content: `📚 知识草稿待审核 — ${knowledgeDraftsCreated} 条新草稿` },
            template: "blue",
          },
          elements: [
            {
              tag: "div",
              text: {
                tag: "lark_md",
                content: `**知识缺口检测** 发现 ${gaps.length} 个缺口，已生成 ${knowledgeDraftsCreated} 条知识条目草稿。\n\n${autoPublishedCount > 0 ? `✅ ${autoPublishedCount} 条高置信度条目已自动发布。` : ""}\n${dedupSkippedCount > 0 ? `⏭ ${dedupSkippedCount} 条重复草稿已跳过。` : ""}`,
              },
            },
            {
              tag: "action",
              actions: [{
                tag: "button",
                text: { tag: "plain_text", content: "前往审核" },
                type: "primary",
                url: `${process.env.NEXT_PUBLIC_SITE_URL || process.env.VERCEL_URL || ""}/dashboard`,
              }],
            },
          ],
        }).catch(() => {});
      }
    }

    // Auto-create optimization task
    if (gaps.length > 0) {
      const totalCreated = knowledgeDraftsCreated + autoPublishedCount;
      const taskDesc = `检测到 ${gaps.length} 个知识缺口。\n自动生成 ${totalCreated} 条知识条目：${autoPublishedCount} 条自动发布，${knowledgeDraftsCreated} 条待审核，${dedupSkippedCount} 条因重复跳过。`;

      await supabaseAdmin.from("optimization_tasks").insert({
        source: "knowledge_gap",
        category: "knowledge_gap",
        title: `知识缺口: ${gaps.length} 个缺口 → ${totalCreated} 条条目（${autoPublishedCount} 自动发布）`,
        description: taskDesc,
        priority: gaps.length > 10 ? "high" : "medium",
        related_knowledge_id: createdKnowledgeIds[0] || null,
      });
    }

    await logAudit({
      action: "knowledge_create",
      resource_type: "knowledge_gap_cron",
      detail: {
        gaps_found: gaps.length,
        drafts_created: knowledgeDraftsCreated,
        auto_published: autoPublishedCount,
        dedup_skipped: dedupSkippedCount,
        questions: gaps.slice(0, 5).map((g) => g.question),
      },
      correlation_id: "cron-gaps",
    });

    return NextResponse.json({
      status: "ok",
      success: true,
      gaps: gaps.length,
      drafts_created: knowledgeDraftsCreated,
      auto_published: autoPublishedCount,
      dedup_skipped: dedupSkippedCount,
    });
  } catch (error) {
    console.error("[KnowledgeGaps] Error:", error);
    await reportCronFailure("knowledge-gaps", error);
    return NextResponse.json({ status: "failed", success: false, error: String(error) }, { status: 500 });
  }
}
