import { describe, expect, it, vi } from "vitest";

import {
  HttpDigitalEmployeeDataSource,
} from "./HttpDigitalEmployeeDataSource";

const eventId = `event_${"c".repeat(32)}`;
const responsePayload = [
  {
    id: "maintenance_001",
    name: "Equipment Maintenance",
    status: "working",
    current_event_id: eventId,
    responsibility: "Equipment Maintenance",
    skills: [{ name: "restaurant-aircon-shutdown" }],
  },
] as const;

function jsonResponse(
  value: unknown,
  status = 200,
): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HttpDigitalEmployeeDataSource", () => {
  it("uses one bounded relative GET and returns an HTTP collection", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(jsonResponse(responsePayload));
    const source = new HttpDigitalEmployeeDataSource(fetcher);

    expect(source.source).toBe("http");
    expect(source.getInitialCollection()).toBeNull();
    const collection = await source.getEmployees();

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/digital-employees",
      {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: undefined,
      },
    );
    expect(collection.source).toBe("http");
    expect(collection.employees[0]).toMatchObject({
      id: "maintenance_001",
      status: "working",
      currentEventId: eventId,
      currentTasks: [],
    });
    expect(
      collection.employees.some(
        ({ id }) => id === "equipment-maintenance",
      ),
    ).toBe(false);
  });

  it("returns the real empty projection without a Mock fallback", async () => {
    const source = new HttpDigitalEmployeeDataSource(
      vi.fn().mockResolvedValue(jsonResponse([])),
    );

    await expect(source.getEmployees()).resolves.toMatchObject({
      source: "http",
      employees: [],
    });
  });

  it("reports pre-aborted and in-flight aborted reads", async () => {
    const preAbortedFetcher = vi.fn();
    const preAbortedSource = new HttpDigitalEmployeeDataSource(
      preAbortedFetcher,
    );
    const preAbortedController = new AbortController();
    preAbortedController.abort();

    await expect(
      preAbortedSource.getEmployees({
        signal: preAbortedController.signal,
      }),
    ).rejects.toMatchObject({
      code: "aborted",
      source: "http",
    });
    expect(preAbortedFetcher).not.toHaveBeenCalled();

    const inFlightFetcher = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    );
    const inFlightSource = new HttpDigitalEmployeeDataSource(
      inFlightFetcher,
    );
    const inFlightController = new AbortController();
    const read = inFlightSource.getEmployees({
      signal: inFlightController.signal,
    });
    inFlightController.abort();

    await expect(read).rejects.toMatchObject({
      code: "aborted",
      source: "http",
    });
  });

  it("normalizes transport, HTTP, JSON, and response-contract failures", async () => {
    const transport = new HttpDigitalEmployeeDataSource(
      vi.fn().mockRejectedValue(new TypeError("offline")),
    );
    await expect(transport.getEmployees()).rejects.toMatchObject({
      code: "transport",
      source: "http",
    });

    const unavailable = new HttpDigitalEmployeeDataSource(
      vi.fn().mockResolvedValue(jsonResponse({}, 503)),
    );
    await expect(unavailable.getEmployees()).rejects.toMatchObject({
      code: "unavailable",
      source: "http",
    });

    const invalidJson = new HttpDigitalEmployeeDataSource(
      vi.fn().mockResolvedValue(
        new Response("{", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(invalidJson.getEmployees()).rejects.toMatchObject({
      code: "contract",
      source: "http",
      message:
        "Digital employee projection returned invalid JSON.",
    });

    const invalidContract = new HttpDigitalEmployeeDataSource(
      vi.fn().mockResolvedValue(
        jsonResponse([{ ...responsePayload[0], status: "online" }]),
      ),
    );
    await expect(
      invalidContract.getEmployees(),
    ).rejects.toMatchObject({
      code: "contract",
      source: "http",
      message:
        "Digital employee projection did not match the contract.",
    });
  });
});
