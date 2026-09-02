import { describe, expect, it } from "vitest";

import { WorkspaceReadError } from "../models";
import {
  MockWorkspaceDataSource,
  buildMockWorkspaceSnapshot,
} from "./MockWorkspaceDataSource";

describe("MockWorkspaceDataSource", () => {
  it("uses the same snapshot contract for initial and async reads", async () => {
    const source = new MockWorkspaceDataSource();
    const initial = source.getInitialSnapshot();

    expect(await source.getWorkspace()).toBe(initial);
    expect(initial.source).toBe("mock");
    expect(initial.events).not.toHaveLength(0);
    expect(initial.activeNotices[0]?.eventId).toBe(
      initial.events[0]?.id,
    );
    for (const event of initial.events) {
      expect(
        initial.actionSummaries.some(
          (summary) =>
            summary.id === event.actionSummaryId &&
            summary.eventId === event.id,
        ),
      ).toBe(true);
    }
  });

  it("selects a valid focus and returns null for an invalid event id", async () => {
    const snapshot = buildMockWorkspaceSnapshot();
    const source = new MockWorkspaceDataSource(snapshot);
    const event = snapshot.events[1];
    if (!event) {
      throw new Error("Expected a second Mock event.");
    }

    await expect(
      source.getWorkspace({ selectedEventId: event.id }),
    ).resolves.toMatchObject({
      currentFocus: {
        id: event.actionSummaryId,
        eventId: event.id,
      },
    });
    await expect(
      source.getWorkspace({ selectedEventId: "missing_event" }),
    ).resolves.toMatchObject({ currentFocus: null });
  });

  it("returns a typed aborted error", async () => {
    const source = new MockWorkspaceDataSource();
    const controller = new AbortController();
    controller.abort();

    const promise = source.getWorkspace({
      signal: controller.signal,
    });

    await expect(promise).rejects.toBeInstanceOf(WorkspaceReadError);
    await expect(promise).rejects.toMatchObject({
      code: "aborted",
      source: "mock",
    });
  });
});
