import { sendGoflyChatMessage } from "../gofly-chat-client";

describe("sendGoflyChatMessage", () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = fetchMock as typeof fetch;
  });

  it("calls the ordinary-mode GoFly endpoint and returns result.content", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      code: 20000,
      msg: "操作成功",
      result: { content: "您好，请描述一下摄像头的问题。" },
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    await expect(sendGoflyChatMessage({
      visitorId: "member-001",
      visitorName: "测试访客",
      content: "你好",
      lang: "cn",
      extra: "product-data",
    })).resolves.toBe("您好，请描述一下摄像头的问题。");

    expect(fetchMock).toHaveBeenCalledWith(
      "https://gofly.v1kf.com/api/v1/9808/conring/robot/chat",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"visitor_id":"member-001"'),
      }),
    );
  });

  it("normalizes non-success GoFly responses", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      code: 50000,
      msg: "error",
    }), { status: 200 }));

    await expect(sendGoflyChatMessage({
      visitorId: "member-001",
      visitorName: "测试访客",
      content: "你好",
    })).rejects.toMatchObject({ code: "invalid_response" });
  });
});
