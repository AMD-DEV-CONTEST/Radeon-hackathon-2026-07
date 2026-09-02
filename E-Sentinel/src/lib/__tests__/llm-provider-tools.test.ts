/**
 * llm-provider function calling 支持测试。
 * mock fetch + mock supabase（无 DB provider → env 兜底），验证：
 * 1. 请求体含 tools / tool_choice
 * 2. 解析 tool_calls 返回
 * 3. 无 tools 向后兼容（content 正常返回）
 */
import { config } from "dotenv";
config({ path: ".env.local", override: true });

jest.mock("../supabase", () => ({ supabaseAdmin: null, supabase: null }));

import { callLLM } from "../llm-provider";

// 用 AMD env 兜底（避免依赖真实 key——mock fetch 拦截，不发真实请求）
process.env.AMD_API_KEY = "test-key";
process.env.DEEPSEEK_API_KEY = "";
process.env.MOONSHOT_API_KEY = "";

const TOOLS = [
  {
    type: "function" as const,
    function: {
      name: "retrieve_policy",
      description: "检索企业质检政策",
      parameters: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
    },
  },
];

function mockFetchOnce(body: Record<string, unknown>) {
  (global as any).fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ choices: [{ message: body }] }),
  });
}

describe("llm-provider function calling", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("passes tools and tool_choice in request body", async () => {
    mockFetchOnce({ content: "ok", tool_calls: [] });
    const result = await callLLM({
      messages: [{ role: "user", content: "hi" }],
      tools: TOOLS,
      toolChoice: "auto",
      useCache: false,
    });
    expect(result).toHaveProperty("content", "ok");
    // 验证请求体
    const fetchMock = (global as any).fetch as jest.Mock;
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.tools).toEqual(TOOLS);
    expect(body.tool_choice).toBe("auto");
  });

  it("parses tool_calls from response", async () => {
    mockFetchOnce({
      content: null,
      tool_calls: [{ id: "call_1", type: "function", function: { name: "retrieve_policy", arguments: '{"query":"退款"}' } }],
    });
    const result = await callLLM({
      messages: [{ role: "user", content: "check this conversation" }],
      tools: TOOLS,
      useCache: false,
    });
    expect(result.content).toBe(""); // content 为 null → 空字符串
    expect((result as any).toolCalls).toHaveLength(1);
    expect((result as any).toolCalls[0].function.name).toBe("retrieve_policy");
  });

  it("remains backward compatible without tools", async () => {
    mockFetchOnce({ content: "普通回答", tool_calls: [] });
    const result = await callLLM({
      messages: [{ role: "user", content: "hello" }],
      useCache: false,
    });
    expect(result.content).toBe("普通回答");
    expect((result as any).toolCalls).toBeUndefined();
  });
});
