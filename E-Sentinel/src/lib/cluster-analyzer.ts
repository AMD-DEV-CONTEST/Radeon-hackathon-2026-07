// ============================================================================
// LLM-powered cluster analyzer — groups user queries into semantic clusters.
// Now uses unified callLLM from llm-provider.
// ============================================================================

import { callLLM } from "./llm-provider";

export interface ClusterInput {
  session_id: string;
  user_questions: string[];
}

export interface ClusterOutput {
  clusters: {
    topic: string;
    count: number;
    examples: string[];
    suggestion: string;
  }[];
}

/**
 * LLM-based user query clustering.
 * Groups user questions across sessions into semantic topic clusters
 * with human-readable labels and optimization suggestions.
 */
export async function clusterUserQueries(
  sessions: ClusterInput[],
  clusterCount: number = 8
): Promise<ClusterOutput> {
  const allQuestions = sessions.flatMap((s) => s.user_questions).filter(Boolean);
  if (allQuestions.length === 0) return { clusters: [] };

  const systemPrompt = `你是电商客服机器人运营专家。请对用户提问进行语义聚类分析。

规则：
1. 将相似语义的问题归入同一主题簇
2. 每个簇的 topic 应为简洁的中文标签（如"退差价问题"、"物流催单"、"优惠券不生效"）
3. 对每个簇给出 3 条代表性原句作为 examples
4. 对每个簇给出优化建议 suggestion（如何通过话术/知识库优化减少此类问题）

输出纯 JSON 数组，不要包裹 markdown 代码块：
[
  {
    "topic": "string",
    "count": number,
    "examples": ["string", "string", "string"],
    "suggestion": "string"
  }
]`;

  const userMessage = `请将以下 ${allQuestions.length} 条用户提问聚类为约 ${clusterCount} 个主题：\n${allQuestions.map((q, i) => `${i + 1}. ${q}`).join("\n")}`;

  const content = await callLLM({
    prompt: userMessage,
    systemPrompt,
    temperature: 0.1,
    maxTokens: 4096,
  });

  if (!content) return { clusters: [] };

  const clusters = parseClusterJSON(content);
  return { clusters };
}

function parseClusterJSON(content: string): ClusterOutput["clusters"] {
  const raw = content.replace(/```json\s*/gi, "").replace(/```\s*/gi, "").trim();
  const arrStart = raw.indexOf("[");
  const arrEnd = raw.lastIndexOf("]");
  if (arrStart !== -1 && arrEnd !== -1 && arrEnd > arrStart) {
    try {
      return JSON.parse(raw.substring(arrStart, arrEnd + 1));
    } catch {
      // fall through
    }
  }
  return [];
}
