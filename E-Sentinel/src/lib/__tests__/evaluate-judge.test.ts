/**
 * 裁判入口测试：useAgent 开关选择单次或 agent。
 */
import { config } from "dotenv";
config({ path: ".env.local", override: true });

jest.mock("../supabase", () => ({ supabaseAdmin: null, supabase: null }));

import { runJudge } from "../agent/evaluate-judge";

describe("runJudge", () => {
  it("uses single-shot when useAgent is false", async () => {
    const result = await runJudge({
      conversation: "客户投诉",
      systemPrompt: "你是质检员",
      useAgent: false,
      callLLMSimple: async () => '{"score":80}',
    });
    expect(result.mode).toBe("single-shot");
    expect(result.content).toBe('{"score":80}');
  });

  it("uses agent loop when useAgent is true", async () => {
    const result = await runJudge({
      conversation: "客户要退款",
      systemPrompt: "你是质检员",
      useAgent: true,
      callLLMAdvanced: async () => ({ content: '{"score":90}', toolCalls: [] }),
    });
    expect(result.mode).toBe("agent");
    expect(result.content).toBe('{"score":90}');
    expect(result.trace).toBeDefined();
  });
});
