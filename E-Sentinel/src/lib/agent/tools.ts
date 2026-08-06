/**
 * 质检 Agent 工具集定义与执行分发。
 *
 * 三个高价值工具：
 * 1. scan_compliance   — 确定性合规扫描（compliance-engine 纯函数）
 * 2. retrieve_knowledge — RAG retrieval 知识检索
 * 3. check_corrections  — 检索历史人工纠错案例（few-shot 学习闭环）
 *
 * 设计原则：工具只做"读 + 确定性计算"，不产生副作用；需要人工动作的
 * （如创建复核任务）由服务端在最终判定后处理，不由 LLM 直接触发。
 */
import type { LlmToolDef } from "../llm-provider";
import { scanCompliance, BUILT_IN_FATAL_PATTERNS } from "../compliance-engine";
import { retrieveRag } from "../rag-client";
import { hybridSearch } from "../hybrid-search";
import { getFewShotExamples } from "../few-shot";
import type { ToolExecutor, ToolResult } from "./types";

// ── 工具执行器 ──────────────────────────────────────────────────────────────

async function scanComplianceTool(args: Record<string, unknown>): Promise<ToolResult> {
  const text = typeof args.text === "string" ? args.text : "";
  if (!text.trim()) return { ok: false, output: null, error: "text 参数缺失" };
  const result = scanCompliance(text, BUILT_IN_FATAL_PATTERNS);
  return { ok: true, output: result };
}

async function retrieveKnowledgeTool(args: Record<string, unknown>): Promise<ToolResult> {
  const query = typeof args.query === "string" ? args.query.trim() : "";
  if (!query) return { ok: false, output: null, error: "query 参数缺失" };
  const intent = typeof args.intent === "string" ? args.intent : "product_qa";
  // C4 三路对照：检索 provider 可切换（QA_RETRIEVAL_PROVIDER=rag|pgvector，默认 rag）。
  // 用于评测同一 Agent 流程在不同检索后端下的端到端质检差异，不改变默认生产行为。
  const provider = (process.env.QA_RETRIEVAL_PROVIDER || "rag").trim().toLowerCase();

  let retrievalMode: string;
  let sources: { title: string; snippet?: string; similarity?: number }[] = [];
  let contextText = "";
  let unavailable = false;
  let noEvidence = true;

  if (provider === "pgvector") {
    const tenant = (process.env.QA_RETRIEVAL_TENANT || "default").trim();
    const h = await hybridSearch(query, { mode: "vector_only", limit: 5, tenantId: tenant });
    retrievalMode = "pgvector-vector_only";
    sources = h.matches.map((m) => ({ title: m.title, snippet: m.content?.slice(0, 240), similarity: m.similarity }));
    contextText = h.matches.map((m) => m.content).join("\n").slice(0, 2000);
    unavailable = h.method === "none";
    noEvidence = h.matches.length === 0;
  } else {
    const result = await retrieveRag(query, intent);
    retrievalMode = result.retrievalMode;
    sources = result.sources.map((s) => ({ title: String(s.title ?? ""), snippet: s.snippet?.slice(0, 240) }));
    contextText = result.contextText.slice(0, 2000);
    unavailable = !result.ok;
    noEvidence = result.ok && result.sources.length === 0;
  }

  // fail-closed 语义：区分"检索服务不可用"（unavailable）和"检索无结果"（noEvidence）。
  // agent 不得在知识不可用/无证据时无依据判定政策/事实违规——应标记需人工复核。
  return {
    ok: true,
    output: {
      retrievalMode,
      sourceCount: sources.length,
      sources,
      contextText,
      unavailable,
      noEvidence,
    },
  };
}

async function checkCorrectionsTool(args: Record<string, unknown>): Promise<ToolResult> {
  const conversation = typeof args.conversation === "string" ? args.conversation : "";
  if (!conversation.trim()) return { ok: false, output: null, error: "conversation 参数缺失" };
  const count = typeof args.count === "number" ? Math.min(Math.max(1, args.count), 5) : 3;
  const { examples, source } = await getFewShotExamples(conversation, { count });
  return {
    ok: true,
    output: {
      source,
      exampleCount: examples.length,
      examples: examples.map((e) => ({
        conversation: String(e.conversation || "").slice(0, 300),
        correctionType: String(e.correction_type || ""),
        humanCorrection: JSON.stringify(e.human_correction || {}).slice(0, 300),
        similarity: Number(e.similarity ?? 0),
      })),
    },
  };
}

// ── 工具注册表 ──────────────────────────────────────────────────────────────

export const AGENT_TOOLS: ToolExecutor[] = [
  {
    name: "scan_compliance",
    description: "对客服会话文本执行确定性合规扫描（广告法红线、违禁词、风险等级），返回命中规则与风险等级",
    parameters: {
      type: "object",
      properties: { text: { type: "string", description: "要扫描的客服会话原文" } },
      required: ["text"],
      additionalProperties: false,
    },
    execute: scanComplianceTool,
  },
  {
    name: "retrieve_knowledge",
    description: "检索企业内部政策/产品知识库，返回带引用的来源片段，用于证据化判定",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "检索问题，如'退款政策是什么'、'产品退换货规则'" },
        intent: { type: "string", enum: ["product_qa", "policy_qa", "wiki_tech"], description: "检索意图，默认 product_qa" },
      },
      required: ["query"],
      additionalProperties: false,
    },
    execute: retrieveKnowledgeTool,
  },
  {
    name: "check_corrections",
    description: "检索历史人工纠错案例（相似会话被如何纠正），用于参考先例避免重复误判",
    parameters: {
      type: "object",
      properties: {
        conversation: { type: "string", description: "当前客服会话文本" },
        count: { type: "integer", minimum: 1, maximum: 5, description: "返回案例数，默认 3" },
      },
      required: ["conversation"],
      additionalProperties: false,
    },
    execute: checkCorrectionsTool,
  },
];

export function toLlmToolDefs(tools: ToolExecutor[] = AGENT_TOOLS): LlmToolDef[] {
  return tools.map((t) => ({
    type: "function" as const,
    function: { name: t.name, description: t.description, parameters: t.parameters },
  }));
}

export async function executeTool(
  name: string,
  argumentsJson: string,
): Promise<ToolResult> {
  const tool = AGENT_TOOLS.find((t) => t.name === name);
  if (!tool) return { ok: false, output: null, error: `未知工具: ${name}` };
  let args: Record<string, unknown> = {};
  // 部分 OpenAI 兼容端点（Ollama 等）直接返回已解析的对象参数；统一字符串化后解析。
  const argsText = typeof argumentsJson === "string" ? argumentsJson : JSON.stringify(argumentsJson);
  try {
    args = argsText ? JSON.parse(argsText) : {};
  } catch {
    return { ok: false, output: null, error: `工具参数不是合法 JSON: ${String(argsText).slice(0, 80)}` };
  }
  try {
    return await tool.execute(args);
  } catch (err) {
    return { ok: false, output: null, error: err instanceof Error ? err.message : "工具执行失败" };
  }
}
