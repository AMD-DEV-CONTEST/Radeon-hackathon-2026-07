/**
 * ReAct 循环测试：工具调用→回喂→最终回答；超限降级；预算超时。
 */
import { config } from "dotenv";
config({ path: ".env.local", override: true });

jest.mock("../supabase", () => ({ supabaseAdmin: null, supabase: null }));

import { runReactLoop } from "../agent/react-loop";
import type { LlmResponse } from "../llm-provider";

function makeAdvanced(sequence: Array<Partial<LlmResponse> & { toolCalls?: LlmResponse["toolCalls"] }>) {
  let i = 0;
  return async () => {
    const step = sequence[Math.min(i, sequence.length - 1)];
    i += 1;
    return {
      content: step.content || "",
      toolCalls: step.toolCalls,
      model: "mock",
      cached: false,
      wasFallback: false,
    } as LlmResponse;
  };
}

describe("runReactLoop", () => {
  it("returns final content when no tool calls", async () => {
    const result = await runReactLoop({
      messages: [{ role: "user", content: "质检这条会话" }],
      callLLMAdvanced: makeAdvanced([{ content: '{"score":90}' }]),
    });
    expect(result.mode).toBe("agent");
    expect(result.content).toBe('{"score":90}');
    expect(result.turns).toBe(1);
    expect(result.toolsUsed).toEqual([]);
  });

  it("executes tool calls then returns final answer", async () => {
    const result = await runReactLoop({
      messages: [{ role: "user", content: "客户要退款，客服说不符合规定" }],
      callLLMAdvanced: makeAdvanced([
        {
          content: "",
          toolCalls: [{ id: "c1", type: "function", function: { name: "scan_compliance", arguments: '{"text":"客户要退款，客服说不符合规定"}' } }],
        },
        { content: '{"decision":"flagged"}' },
      ]),
    });
    expect(result.mode).toBe("agent");
    expect(result.turns).toBe(2);
    expect(result.toolsUsed).toContain("scan_compliance");
    expect(result.traces.length).toBe(1);
    expect(result.traces[0].toolCalls[0].name).toBe("scan_compliance");
  });

  it("falls back to agent-fallback when exceeding maxTurns", async () => {
    const result = await runReactLoop({
      messages: [{ role: "user", content: "x" }],
      maxTurns: 2,
      callLLMAdvanced: makeAdvanced([
        { content: "", toolCalls: [{ id: "c1", type: "function", function: { name: "scan_compliance", arguments: '{"text":"a"}' } }] },
        { content: "", toolCalls: [{ id: "c2", type: "function", function: { name: "scan_compliance", arguments: '{"text":"b"}' } }] },
        { content: '{"ok":true}' },
      ]),
    });
    // maxTurns=2：第 1 轮工具，第 2 轮仍工具 → 超限降级
    expect(result.mode).toBe("agent-fallback");
  });

  it("falls back when LLM throws", async () => {
    const result = await runReactLoop({
      messages: [{ role: "user", content: "x" }],
      callLLMAdvanced: async () => {
        throw new Error("llm down");
      },
    });
    expect(result.mode).toBe("agent-fallback");
  });
});
