/**
 * ReAct 推理循环：规划 → 调工具 → 观察 → 回答。
 *
 * 流程：
 *   1. 调 LLM（advanced + tools, tool_choice=auto）
 *   2. 返回 tool_calls → 执行工具 → 把结果以 role:"tool" 追加回消息 → 继续
 *   3. 无 tool_calls → 得到最终回答（含质检 JSON）
 *   4. 超过 maxTurns 或预算 → 降级返回已积累内容（agent-fallback）
 *
 * 依赖注入 callLLMAdvanced，便于单测 mock。
 */
import type { AgentResult, AgentTurnTrace, ToolResult } from "./types";
import { executeTool, toLlmToolDefs } from "./tools";
import type { LlmRequest, LlmResponse } from "../llm-provider";

export interface ReactLoopOptions {
  messages: Array<{ role: string; content: string }>;
  systemPrompt?: string;
  maxTurns?: number;
  budgetMs?: number;
  timeoutMs?: number;
  tenantId?: string;
  /** 服务端调查策略要求的必调工具（ADR-0003 第 4 层扩展）。
   *  首轮用 tool_choice 精确指定该工具强制执行；工具结果回喂后次轮回到 auto。 */
  requiredTool?: string;
  /** 服务端确定性执行的必调工具结果，在循环开始前注入为 role:"tool" 消息。
   *  用于 AMD 等把 tool_choice 当"偏好"的端点：必调工具由代码执行，不依赖模型自选。 */
  preloadedMessages?: Array<{ role: string; content: string; tool_call_id?: string; name?: string }>;
  callLLMAdvanced?: (req: LlmRequest) => Promise<LlmResponse>;
}

const DEFAULT_MAX_TURNS = 3;
const DEFAULT_BUDGET_MS = 25_000;
const DEFAULT_TIMEOUT_MS = 20_000;

export async function runReactLoop(options: ReactLoopOptions): Promise<AgentResult> {
  const {
    messages,
    systemPrompt,
    maxTurns = DEFAULT_MAX_TURNS,
    budgetMs = DEFAULT_BUDGET_MS,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    tenantId,
    requiredTool,
    preloadedMessages,
    callLLMAdvanced,
  } = options;

  const llm = callLLMAdvanced ?? (async (req) => {
    // 延迟加载避免循环依赖
    const { callLLM } = await import("../llm-provider");
    const res = await callLLM(req as LlmRequest);
    return res as LlmResponse;
  });

  const working: Array<Record<string, unknown>> = [];
  if (systemPrompt) working.push({ role: "system", content: systemPrompt });
  for (const m of messages) working.push({ role: m.role, content: m.content });
  // 服务端确定性执行的必调工具结果，注入为 tool 消息（需带 tool_call_id 才能被部分端点接受）
  for (const pm of preloadedMessages || []) {
    working.push({ role: "tool", content: pm.content, tool_call_id: pm.tool_call_id || `forced_${pm.name || "tool"}`, name: pm.name });
  }

  const traces: AgentTurnTrace[] = [];
  const toolsUsed = new Set<string>();
  const startedAt = Date.now();
  const tools = toLlmToolDefs();

  for (let turn = 0; turn < maxTurns; turn += 1) {
    const elapsed = Date.now() - startedAt;
    if (elapsed >= budgetMs) {
      // 预算超限：返回已积累的最后一轮 content（若有），否则降级
      return {
        content: extractLastAssistantContent(working),
        mode: "agent-fallback",
        turns: turn,
        toolsUsed: [...toolsUsed],
        traces,
      };
    }

    const remainingBudget = budgetMs - elapsed;
    const perTurnTimeout = Math.min(timeoutMs, remainingBudget);

    let response: LlmResponse;
    try {
      // 首轮：服务端策略要求必调工具时，用精确 tool_choice 强制执行（不依赖模型自选）。
      // 工具结果回喂后（turn>=1）回到 auto，模型可补调工具或直接做证据总结。
      const toolChoice = requiredTool && turn === 0
        ? { type: "function" as const, function: { name: requiredTool } }
        : "auto";
      response = await llm({
        messages: working as LlmRequest["messages"],
        tools,
        toolChoice,
        useCache: false,
        timeoutMs: perTurnTimeout,
        tenantId,
      } as LlmRequest);
    } catch (err) {
      // LLM 调用失败 → 降级单次：返回当前积累内容或空
      return {
        content: extractLastAssistantContent(working),
        mode: "agent-fallback",
        turns: turn,
        toolsUsed: [...toolsUsed],
        traces,
      };
    }

    const toolCalls = response.toolCalls ?? [];
    if (toolCalls.length === 0) {
      // 无工具调用 → 最终回答
      return {
        content: response.content,
        mode: "agent",
        turns: turn + 1,
        toolsUsed: [...toolsUsed],
        traces,
      };
    }

    // 执行工具调用
    working.push({
      role: "assistant",
      content: response.content || "",
      tool_calls: toolCalls,
    });

    const toolResults: Array<{ name: string; ok: boolean; summary: string }> = [];
    for (const call of toolCalls) {
      toolsUsed.add(call.function.name);
      const result: ToolResult = await executeTool(call.function.name, call.function.arguments);
      toolResults.push({
        name: call.function.name,
        ok: result.ok,
        summary: summarizeToolResult(result),
      });
      working.push({
        role: "tool",
        content: JSON.stringify(result),
        tool_call_id: call.id,
        name: call.function.name,
      });
    }

    traces.push({
      turn,
      thought: response.content || null,
      toolCalls: toolCalls.map((c) => ({ name: c.function.name, arguments: c.function.arguments })),
      toolResults,
    });
  }

  // 超过 maxTurns：降级
  return {
    content: extractLastAssistantContent(working),
    mode: "agent-fallback",
    turns: maxTurns,
    toolsUsed: [...toolsUsed],
    traces,
  };
}

function extractLastAssistantContent(working: Array<Record<string, unknown>>): string {
  for (let i = working.length - 1; i >= 0; i -= 1) {
    if (working[i].role === "assistant" && typeof working[i].content === "string") {
      return working[i].content as string;
    }
  }
  return "";
}

function summarizeToolResult(result: ToolResult): string {
  if (!result.ok) return result.error || "error";
  const s = JSON.stringify(result.output);
  return s.length > 120 ? `${s.slice(0, 117)}...` : s;
}
