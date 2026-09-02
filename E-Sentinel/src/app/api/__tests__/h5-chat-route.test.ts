import { DELETE, POST } from "../v1/9808/conring/robot/chat/route";
import { sendDifyChatMessage } from "@/lib/dify-chat-client";

jest.mock("next/headers", () => ({
  cookies: jest.fn(async () => ({
    get: jest.fn((name: string) => name === "h5_dify_conversation_id" ? { value: "conversation-old" } : undefined),
  })),
}));

jest.mock("@/lib/dify-chat-client", () => ({
  DifyChatError: class DifyChatError extends Error {
    code: string;
    constructor(message: string, code: string) { super(message); this.code = code; }
  },
  sendDifyChatMessage: jest.fn(),
  uploadDifyImage: jest.fn(),
}));

const mockedSend = sendDifyChatMessage as jest.MockedFunction<typeof sendDifyChatMessage>;
const mockedUpload = (jest.requireMock("@/lib/dify-chat-client").uploadDifyImage) as jest.Mock;

function request(body: unknown, headers?: Record<string, string>) {
  return new Request("http://localhost:3000/api/v1/9808/conring/robot/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

describe("H5 ordinary chat route", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedSend.mockResolvedValue({ answer: "已收到", conversationId: "conversation-new", messageId: "message-1" });
    mockedUpload.mockResolvedValue("file-1");
  });

  it("maps the ordinary-mode payload to Dify and sets a conversation cookie", async () => {
    const response = await POST(request({
      visitor_id: "member-001",
      visitor_name: "测试访客",
      content: "你好",
      lang: "cn",
      extra: "product-data",
    }));

    expect(response.status).toBe(200);
    expect(response.headers.get("X-H5-Deployment")).toBe("dify-h5-v1");
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.json()).toEqual(expect.objectContaining({ answer: "已收到", content: "已收到" }));
    expect(response.headers.get("set-cookie")).toContain("h5_dify_conversation_id=conversation-new");
    expect(mockedSend).toHaveBeenCalledWith(expect.objectContaining({
      query: "你好",
      user: "member-001",
      conversationId: "conversation-old",
      inputs: expect.objectContaining({
        channel: "h5",
        visitor_name: "测试访客",
        extra: "product-data",
        routing_hint: "",
        clarification_instruction: "",
      }),
    }));
  });

  it("injects only the structured clarification guard for an exact vague short message", async () => {
    const response = await POST(request({ content: "坏了！" }));

    expect(response.status).toBe(200);
    expect(mockedSend).toHaveBeenCalledWith(expect.objectContaining({
      query: "坏了！",
      inputs: expect.objectContaining({
        channel: "h5",
        routing_hint: "vague_issue_clarification",
        clarification_instruction: expect.stringContaining("先确认具体表现"),
      }),
    }));
  });

  it("does not downgrade a message that already contains diagnostic context", async () => {
    await POST(request({ content: "摄像头坏了，指示灯不亮" }));

    expect(mockedSend).toHaveBeenCalledWith(expect.objectContaining({
      inputs: expect.objectContaining({ routing_hint: "", clarification_instruction: "" }),
    }));
  });

  it("uploads a multipart image and passes the Dify file reference", async () => {
    const form = new FormData();
    form.set("content", "请看看这个指示灯");
    form.set("visitor_id", "member-image");
    form.set("visitor_name", "图片访客");
    form.set("image", new File([new Uint8Array([1, 2, 3])], "led.png", { type: "image/png" }));

    const response = await POST(new Request("http://localhost:3000/api/v1/9808/conring/robot/chat", {
      method: "POST",
      body: form,
    }));

    expect(response.status).toBe(200);
    expect(mockedUpload).toHaveBeenCalledWith(expect.any(File), "member-image");
    expect(mockedSend).toHaveBeenCalledWith(expect.objectContaining({
      query: "请看看这个指示灯",
      files: [{ type: "image", transfer_method: "local_file", upload_file_id: "file-1" }],
      inputs: expect.objectContaining({ has_image: true }),
    }));
  });

  it("rejects an empty or oversized message before calling Dify", async () => {
    expect((await POST(request({ content: " " }))).status).toBe(400);
    expect((await POST(request({ content: "x".repeat(4_001) }))).status).toBe(400);
    expect(mockedSend).not.toHaveBeenCalled();
  });

  it("clears the server-side conversation cookie", async () => {
    const response = await DELETE();
    expect(response.status).toBe(200);
    expect(response.headers.get("X-H5-Deployment")).toBe("dify-h5-v1");
    expect(response.headers.get("set-cookie")).toContain("h5_dify_conversation_id=;");
  });

  it("marks the conversation cookie Secure only for HTTPS requests", async () => {
    const httpResponse = await POST(request({ content: "你好" }));
    expect(httpResponse.headers.get("set-cookie")).not.toContain("Secure");

    const httpsResponse = await POST(new Request("https://example.test/api/v1/9808/conring/robot/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: "你好" }),
    }));
    expect(httpsResponse.headers.get("set-cookie")).toContain("Secure");
  });
});
