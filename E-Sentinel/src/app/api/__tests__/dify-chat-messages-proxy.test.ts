import { POST } from "../dify-chat-messages/route";
import { POST as COMPAT_POST } from "../../v1/chat-messages/route";

describe("Dify GoFly compatibility proxy", () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = fetchMock as typeof fetch;
    process.env.H5_DIFY_DIRECT_URL = "http://172.18.0.11:5001/v1";
  });

  afterEach(() => {
    delete process.env.H5_DIFY_DIRECT_URL;
  });

  it("exposes the same handler at the standard Dify chat-messages path", () => {
    expect(COMPAT_POST).toBe(POST);
  });

  it("converts GoFly img markers into Dify files", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("image-bytes", { status: 200, headers: { "Content-Type": "image/jpeg" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "file-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ answer: "图片中是摄像头。" }), { status: 200, headers: { "Content-Type": "application/json" } }));

    const response = await POST(new Request("http://localhost/api/dify-chat-messages", {
      method: "POST",
      headers: { Authorization: "Bearer app-test-key", "Content-Type": "application/json" },
      body: JSON.stringify({ query: "img[https://goflychat.oss-cn-hangzhou.aliyuncs.com/static/camera.jpg]", user: "visitor-1", response_mode: "blocking" }),
    }));

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const uploadBody = fetchMock.mock.calls[1][1].body as FormData;
    expect(uploadBody.get("user")).toBe("visitor-1");
    const chatBody = JSON.parse(fetchMock.mock.calls[2][1].body as string);
    expect(chatBody.response_mode).toBe("blocking");
    expect(chatBody.query).toContain("只描述");
    expect(chatBody.files).toEqual([{ type: "image", transfer_method: "local_file", upload_file_id: "file-1" }]);
    expect(chatBody.inputs).toEqual(expect.objectContaining({
      channel: "h5",
      has_image: true,
      routing_hint: "",
      clarification_instruction: "",
    }));
  });

  it("rejects image URLs outside GoFly storage", async () => {
    const response = await POST(new Request("http://localhost/api/dify-chat-messages", {
      method: "POST",
      headers: { Authorization: "Bearer app-test-key", "Content-Type": "application/json" },
      body: JSON.stringify({ query: "img[https://example.com/image.jpg]", user: "visitor-1" }),
    }));

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("adds a no-image boundary to text-only turns", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ answer: "好的" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));

    const response = await POST(new Request("http://localhost/api/dify-chat-messages", {
      method: "POST",
      headers: { Authorization: "Bearer app-test-key", "Content-Type": "application/json" },
      body: JSON.stringify({ query: "设备为什么离线？", user: "visitor-1", conversation_id: "conversation-1" }),
    }));

    expect(response.status).toBe(200);
    const chatBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(chatBody.query).toContain("本轮没有附带图片");
    expect(chatBody.query).toContain("设备为什么离线？");
    expect(chatBody.conversation_id).toBe("conversation-1");
    expect(chatBody.inputs.has_image).toBe(false);
  });

  it("preserves streaming mode for GoFly native requests", async () => {
    fetchMock.mockResolvedValueOnce(new Response('data: {"event":"message_end"}\n\n', {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }));

    const response = await POST(new Request("http://localhost/api/dify-chat-messages", {
      method: "POST",
      headers: { Authorization: "Bearer app-test-key", "Content-Type": "application/json" },
      body: JSON.stringify({
        query: "你好",
        user: "visitor-1",
        visitor_id: "member-001",
        visitor_name: "测试访客",
        lang: "cn",
        avator: "https://example.com/avatar.jpg",
        extra: "product-data",
        response_mode: "streaming",
      }),
    }));

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    const chatBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(chatBody.response_mode).toBe("streaming");
    expect(chatBody.inputs).toEqual(expect.objectContaining({
      channel: "h5",
      visitor_id: "member-001",
      visitor_name: "测试访客",
      lang: "cn",
      avator: "https://example.com/avatar.jpg",
      extra: "product-data",
    }));
  });

  it("injects the exact-match clarification inputs for vague short replies", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ answer: "请说明具体是哪一项。" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));

    await POST(new Request("http://localhost/api/dify-chat-messages", {
      method: "POST",
      headers: { Authorization: "Bearer app-test-key", "Content-Type": "application/json" },
      body: JSON.stringify({ query: "坏了！", user: "visitor-1", conversation_id: "conversation-1" }),
    }));

    const chatBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(chatBody.inputs).toEqual(expect.objectContaining({
      channel: "h5",
      routing_hint: "vague_issue_clarification",
      clarification_instruction: expect.stringContaining("先确认具体表现"),
    }));
    expect(chatBody.query).toContain("用户本轮消息：坏了！");
  });

  it("clears the clarification inputs for a concrete message", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ answer: "好的" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));

    await POST(new Request("http://localhost/api/dify-chat-messages", {
      method: "POST",
      headers: { Authorization: "Bearer app-test-key", "Content-Type": "application/json" },
      body: JSON.stringify({ query: "摄像头坏了，指示灯不亮", user: "visitor-1" }),
    }));

    const chatBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(chatBody.inputs).toEqual(expect.objectContaining({ routing_hint: "", clarification_instruction: "" }));
  });
});
