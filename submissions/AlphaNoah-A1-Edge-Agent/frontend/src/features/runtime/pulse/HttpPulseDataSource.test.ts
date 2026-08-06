import { describe, expect, it, vi } from "vitest";

import { HttpPulseDataSource } from "./HttpPulseDataSource";
import { PulseReadError } from "./pulseDataSource";

const eventId = "event_0123456789abcdef0123456789abcdef";

describe("HttpPulseDataSource", () => {
  it("reads GET /api/pulse and maps its safe projection", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          level: "attention",
          title: "Equipment exception requires review",
          event_id: eventId,
        }),
        { status: 200 },
      ),
    );
    const source = new HttpPulseDataSource(fetcher);

    const notice = await source.getPulse();

    expect(fetcher).toHaveBeenCalledWith(
      "/api/pulse",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        headers: { Accept: "application/json" },
      }),
    );
    expect(notice?.kind).toBe("attention");
    expect(notice?.eventId).toBe(eventId);
  });

  it("returns null only when the API confirms there is no notice", async () => {
    const source = new HttpPulseDataSource(
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          new Response("null", { status: 200 }),
        ),
    );

    await expect(source.getPulse()).resolves.toBeNull();
  });

  it("returns typed unavailable and contract errors without response details", async () => {
    const unavailable = new HttpPulseDataSource(
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          new Response("private upstream response", {
            status: 503,
          }),
        ),
    );
    const invalid = new HttpPulseDataSource(
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              level: "attention",
              title: "Review required",
              event_id: eventId,
              prompt: "private prompt",
            }),
            { status: 200 },
          ),
        ),
    );

    await expect(unavailable.getPulse()).rejects.toMatchObject({
      name: "PulseReadError",
      code: "unavailable",
      status: 503,
      message: "Runtime Pulse request was rejected.",
    });
    await expect(invalid.getPulse()).rejects.toMatchObject({
      name: "PulseReadError",
      code: "contract",
      message:
        "Runtime Pulse response did not match the projection contract.",
    });
  });

  it("normalizes transport and abort failures", async () => {
    const transport = new HttpPulseDataSource(
      vi
        .fn<typeof fetch>()
        .mockRejectedValue(new Error("private network detail")),
    );
    const controller = new AbortController();
    controller.abort();

    await expect(transport.getPulse()).rejects.toBeInstanceOf(
      PulseReadError,
    );
    await expect(
      transport.getPulse({ signal: controller.signal }),
    ).rejects.toMatchObject({ code: "aborted" });
  });
});
