import { describe, expect, it } from "vitest";

import type {
  RuntimeEventProjectionDto,
  RuntimeWorkspaceProjectionDto,
} from "../api/runtimeApiDtos";
import { adaptWorkspaceProjection } from "./workspaceProjectionAdapter";

const activeEventId =
  "event_0123456789abcdef0123456789abcdef";
const closedEventId =
  "event_fedcba9876543210fedcba9876543210";

function event(
  id: string,
  status: string,
  severity: RuntimeEventProjectionDto["severity"] = "HIGH",
): RuntimeEventProjectionDto {
  return {
    id,
    type: "device_not_shutdown",
    status,
    timestamp: "2026-07-30T10:42:00+08:00",
    severity,
    location: "B03",
    asset_id: "B03-AIRCON",
    description: "Cooling performance is weaker than normal.",
    responsibility: {
      id: "maintenance_001",
      name: "Equipment Maintenance",
    },
  };
}

function workspace(
  overrides: Partial<RuntimeWorkspaceProjectionDto> = {},
): RuntimeWorkspaceProjectionDto {
  return {
    version: "workspace-v1",
    events: [],
    active_event: null,
    pulse: null,
    employees: [],
    ...overrides,
  };
}

describe("workspace-v1 View Model adapter", () => {
  it("puts the active Event first, de-duplicates it, and focuses its safe summary", () => {
    const active = event(
      activeEventId,
      "PENDING_HUMAN_REVIEW",
    );
    const closed = event(closedEventId, "CLOSED", "LOW");

    const snapshot = adaptWorkspaceProjection(
      workspace({
        events: [closed, active],
        active_event: active,
      }),
    );

    expect(snapshot.events.map(({ id }) => id)).toEqual([
      activeEventId,
      closedEventId,
    ]);
    expect(snapshot.actionSummaries).toHaveLength(2);
    expect(snapshot.currentFocus).toMatchObject({
      id: `workspace-action-${activeEventId}`,
      eventId: activeEventId,
      aiUnderstanding: null,
      decision: null,
      task: null,
    });
    expect(snapshot.events[0]?.actionSummaryId).toBe(
      `workspace-action-${activeEventId}`,
    );
    expect(snapshot.currentFocus?.facts).toEqual([
      {
        kind: "literal",
        value: "2026-07-30T10:42:00+08:00",
      },
      { kind: "literal", value: "B03" },
      { kind: "literal", value: "B03-AIRCON" },
      { kind: "literal", value: "Equipment Maintenance" },
    ]);
  });

  it("adds an active Event outside the bounded feed", () => {
    const snapshot = adaptWorkspaceProjection(
      workspace({
        events: [event(closedEventId, "CLOSED")],
        active_event: event(activeEventId, "ANALYZED"),
      }),
    );

    expect(snapshot.events.map(({ id }) => id)).toEqual([
      activeEventId,
      closedEventId,
    ]);
  });

  it("uses neutral unknown/partial values instead of Mock workspace facts", () => {
    const snapshot = adaptWorkspaceProjection(workspace());

    expect(snapshot).toMatchObject({
      source: "http",
      site: {
        id: null,
        name: {
          kind: "message",
          id: "workspace.runtimeName",
        },
        area: null,
        observationLabel: null,
      },
      health: {
        state: "unknown",
        components: [],
      },
      contextSignals: [],
      activeNotices: [],
      events: [],
      actionSummaries: [],
      currentFocus: null,
      commandSuggestions: [],
      observedAt: null,
      quality: {
        availability: "partial",
        contractWarnings: [],
      },
    });
  });

  it("preserves unknown Event status and leaves Pulse to its independent owner", () => {
    const snapshot = adaptWorkspaceProjection(
      workspace({
        events: [
          event(
            activeEventId,
            "FUTURE_RUNTIME_STATUS",
            "CRITICAL",
          ),
        ],
        pulse: {
          level: "attention",
          title: "Review required",
          event_id: activeEventId,
        },
      }),
    );

    expect(snapshot.events[0]).toMatchObject({
      runtimeStatus: "UNKNOWN",
      rawRuntimeStatus: "FUTURE_RUNTIME_STATUS",
      lifecyclePhase: "failed",
      quality: {
        availability: "partial",
      },
    });
    expect(snapshot.activeNotices).toEqual([]);
  });
});
