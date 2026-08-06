import { afterEach, describe, expect, it, vi } from "vitest";
import request from "supertest";
import type { Express } from "express";
import { createApp, createAppContext, type AppContext } from "./app.js";
import {
  MAX_IMAGE_BYTES,
  MediaIntakeService,
  type IntakeTelemetry
} from "./intake-service.js";
import { mockAgentTestConfig } from "./runtime-config.js";

const PNG_BYTES = Buffer.from([
  137, 80, 78, 71, 13, 10, 26, 10,
  0, 0, 0, 0
]);

describe("media intake API", () => {
  afterEach(() => {
    activeContext?.domain.close();
    activeContext = null;
  });

  it("returns a structured inventory draft for a valid image", async () => {
    const fetchImpl = fakeModelFetch(
      JSON.stringify({
        items: [
          {
            rawName: "北豆腐",
            quantity: 2,
            unit: "盒",
            packageSize: null,
            confidence: "medium",
            evidence: "照片中可见两个相似包装"
          }
        ],
        limitations: ["无法确认包装背面的净含量"]
      })
    );
    const telemetry: IntakeTelemetry[] = [];
    const app = await makeApp(fetchImpl, telemetry);
    const imageDataUrl = dataUrl("image/png", PNG_BYTES);

    const response = await request(app)
      .post("/api/intake/inventory-image")
      .send({ imageDataUrl });

    expect(response.status).toBe(200);
    expect(response.body).toEqual({
      items: [
        {
          id: "draft-1",
          rawName: "北豆腐",
          quantity: 2,
          unit: "盒",
          packageSize: null,
          confidence: "medium",
          evidence: "照片中可见两个相似包装"
        }
      ],
      limitations: ["无法确认包装背面的净含量"]
    });

    const body = JSON.parse(
      String(fetchImpl.mock.calls[0]?.[1]?.body ?? "{}")
    ) as {
      messages: Array<{ content: Array<Record<string, unknown>> }>;
    };
    expect(body.messages[0]?.content[1]).toMatchObject({
      type: "image_url"
    });
    expect(telemetry.some((event) => event.kind === "vision_intake")).toBe(true);
    expect(JSON.stringify(telemetry)).not.toContain(imageDataUrl);
  });

  it("rejects unsupported image MIME types", async () => {
    const fetchImpl = fakeModelFetch("{}");
    const app = await makeApp(fetchImpl);

    const response = await request(app)
      .post("/api/intake/inventory-image")
      .send({ imageDataUrl: dataUrl("image/gif", Buffer.from("gif")) });

    expect(response.status).toBe(400);
    expect(response.body.code).toBe("INVALID_MEDIA");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects an image over the size limit", async () => {
    const fetchImpl = fakeModelFetch("{}");
    const app = await makeApp(fetchImpl);
    const tooLarge = Buffer.concat([PNG_BYTES, Buffer.alloc(MAX_IMAGE_BYTES)]);

    const response = await request(app)
      .post("/api/intake/inventory-image")
      .send({ imageDataUrl: dataUrl("image/png", tooLarge) });

    expect(response.status).toBe(413);
    expect(response.body.code).toBe("MEDIA_TOO_LARGE");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("fails closed when the vision model returns an invalid structure", async () => {
    const fetchImpl = fakeModelFetch("我看到了一些食物，但无法确定。");
    const app = await makeApp(fetchImpl);

    const response = await request(app)
      .post("/api/intake/inventory-image")
      .send({ imageDataUrl: dataUrl("image/png", PNG_BYTES) });

    expect(response.status).toBe(502);
    expect(response.body.code).toBe("MODEL_RESPONSE_INVALID");
  });

  it("reports a multimodal service outage without guessing", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new Error("connection refused");
    });
    const app = await makeApp(fetchImpl);

    const response = await request(app)
      .post("/api/intake/inventory-image")
      .send({ imageDataUrl: dataUrl("image/png", PNG_BYTES) });

    expect(response.status).toBe(503);
    expect(response.body.code).toBe("INTAKE_UNAVAILABLE");
    expect(response.body.items).toBeUndefined();
  });

  it("returns a transcript for a valid audio request", async () => {
    const fetchImpl = fakeModelFetch(
      JSON.stringify({ transcript: "今晚用冰箱里的豆腐做晚饭" })
    );
    const telemetry: IntakeTelemetry[] = [];
    const app = await makeApp(fetchImpl, telemetry);
    const audioDataUrl = dataUrl("audio/webm", Buffer.from("browser-audio"));

    const response = await request(app)
      .post("/api/intake/audio-transcription")
      .send({ audioDataUrl, format: "webm", durationMs: 2_700 });

    expect(response.status).toBe(200);
    expect(response.body).toEqual({
      transcript: "今晚用冰箱里的豆腐做晚饭"
    });
    expect(telemetry.some((event) => event.kind === "audio_intake")).toBe(true);
    const body = JSON.parse(
      String(fetchImpl.mock.calls[0]?.[1]?.body ?? "{}")
    ) as {
      messages: Array<{ content: Array<Record<string, unknown>> }>;
    };
    expect(body.messages[0]?.content[1]).toMatchObject({
      type: "audio_url"
    });
    expect(JSON.stringify(telemetry)).not.toContain(audioDataUrl);
  });

  it("reports vLLM audio support as unavailable without inventing a transcript", async () => {
    const fetchImpl = fakeModelFetch(
      "Please install vllm[audio] for audio support",
      500
    );
    const app = await makeApp(fetchImpl);

    const response = await request(app)
      .post("/api/intake/audio-transcription")
      .send({
        audioDataUrl: dataUrl("audio/webm", Buffer.from("browser-audio")),
        format: "webm",
        durationMs: 2_700
      });

    expect(response.status).toBe(503);
    expect(response.body).toEqual({
      code: "INTAKE_UNAVAILABLE",
      message: "当前环境暂不支持音频转写：远端 vLLM 缺少音频依赖。"
    });
    expect(response.body.transcript).toBeUndefined();
  });

  it("returns an empty transcript when the model says it cannot hear the audio", async () => {
    const fetchImpl = fakeModelFetch(
      JSON.stringify({ transcript: "I'm sorry, I can't hear you." })
    );
    const app = await makeApp(fetchImpl);

    const response = await request(app)
      .post("/api/intake/audio-transcription")
      .send({
        audioDataUrl: dataUrl("audio/wav", Buffer.from("browser-audio")),
        format: "wav",
        durationMs: 2_700
      });

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ transcript: "" });
  });

  it("returns an empty transcript when the model refuses the audio request", async () => {
    const fetchImpl = fakeModelFetch(
      JSON.stringify({ transcript: "I'm sorry, I can't do that." })
    );
    const app = await makeApp(fetchImpl);

    const response = await request(app)
      .post("/api/intake/audio-transcription")
      .send({
        audioDataUrl: dataUrl("audio/wav", Buffer.from("browser-audio")),
        format: "wav",
        durationMs: 2_700
      });

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ transcript: "" });
  });

  it("rejects an unsupported audio format", async () => {
    const fetchImpl = fakeModelFetch("{}");
    const app = await makeApp(fetchImpl);

    const response = await request(app)
      .post("/api/intake/audio-transcription")
      .send({
        audioDataUrl: dataUrl("audio/flac", Buffer.from("audio")),
        format: "flac",
        durationMs: 1_000
      });

    expect(response.status).toBe(400);
    expect(response.body.code).toBe("VALIDATION_ERROR");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("does not call Agent tools, write inventory, or create confirmation", async () => {
    const fetchImpl = fakeModelFetch(
      JSON.stringify({ items: [], limitations: ["不是食品照片"] })
    );
    const app = await makeApp(fetchImpl);
    const runSpy = vi.spyOn(activeContext!.sessions, "run");
    const before = activeContext!.domain.getMealContext();

    const response = await request(app)
      .post("/api/intake/inventory-image")
      .set("X-PrivatePlate-Session", "intake-isolation")
      .send({ imageDataUrl: dataUrl("image/png", PNG_BYTES) });

    const after = activeContext!.domain.getMealContext();
    expect(response.status).toBe(200);
    expect(runSpy).not.toHaveBeenCalled();
    expect(after.inventoryVersion).toBe(before.inventoryVersion);
    expect(after.inventory).toEqual(before.inventory);
    expect(
      activeContext!.sessions.getState("intake-isolation").pendingActionId
    ).toBeNull();
  });
});

let activeContext: AppContext | null = null;

async function makeApp(
  fetchImpl: typeof fetch,
  telemetry: IntakeTelemetry[] = []
): Promise<Express> {
  const config = mockAgentTestConfig();
  const intake = new MediaIntakeService({
    baseUrl: config.baseUrl,
    model: config.model,
    fetchImpl,
    logger: (event) => telemetry.push(event)
  });
  activeContext = await createAppContext({ config, intake });
  return createApp(activeContext);
}

function fakeModelFetch(content: string, status = 200) {
  return vi.fn<typeof fetch>(async () =>
    new Response(
      JSON.stringify(
        status >= 400
          ? { error: { message: content } }
          : {
              id: "intake-test",
              model: "test-model",
              choices: [
                {
                  message: { content },
                  finish_reason: "stop"
                }
              ]
            }
      ),
      {
        status,
        headers: { "Content-Type": "application/json" }
      }
    )
  );
}

function dataUrl(mimeType: string, bytes: Buffer): string {
  return `data:${mimeType};base64,${bytes.toString("base64")}`;
}
