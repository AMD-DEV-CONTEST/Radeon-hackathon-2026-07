import { describe, expect, it, vi } from "vitest";

import { WorkspaceReadError } from "../models";
import { HttpWorkspaceDataSource } from "./HttpWorkspaceDataSource";

const eventId = "event_0123456789abcdef0123456789abcdef";

function workspaceResponse() {
  return {
    version: "workspace-v1",
    events: [
      {
        id: eventId,
        type: "device_not_shutdown",
        status: "PENDING_HUMAN_REVIEW",
        timestamp: "2026-07-30T10:42:00+08:00",
        severity: "HIGH",
        location: "B03",
        asset_id: "B03-AIRCON",
        description: "Cooling performance is weaker than normal.",
        responsibility: {
          id: "maintenance_001",
          name: "Equipment Maintenance",
        },
      },
    ],
    active_event: null,
    pulse: null,
    employees: [],
  };
}

describe("HttpWorkspaceDataSource", () => {
  it("reads workspace-v1 once and returns an HTTP View Model", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(workspaceResponse()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const source = new HttpWorkspaceDataSource(fetcher);
    const controller = new AbortController();

    const snapshot = await source.getWorkspace({
      signal: controller.signal,
    });

    expect(source.source).toBe("http");
    expect(source.getInitialSnapshot()).toBeNull();
    expect(snapshot.source).toBe("http");
    expect(snapshot.events).toHaveLength(1);
    expect(snapshot.events[0]).toMatchObject({
      id: eventId,
      rawRuntimeStatus: "PENDING_HUMAN_REVIEW",
      occurredAt: "2026-07-30T10:42:00+08:00",
      location: { kind: "literal", value: "B03" },
      assetId: "B03-AIRCON",
      detail: {
        kind: "literal",
        value: "Cooling performance is weaker than normal.",
      },
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith("/api/workspace", {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });
  });

  it("returns a real empty snapshot without inventing Mock data", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          version: "workspace-v1",
          events: [],
          active_event: null,
          pulse: null,
          employees: [],
        }),
        { status: 200 },
      ),
    );
    const source = new HttpWorkspaceDataSource(fetcher);

    const snapshot = await source.getWorkspace();

    expect(snapshot.events).toEqual([]);
    expect(snapshot.activeNotices).toEqual([]);
    expect(snapshot.actionSummaries).toEqual([]);
    expect(snapshot.contextSignals).toEqual([]);
    expect(snapshot.commandSuggestions).toEqual([]);
  });

  it("fails closed for a rejected response and never performs a Mock fallback", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          error_code: "INTERNAL_ERROR",
          message: "Unavailable",
        }),
        { status: 503 },
      ),
    );
    const source = new HttpWorkspaceDataSource(fetcher);

    await expect(source.getWorkspace()).rejects.toMatchObject({
      name: "WorkspaceReadError",
      code: "unavailable",
      source: "http",
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("classifies network, JSON, and workspace-v1 failures", async () => {
    const networkSource = new HttpWorkspaceDataSource(
      vi
        .fn<typeof fetch>()
        .mockRejectedValue(new TypeError("disconnected")),
    );
    await expect(networkSource.getWorkspace()).rejects.toMatchObject({
      code: "transport",
      source: "http",
    });

    const invalidJsonSource = new HttpWorkspaceDataSource(
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response("{", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(
      invalidJsonSource.getWorkspace(),
    ).rejects.toMatchObject({
      code: "contract",
      source: "http",
      message: "Runtime workspace returned invalid JSON.",
    });

    const invalidContractSource = new HttpWorkspaceDataSource(
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            ...workspaceResponse(),
            version: "workspace-v2",
          }),
          { status: 200 },
        ),
      ),
    );
    await expect(
      invalidContractSource.getWorkspace(),
    ).rejects.toMatchObject({
      code: "contract",
      source: "http",
      message:
        "Runtime workspace response did not match workspace-v1.",
    });
  });

  it("reports pre-aborted and in-flight aborted requests explicitly", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const source = new HttpWorkspaceDataSource(fetcher);
    const preAborted = new AbortController();
    preAborted.abort();

    await expect(
      source.getWorkspace({ signal: preAborted.signal }),
    ).rejects.toBeInstanceOf(WorkspaceReadError);
    await expect(
      source.getWorkspace({ signal: preAborted.signal }),
    ).rejects.toMatchObject({
      code: "aborted",
      source: "http",
    });
    expect(fetcher).not.toHaveBeenCalled();

    const abortError = new DOMException("Aborted", "AbortError");
    const inFlightSource = new HttpWorkspaceDataSource(
      vi.fn<typeof fetch>().mockRejectedValue(abortError),
    );
    await expect(
      inFlightSource.getWorkspace(),
    ).rejects.toMatchObject({
      code: "aborted",
      source: "http",
    });
  });
});
