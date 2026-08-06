import { describe, expect, it, vi } from "vitest";

import { mockActivationResponse } from "../mock/mockActivationResponse";
import { HttpActivationDataSource } from "./HttpActivationDataSource";

describe("HttpActivationDataSource", () => {
  it("uses only relative bounded POST and GET activation routes", async () => {
    const fetcher = vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify(mockActivationResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const source = new HttpActivationDataSource(fetcher);

    await source.activate({
      description: "Synthetic incident.",
      requestId: "activation-test-1",
    });
    await source.getEvent(mockActivationResponse.event.event_id);

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/demo/events",
      expect.objectContaining({ method: "POST" }),
    );
    expect(
      JSON.parse(
        String(fetcher.mock.calls[0]?.[1]?.body),
      ),
    ).toEqual({
      scenario_id: "synthetic-restaurant-aircon-a08",
      description: "Synthetic incident.",
      request_id: "activation-test-1",
    });
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      `/api/demo/events/${mockActivationResponse.event.event_id}`,
      expect.objectContaining({ method: "GET" }),
    );
  });
});
