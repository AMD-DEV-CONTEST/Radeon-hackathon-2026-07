import { describe, expect, it, vi } from "vitest";
import type { ConfirmationRequiredEvent } from "./events.js";
import { AgentRunStore } from "./run-store.js";

const confirmationEvent: ConfirmationRequiredEvent = {
  type: "confirmation_required",
  pendingActionId: "pending-1",
  confirmationToken: "secret-token",
  payloadHash: "payload-hash",
  expiresAt: "2026-07-26T12:00:00.000Z",
  taskCard: {
    planId: "plan-1",
    planVersion: 1,
    recipientLabel: "家庭保姆",
    serveAt: "unspecified",
    menu: [],
    useFromInventory: [],
    shoppingItems: [],
    executionNotes: [],
    disclosurePolicyVersion: "caregiver-minimum-v1"
  }
};

describe("AgentRunStore", () => {
  it("replays stored events through the record and publishes new events live", () => {
    const store = new AgentRunStore();
    const run = store.create("session-a");
    const listener = vi.fn();
    const unsubscribe = store.subscribe(run.runId, listener);

    store.append(run.runId, { type: "run_started", runId: run.runId });
    expect(store.hasRunning()).toBe(true);
    store.append(run.runId, { type: "answer_delta", text: "你好" });
    store.finish(run.runId, "completed");
    expect(store.hasRunning()).toBe(false);

    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.get(run.runId)).toMatchObject({
      sessionId: "session-a",
      status: "completed",
      events: [
        { type: "run_started", runId: run.runId },
        { type: "answer_delta", text: "你好" }
      ]
    });

    unsubscribe();
  });

  it("delivers a pending UI-only token once without adding it to replay events", () => {
    const store = new AgentRunStore();
    const run = store.create("session-a");
    store.append(run.runId, { type: "run_started", runId: run.runId });
    store.publishUiOnly(run.runId, confirmationEvent);
    store.append(run.runId, { type: "answer_delta", text: "待确认" });

    expect(store.get(run.runId)?.events).not.toContainEqual(confirmationEvent);
    expect(store.takeDeliverySnapshot(run.runId)).toEqual([
      { type: "run_started", runId: run.runId },
      confirmationEvent,
      { type: "answer_delta", text: "待确认" }
    ]);
    expect(store.takeDeliverySnapshot(run.runId)).not.toContainEqual(
      confirmationEvent
    );
  });

  it("publishes a live UI-only token to one subscriber without retaining it", () => {
    const store = new AgentRunStore();
    const run = store.create("session-a");
    const first = vi.fn();
    const second = vi.fn();
    store.subscribe(run.runId, first);
    store.subscribe(run.runId, second);

    store.publishUiOnly(run.runId, confirmationEvent);

    expect(first).toHaveBeenCalledWith(confirmationEvent);
    expect(second).not.toHaveBeenCalled();
    expect(store.takeDeliverySnapshot(run.runId)).not.toContainEqual(
      confirmationEvent
    );
  });
});
