// ============================================================================
// LLM-powered Feishu bot reply generator.
// Now uses unified callLLM from llm-provider.
// ============================================================================

import { callLLM, getCached, setCache } from "./llm-provider";
import { recordLLMCall } from "./llm-metrics";
import { hybridSearch } from "./hybrid-search";

export interface BotReplyResult {
  reply: string;
  knowledgeIds: string[];
  ragMethod: "hybrid" | "vector_only" | "keyword_only" | "sql_fallback" | "none";
}

/** Keyword-based fallback reply — used when LLM is unavailable */
function keywordReply(text: string): string {
  const t = text.toLowerCase();
  if (t.includes("发货") || t.includes("物流") || t.includes("快递") || t.includes("订单")) {
    return "亲亲您好，订单物流问题已收到～仓库正在加急处理，一般48小时内更新物流信息。如需催单，我会为您标记加急，请您耐心等待哦 ❤️";
  }
  if (t.includes("退款") || t.includes("退货") || t.includes("退钱")) {
    return "亲亲您好，退款问题已记录～售后客服会在1个工作日内核实处理，请您保持联系畅通。如需加急，请回复「加急退款」～";
  }
  if (t.includes("优惠券") || t.includes("满减") || t.includes("活动")) {
    return "亲亲您好，优惠相关咨询已收到～不同活动优惠券使用规则略有差异，建议您查看商品详情页的优惠说明，或回复具体券码我帮您查询哦～";
  }
  if (t.includes("质量") || t.includes("瑕疵") || t.includes("破损") || t.includes("坏了") || t.includes("烂了")) {
    return "亲亲非常抱歉给您带来不好的体验！商品质量问题我们非常重视，请您拍照上传问题商品照片，售后专员会优先为您处理退换货～";
  }
  return "亲亲您好，您的问题已收到～客服正在马不停蹄赶来，请稍等片刻，感谢您的耐心与理解 ❤️";
}

/** Simple text hash for cache key */
function simpleHash(input: string): string {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    const chr = input.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

/**
 * Generate a bot reply using LLM with knowledge base context.
 * Falls back to keyword-based reply on error/timeout.
 */
export async function generateLLMBotReply(
  text: string,
  history = "",
  tenantId?: string,
): Promise<string> {
  const result = await generateLLMBotReplyWithMetadata(text, history, tenantId);
  return result.reply;
}

async function retrieveKnowledge(
  text: string,
  tenantId?: string,
): Promise<Pick<BotReplyResult, "knowledgeIds" | "ragMethod"> & { context: string }> {
  if (!text.trim()) return { context: "", knowledgeIds: [], ragMethod: "none" };
  const scopedTenantId = tenantId?.trim();
  if (!scopedTenantId) return { context: "", knowledgeIds: [], ragMethod: "none" };

  try {
    const hybrid = await Promise.race([
      hybridSearch(text, { limit: 5, matchCount: 20, tenantId: scopedTenantId }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 650)),
    ]);
    if (hybrid && hybrid.matches.length > 0) {
      return {
        context: hybrid.matches.map((e) => `【${e.title}】${e.content}`).join("\n"),
        knowledgeIds: hybrid.matches.map((e) => e.id),
        ragMethod: hybrid.method,
      };
    }
  } catch {
    // Fall through to the legacy SQL query below.
  }

  try {
    const { supabaseAdmin } = await import("./supabase");
    if (supabaseAdmin) {
      const { data: entries } = await supabaseAdmin
        .from("knowledge_entries")
        .select("id, title, content")
        .eq("status", "published")
        .eq("tenant_id", scopedTenantId)
        .limit(5);
      if (entries && entries.length > 0) {
        return {
          context: (entries as Array<{ id: string; title: string; content: string }>)
            .map((e) => `【${e.title}】${e.content}`)
            .join("\n"),
          knowledgeIds: (entries as Array<{ id: string }>).map((e) => e.id),
          ragMethod: "sql_fallback",
        };
      }
    }
  } catch {
    // Retrieval is best-effort; reply generation still has a safe fallback.
  }

  return { context: "", knowledgeIds: [], ragMethod: "none" };
}

export async function generateLLMBotReplyWithMetadata(
  text: string,
  history = "",
  tenantId?: string,
): Promise<BotReplyResult> {
  if (!text.trim()) return { reply: keywordReply(text), knowledgeIds: [], ragMethod: "none" };

  const scopedTenantId = tenantId?.trim();
  const retrieval = await retrieveKnowledge(text, scopedTenantId);

  const cacheKey = `feishu:reply:${scopedTenantId || "unscoped"}:${simpleHash(`${text.slice(0, 300)}\n${history.slice(-2400)}`)}`;

  // Check cache first
  const cached = getCached(cacheKey);
  if (cached) {
    recordLLMCall({
      model: "auto",
      endpoint: "feishu_bot_reply",
      success: true,
      cached: true,
      tokensUsed: cached.length / 2,
      responseTimeMs: 0,
    });
    return { reply: cached, ...retrieval };
  }

  const knowledgeContext = retrieval.context.slice(0, 12000);
  const historyContext = history
    .split("\n")
    .filter(Boolean)
    .slice(-10)
    .join("\n")
    .slice(-2400);

  const systemPrompt = knowledgeContext
    ? `你是电商客服机器人。使用以下知识库内容回答客户问题。保持亲切、专业、简洁（不超过150字）。如知识库没有明确答案，不要编造价格、库存、订单或退款结论。\n\n知识库参考：\n${knowledgeContext}${historyContext ? `\n\n最近会话：\n${historyContext}` : ""}`
    : "你是电商客服机器人。请亲切、专业、简洁地回复客户（不超过150字）。如涉及退款/退货，引导联系售后。如涉及发货，说明正常时效。";

  const startTime = Date.now();

  try {
    const reply = await callLLM({
      prompt: text,
      systemPrompt,
      temperature: 0.7,
      maxTokens: 200,
      useCache: false, // we have our own caching layer
      tenantId: scopedTenantId,
    });

    const elapsed = Date.now() - startTime;

    if (reply) {
      recordLLMCall({
        model: "auto",
        endpoint: "feishu_bot_reply",
        success: true,
        tokensUsed: Math.ceil((systemPrompt.length + text.length + reply.length) / 2),
        responseTimeMs: elapsed,
      });

      // Cache for 10 minutes
      setCache(cacheKey, reply, Math.ceil((systemPrompt.length + text.length) / 2), "auto");
      return { reply, ...retrieval };
    }

    console.warn("[Feishu Bot] LLM reply returned null, using keyword fallback");
    recordLLMCall({
      model: "auto",
      endpoint: "feishu_bot_reply",
      success: false,
      responseTimeMs: elapsed,
    });
    return { reply: keywordReply(text), ...retrieval };
  } catch (err) {
    const elapsed = Date.now() - startTime;
    console.warn("[Feishu Bot] LLM call failed, using keyword fallback:", String(err).slice(0, 100));
    recordLLMCall({
      model: "auto",
      endpoint: "feishu_bot_reply",
      success: false,
      responseTimeMs: elapsed,
    });
    return { reply: keywordReply(text), ...retrieval };
  }
}
