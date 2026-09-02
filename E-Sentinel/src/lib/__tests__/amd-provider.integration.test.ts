/**
 * AMD Radeon provider 集成验证（真实调用 AMD API）。
 * 仅在配置了 AMD_API_KEY 时执行 live 调用；未配置则跳过。
 */
import { config } from "dotenv";
config({ path: ".env.local", override: true });

// mock supabase：模拟无 DB provider，让 AMD env 兜底生效
jest.mock("../supabase", () => ({ supabaseAdmin: null, supabase: null }));

// 强制走 AMD：QA_LLM_PROVIDER=amd 时 resolveProviderChain 只保留 AMD Radeon 端点，
// 确保该集成测试真正验证 AMD，而不是被默认链上的 DeepSeek/Moonshot 拦截。
process.env.QA_LLM_PROVIDER = "amd";

import { callLLM } from "../llm-provider";

describe("AMD Radeon provider integration", () => {
  it(
    "calls AMD Qwen and returns non-empty content",
    async () => {
      const key = process.env.AMD_API_KEY;
      if (!key) {
        console.warn("AMD_API_KEY not set, skipping live call");
        return;
      }
      const content = await callLLM({
        prompt: "用一句话说：AMD Radeon GPU 上的本地推理是什么？",
        systemPrompt: "你是 E-Sentinel 质检助手，回答简洁。",
        useCache: false,
        timeoutMs: 45000,
      });
      console.log("AMD content:", JSON.stringify(content));
      expect(content).toBeTruthy();
      expect(typeof content).toBe("string");
      expect((content as string).length).toBeGreaterThan(5);
    },
    60000
  );
});
