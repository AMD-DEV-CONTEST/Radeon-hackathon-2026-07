import { DifyChatError, sendDifyChatMessage, uploadDifyImage } from "../dify-chat-client";

describe("sendDifyChatMessage", () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = fetchMock as typeof fetch;
    process.env.H5_DIFY_BASE_URL = "http://62.234.28.57/v1";
    process.env.H5_DIFY_API_KEY = "app-test-key";
  });

  afterEach(() => {
    delete process.env.H5_DIFY_BASE_URL;
    delete process.env.H5_DIFY_API_KEY;
  });

  it("sends a blocking request and normalizes the response", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      answer: "请检查设备电源。",
      conversation_id: "conversation-1",
      message_id: "message-1",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    await expect(sendDifyChatMessage({
      query: "摄像头离线了",
      user: "member-1",
      inputs: { channel: "h5", lang: "cn" },
    })).resolves.toEqual({
      answer: "请检查设备电源。",
      conversationId: "conversation-1",
      messageId: "message-1",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://62.234.28.57/v1/chat-messages",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer app-test-key" }),
        body: expect.stringContaining('"response_mode":"blocking"'),
      }),
    );
  });

  it("uploads an image without exposing the API key in multipart headers", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ id: "file-1" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));

    const id = await uploadDifyImage(new File([new Uint8Array([1, 2, 3])], "camera.png", { type: "image/png" }), "member-1");

    expect(id).toBe("file-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://62.234.28.57/v1/files/upload",
      expect.objectContaining({
        method: "POST",
        headers: { Authorization: "Bearer app-test-key" },
        body: expect.any(FormData),
      }),
    );
  });

  it("fails closed when server configuration is missing", async () => {
    delete process.env.H5_DIFY_API_KEY;
    await expect(sendDifyChatMessage({ query: "hello", user: "member-1" })).rejects.toMatchObject({ code: "config" } satisfies Partial<DifyChatError>);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not expose upstream response details", async () => {
    fetchMock.mockResolvedValue(new Response("internal key details", { status: 401 }));
    await expect(sendDifyChatMessage({ query: "hello", user: "member-1" })).rejects.toMatchObject({
      code: "upstream",
      message: "Dify returned HTTP 401",
    });
  });
});
