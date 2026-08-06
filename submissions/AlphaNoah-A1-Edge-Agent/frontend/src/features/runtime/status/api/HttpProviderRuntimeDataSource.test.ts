import { describe, expect, it, vi } from "vitest";

import { ProviderRuntimeReadError } from "../models/providerRuntime";
import { HttpProviderRuntimeDataSource } from "./HttpProviderRuntimeDataSource";
import { decodeProviderRuntimeStatus } from "./providerRuntimeApiDecoder";

const readyPayload = {
  version: "runtime-status-v1",
  status: "ready",
  provider: "ollama",
  model: "qwen3.5:9b",
  execution: "local",
  selection_source: "environment",
  health: "healthy",
} as const;

describe("Provider Runtime HTTP boundary", () => {
  it("decodes runtime-status-v1 and maps a ready local Provider", async () => {
    const fetcher = vi.fn(async () => jsonResponse(readyPayload));
    const dataSource = new HttpProviderRuntimeDataSource(fetcher);

    await expect(dataSource.getRuntimeStatus()).resolves.toMatchObject({
      source: "http",
      visibility: "ready",
      runtimeStatus: "ready",
      provider: "ollama",
      model: "qwen3.5:9b",
      execution: "local",
      selectionSource: "environment",
      health: "healthy",
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/runtime",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
  });

  it("maps an explicit backend unavailable state without fallback", async () => {
    const fetcher = vi.fn(async () =>
      jsonResponse({
        ...readyPayload,
        status: "unconfigured",
        provider: null,
        model: null,
        execution: "none",
        selection_source: "none",
        health: "not_configured",
      }),
    );

    await expect(
      new HttpProviderRuntimeDataSource(fetcher).getRuntimeStatus(),
    ).resolves.toMatchObject({
      visibility: "unavailable",
      runtimeStatus: "unconfigured",
      provider: null,
      health: "not_configured",
    });
  });

  it("rejects unknown contract values instead of guessing", async () => {
    expect(() =>
      decodeProviderRuntimeStatus({
        ...readyPayload,
        status: "online",
      }),
    ).toThrow("runtime.status is not supported");

    const dataSource = new HttpProviderRuntimeDataSource(
      vi.fn(async () => jsonResponse({ ...readyPayload, version: "v2" })),
    );
    await expect(dataSource.getRuntimeStatus()).rejects.toMatchObject({
      code: "contract",
      source: "http",
    } satisfies Partial<ProviderRuntimeReadError>);
  });

  it("reports transport failure as unknown-capable read error", async () => {
    const dataSource = new HttpProviderRuntimeDataSource(
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );

    await expect(dataSource.getRuntimeStatus()).rejects.toMatchObject({
      code: "transport",
      source: "http",
    } satisfies Partial<ProviderRuntimeReadError>);
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
