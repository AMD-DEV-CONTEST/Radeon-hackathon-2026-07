import { describe, expect, it } from "vitest";

import {
  decodeRuntimeApiError,
  decodeRuntimeEventDetail,
  decodeRuntimeTask,
  decodeRuntimeTimeline,
  decodeRuntimeWorkspaceProjection,
} from "./runtimeApiDecoders";
import {
  RuntimeApiError,
  normalizeRuntimeApiErrorCode,
} from "./runtimeApiErrors";

describe("Runtime API decoders", () => {
  it("accepts nullable projections, preserves unknown status, and ignores additive fields", () => {
    expect(
      decodeRuntimeEventDetail({
        event_id: "event_1",
        status: "FUTURE_RUNTIME_STATUS",
        skill_id: null,
        skill_version: null,
        analysis: null,
        decision: null,
        future_field: { additive: true },
      }),
    ).toEqual({
      event_id: "event_1",
      status: "FUTURE_RUNTIME_STATUS",
      skill_id: null,
      skill_version: null,
      analysis: null,
      decision: null,
    });
  });

  it("decodes the complete event detail contract", () => {
    const detail = decodeRuntimeEventDetail({
      event_id: "event_2",
      status: "PENDING_HUMAN_REVIEW",
      skill_id: "skill.cooling",
      skill_version: "1.2.0",
      analysis: {
        detected_issue: "variance",
        decision_type: "inspect",
        reasoning_summary: "trend deviation",
        evidence: ["sensor-a", "sensor-b"],
        model_or_rule: "rule.cooling",
        confidence: 0.92,
        requires_human_review: true,
        severity: "HIGH",
      },
      decision: {
        decision_id: "decision_1",
        status: "PENDING_HUMAN_REVIEW",
        requires_human_review: true,
      },
    });

    expect(detail.analysis?.confidence).toBe(0.92);
    expect(detail.analysis?.evidence).toEqual([
      "sensor-a",
      "sensor-b",
    ]);
    expect(detail.decision?.decision_id).toBe("decision_1");
  });

  it.each([
    {
      label: "a missing required event field",
      value: {
        status: "NEW",
        skill_id: null,
        skill_version: null,
        analysis: null,
        decision: null,
      },
      message: "event.event_id must be a string",
    },
    {
      label: "a wrong event status type",
      value: {
        event_id: "event_1",
        status: 3,
        skill_id: null,
        skill_version: null,
        analysis: null,
        decision: null,
      },
      message: "event.status must be a string",
    },
    {
      label: "a missing nullable analysis field",
      value: {
        event_id: "event_1",
        status: "NEW",
        skill_id: null,
        skill_version: null,
        decision: null,
      },
      message: "event.analysis must be an object",
    },
    {
      label: "a non-finite confidence",
      value: {
        event_id: "event_1",
        status: "ANALYZED",
        skill_id: null,
        skill_version: null,
        analysis: {
          detected_issue: "variance",
          decision_type: "inspect",
          reasoning_summary: "trend deviation",
          evidence: [],
          model_or_rule: "rule.cooling",
          confidence: Number.NaN,
          requires_human_review: false,
          severity: "LOW",
        },
        decision: null,
      },
      message: "event.analysis.confidence must be a finite number",
    },
  ])("fails closed for $label", ({ value, message }) => {
    expect(() => decodeRuntimeEventDetail(value)).toThrowError(
      expect.objectContaining({
        name: "RuntimeApiError",
        code: "INVALID_RESPONSE",
        message,
      }),
    );
  });

  it("accepts a null task and rejects a missing task property", () => {
    expect(
      decodeRuntimeTask({ event_id: "event_1", task: null }),
    ).toEqual({ event_id: "event_1", task: null });

    expect(() =>
      decodeRuntimeTask({ event_id: "event_1" }),
    ).toThrow("task_response.task must be an object");
  });

  it("rejects critical timeline type errors", () => {
    expect(() =>
      decodeRuntimeTimeline([
        {
          sequence: "1",
          timestamp: "2026-07-29T00:00:00+00:00",
          action: "created",
          entity_type: "event",
          entity_id: "event_1",
          status: "NEW",
        },
      ]),
    ).toThrow("timeline[0].sequence must be a finite number");

    expect(() => decodeRuntimeTimeline(null)).toThrow(
      "timeline must be an array",
    );
  });

  it("preserves unknown API error codes for compatibility handling", () => {
    const dto = decodeRuntimeApiError({
      error_code: "FUTURE_ERROR",
      message: "Future failure",
      detail: "ignored",
    });

    expect(dto).toEqual({
      error_code: "FUTURE_ERROR",
      message: "Future failure",
    });
    expect(normalizeRuntimeApiErrorCode(dto.error_code)).toBe(
      "UNKNOWN_API_ERROR",
    );
    expect(normalizeRuntimeApiErrorCode("EVENT_NOT_FOUND")).toBe(
      "EVENT_NOT_FOUND",
    );
  });

  it("uses a typed INVALID_RESPONSE error", () => {
    try {
      decodeRuntimeApiError({ error_code: null, message: "bad" });
      throw new Error("decoder should have failed");
    } catch (error) {
      expect(error).toBeInstanceOf(RuntimeApiError);
      expect(error).toMatchObject({
        code: "INVALID_RESPONSE",
        rawCode: null,
        status: null,
      });
    }
  });
});

const projectionEventId =
  "event_0123456789abcdef0123456789abcdef";

function validWorkspaceProjection() {
  return {
    version: "workspace-v1",
    events: [
      {
        id: projectionEventId,
        type: "device_not_shutdown",
        status: "FUTURE_RUNTIME_STATUS",
        timestamp: "2026-07-30T10:42:00+08:00",
        severity: "UNKNOWN",
        location: "B03",
        asset_id: "B03-AIRCON",
        description: "Cooling performance is weaker than normal.",
        responsibility: null,
        ignored_private_field: "never returned",
      },
    ],
    active_event: null,
    pulse: null,
    employees: [],
    ignored_top_level_field: {
      prompt: "never returned",
    },
  };
}

describe("workspace-v1 projection decoder", () => {
  it("decodes a legal partial projection and allowlists public fields", () => {
    expect(
      decodeRuntimeWorkspaceProjection(validWorkspaceProjection()),
    ).toEqual({
      version: "workspace-v1",
      events: [
        {
          id: projectionEventId,
          type: "device_not_shutdown",
          status: "FUTURE_RUNTIME_STATUS",
          timestamp: "2026-07-30T10:42:00+08:00",
          severity: "UNKNOWN",
          location: "B03",
          asset_id: "B03-AIRCON",
          description: "Cooling performance is weaker than normal.",
          responsibility: null,
        },
      ],
      active_event: null,
      pulse: null,
      employees: [],
    });
  });

  it("decodes the complete Workspace aggregate contract", () => {
    const decoded = decodeRuntimeWorkspaceProjection({
      ...validWorkspaceProjection(),
      active_event: {
        id: projectionEventId,
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
      pulse: {
        level: "critical",
        title: "Incident requires attention",
        event_id: projectionEventId,
      },
      employees: [
        {
          id: "maintenance_001",
          name: "Equipment Maintenance",
          status: "working",
          current_event_id: projectionEventId,
          responsibility: "Equipment Maintenance",
          skills: [{ name: "restaurant-aircon-shutdown" }],
        },
      ],
    });

    expect(decoded.active_event?.responsibility).toEqual({
      id: "maintenance_001",
      name: "Equipment Maintenance",
    });
    expect(decoded.pulse?.level).toBe("critical");
    expect(decoded.employees[0]).toMatchObject({
      id: "maintenance_001",
      status: "working",
      current_event_id: projectionEventId,
    });
    expect(decoded.employees[0]?.skills).toEqual([
      { name: "restaurant-aircon-shutdown" },
    ]);
  });

  it.each([
    {
      label: "a missing required collection",
      value: {
        version: "workspace-v1",
        active_event: null,
        pulse: null,
        employees: [],
      },
      message: "workspace.events must be an array",
    },
    {
      label: "an unsupported version",
      value: {
        ...validWorkspaceProjection(),
        version: "workspace-v2",
      },
      message: "workspace.version must equal workspace-v1",
    },
    {
      label: "an invalid Event ID",
      value: {
        ...validWorkspaceProjection(),
        events: [
          {
            ...validWorkspaceProjection().events[0],
            id: "event_1",
          },
        ],
      },
      message:
        "workspace.events[0].id must be a Runtime Event ID",
    },
    {
      label: "an unsupported severity",
      value: {
        ...validWorkspaceProjection(),
        events: [
          {
            ...validWorkspaceProjection().events[0],
            severity: "URGENT",
          },
        ],
      },
      message:
        "workspace.events[0].severity is not a workspace-v1 severity",
    },
    {
      label: "an invalid Pulse level",
      value: {
        ...validWorkspaceProjection(),
        pulse: {
          level: "idle",
          title: "No notification",
          event_id: projectionEventId,
        },
      },
      message:
        "workspace.pulse.level must be attention or critical",
    },
    {
      label: "an invalid employee status",
      value: {
        ...validWorkspaceProjection(),
        employees: [
          {
            id: "maintenance_001",
            name: "Equipment Maintenance",
            status: "online",
            current_event_id: null,
            responsibility: "Equipment Maintenance",
            skills: [],
          },
        ],
      },
      message:
        "workspace.employees[0].status must be working or unknown",
    },
  ])("fails closed for $label", ({ value, message }) => {
    expect(() =>
      decodeRuntimeWorkspaceProjection(value),
    ).toThrowError(
      expect.objectContaining({
        name: "RuntimeApiError",
        code: "INVALID_RESPONSE",
        message,
      }),
    );
  });

  it("enforces the bounded Event feed", () => {
    const event = validWorkspaceProjection().events[0];
    expect(() =>
      decodeRuntimeWorkspaceProjection({
        ...validWorkspaceProjection(),
        events: Array.from({ length: 101 }, () => event),
      }),
    ).toThrow(
      "workspace.events must contain at most 100 items",
    );
  });
});
