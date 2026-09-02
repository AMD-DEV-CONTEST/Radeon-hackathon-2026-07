import { NextResponse } from "next/server";
import { callLLM } from "@/lib/llm-provider";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SCENE_DESCRIPTIONS: Record<string, string> = {
  pre_sale:
    "售前咨询场景。语气应热情专业、主动介绍产品优势，帮助客户做出购买决策。",
  after_sale:
    "售后问题处理场景。语气应耐心诚恳，以解决问题为导向，安抚客户情绪。",
  after_sales:
    "售后问题处理场景。语气应耐心诚恳，以解决问题为导向，安抚客户情绪。",
  logistics:
    "物流查询场景。语气应简洁高效，提供准确的物流信息，减少客户等待焦虑。",
  complaint:
    "投诉处理场景。语气应谨慎温和，充分表达理解和歉意，积极提出解决方案。",
  general:
    "通用客服场景。语气应友好专业，能够回答各类问题，灵活应对不同需求。",
};

function buildGeneratePrompt(description: string, scene: string): string {
  const sceneDesc = SCENE_DESCRIPTIONS[scene] || SCENE_DESCRIPTIONS.general;
  return `你是一个Prompt工程师。根据用户描述生成一个专业的AI客服系统提示词。

要求：
1. 用中文编写
2. 包含角色定位、语气要求、知识范围、禁止事项
3. 使用 {变量名} 格式标注可替换变量
4. 长度控制在200-500字
5. 语气符合场景：${sceneDesc}

用户描述：${description}

请直接返回生成好的提示词文本，不要加额外说明。`;
}

function extractVariables(text: string): string[] {
  const regex = /\{(\w+)\}/g;
  const seen = new Set<string>();
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    seen.add(match[1]);
  }
  return Array.from(seen);
}

function suggestName(text: string): string {
  // Take first line, strip leading markers, trim to ~20 chars
  const firstLine = text.split("\n")[0] || "";
  const cleaned = firstLine
    .replace(/^[#\s\-*•>]+/, "")
    .replace(/[：:，,。；;！!？?]/g, "")
    .trim();
  if (!cleaned) return "AI 生成提示词";
  return cleaned.length > 20 ? cleaned.slice(0, 20) + "..." : cleaned;
}

// ---------------------------------------------------------------------------
// POST /api/qa/prompts/generate
// ---------------------------------------------------------------------------

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    const { description, scene } = body as {
      description?: string;
      scene?: string;
    };

    if (!description || !description.trim()) {
      return NextResponse.json(
        { error: "description is required" },
        { status: 400 }
      );
    }

    const validScene = SCENE_DESCRIPTIONS[scene || ""] ? scene! : "general";

    const llmPrompt = buildGeneratePrompt(description.trim(), validScene);

    const result = await callLLM({
      messages: [
        { role: "user", content: llmPrompt },
      ],
      temperature: 0.7,
      max_tokens: 2048,
      useCache: false,
    });

    const systemPrompt = result.content.trim();
    const suggestedVariables = extractVariables(systemPrompt);
    const suggestedName = suggestName(systemPrompt);

    return NextResponse.json({
      system_prompt: systemPrompt,
      suggested_variables: suggestedVariables,
      suggested_name: suggestedName,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Prompts] Generate error:", message);

    if (message === "LLM_RATE_LIMITED") {
      return NextResponse.json(
        { error: "请求过于频繁，请稍后重试" },
        { status: 429 }
      );
    }

    return NextResponse.json({ error: message }, { status: 500 });
  }
}
