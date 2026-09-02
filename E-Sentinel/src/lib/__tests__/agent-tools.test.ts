/**
 * agent 工具测试：scan_compliance / retrieve_knowledge / check_corrections / executeTool 分发。
 */
import { config } from "dotenv";
config({ path: ".env.local", override: true });

jest.mock("../supabase", () => ({ supabaseAdmin: null, supabase: null }));

// mock RAG 客户端：与真实配置无关，确定性验证 fail-closed 语义。
// 注：rag-client 在模块加载时捕获 env，运行期删 env 无效，必须 mock。
jest.mock("../rag-client", () => ({
  retrieveRag: jest.fn(async () => ({
    ok: false,
    retrievalMode: "none",
    sources: [],
    contextText: "",
  })),
}));

import { executeTool, toLlmToolDefs } from "../agent/tools";

describe("agent tools", () => {
  it("toLlmToolDefs converts to OpenAI schema", () => {
    const defs = toLlmToolDefs();
    expect(defs.length).toBe(3);
    expect(defs[0].function.name).toBe("scan_compliance");
    expect(defs[1].function.name).toBe("retrieve_knowledge");
    expect(defs[2].function.name).toBe("check_corrections");
  });

  it("scan_compliance catches fatal pattern", async () => {
    const result = await executeTool("scan_compliance", JSON.stringify({ text: "我们保证彻底治愈，100%有效" }));
    expect(result.ok).toBe(true);
    const output = result.output as { decision: string; matches: unknown[] };
    expect(output.matches.length).toBeGreaterThan(0);
  });

  it("scan_compliance passes clean text", async () => {
    const result = await executeTool("scan_compliance", JSON.stringify({ text: "您好，我可以帮您查询订单状态" }));
    expect(result.ok).toBe(true);
    const output = result.output as { decision: string };
    expect(output.decision).toBe("passed");
  });

  it("retrieve_knowledge fails closed when RAG unavailable", async () => {
    // mock 返回 ok:false → 工具标记 unavailable，fail-closed 不抛异常
    const result = await executeTool("retrieve_knowledge", JSON.stringify({ query: "退款政策" }));
    expect(result.ok).toBe(true);
    const output = result.output as { unavailable: boolean; sourceCount: number };
    expect(output.unavailable).toBe(true);
    expect(output.sourceCount).toBe(0);
  });

  it("check_corrections returns empty without supabase", async () => {
    const result = await executeTool("check_corrections", JSON.stringify({ conversation: "客户要求退款" }));
    expect(result.ok).toBe(true);
    const output = result.output as { exampleCount: number; source: string };
    expect(output.exampleCount).toBe(0);
  });

  it("unknown tool returns error", async () => {
    const result = await executeTool("not_a_tool", "{}");
    expect(result.ok).toBe(false);
    expect(result.error).toContain("未知工具");
  });

  it("invalid JSON args returns error", async () => {
    const result = await executeTool("scan_compliance", "{bad json");
    expect(result.ok).toBe(false);
  });
});
