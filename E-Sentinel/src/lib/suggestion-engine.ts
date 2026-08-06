// ============================================================================
// LLM-powered suggestion engine — general-purpose suggestion generator.
// Now uses unified callLLM from llm-provider.
// ============================================================================

import { callLLM } from "./llm-provider";
import { createCorrelationId } from "./correlation";

interface SuggestionInput {
  context_type: string;
  context_data: unknown;
  question: string;
  max_tokens?: number;
}

/**
 * General-purpose LLM suggestion endpoint wrapper.
 * Used by: bot config suggestion, knowledge gap analysis, optimization planning.
 */
export async function callLLMForSuggestion(input: SuggestionInput): Promise<{
  suggestion: string;
  confidence: number;
}> {
  const systemPrompt = `你是电商客服机器人运营专家。请根据提供的上下文数据回答用户问题，给出具体、可执行的建议。

输出纯 JSON，不要包裹 markdown 代码块：
{
  "suggestion": "string (具体建议，200字以内)",
  "confidence": 0.0-1.0 (你对该建议的信心度)
}`;

  const userMessage = `上下文数据：\n${JSON.stringify(input.context_data, null, 2)}\n\n问题：${input.question}`;

  const content = await callLLM({
    prompt: userMessage,
    systemPrompt,
    temperature: 0.1,
    maxTokens: input.max_tokens || 1024,
  });

  if (!content) return { suggestion: "LLM 调用失败,请稍后重试", confidence: 0 };

  const parsed = parseSuggestionJSON(content);
  return {
    suggestion: String(parsed.suggestion || "无法生成建议"),
    confidence: typeof parsed.confidence === "number" ? parsed.confidence : 0.5,
  };
}

function parseSuggestionJSON(content: string): Record<string, unknown> {
  const raw = content.replace(/```json\s*/gi, "").replace(/```\s*/gi, "").trim();
  const objStart = raw.indexOf("{");
  const objEnd = raw.lastIndexOf("}");
  if (objStart !== -1 && objEnd !== -1 && objEnd > objStart) {
    try {
      return JSON.parse(raw.substring(objStart, objEnd + 1));
    } catch {
      // fall through
    }
  }
  return { suggestion: raw.slice(0, 500), confidence: 0.3 };
}

export function generateTraceId(prefix: string = "qa"): string {
  return createCorrelationId().replace(/^qa_/, `${prefix}_`);
}
