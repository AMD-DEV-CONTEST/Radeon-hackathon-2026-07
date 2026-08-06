import { describe, expect, it } from "vitest";

import { adaptEventView } from "./eventViewAdapter";
import { adaptPulseNotice } from "./pulseNoticeAdapter";
import {
  mapRuntimeStatus,
  mapSeverity,
} from "./statusMapping";
import { literalText, messageText } from "../models";

const expectedStatuses = {
  NEW: ["detected", false, false],
  ANALYZED: ["analysis", false, false],
  PENDING_HUMAN_REVIEW: ["review", true, false],
  APPROVED: ["review", false, false],
  TASK_CREATED: ["task", false, false],
  IN_PROGRESS: ["task", false, false],
  EVIDENCE_SUBMITTED: ["evidence", false, false],
  UNDER_REVIEW: ["evidence", false, false],
  CLOSED: ["resolved", false, true],
  REJECTED: ["review", false, true],
  NEEDS_MORE_EVIDENCE: ["evidence", true, false],
  FAILED: ["failed", false, true],
  CANCELLED: ["resolved", false, true],
  ESCALATED: ["review", true, false],
} as const;

describe("Runtime status projection", () => {
  it.each(Object.entries(expectedStatuses))(
    "projects the real EventStatus %s without inventing a transition",
    (rawStatus, [lifecyclePhase, requiresHumanAction, isTerminal]) => {
      expect(mapRuntimeStatus(rawStatus)).toMatchObject({
        runtimeStatus: rawStatus,
        rawRuntimeStatus: rawStatus,
        lifecyclePhase,
        requiresHumanAction,
        isTerminal,
        contractWarning: null,
      });
    },
  );

  it("preserves an unknown raw status and does not present it as Closed", () => {
    const projection = mapRuntimeStatus("AWAITING_OPERATOR");

    expect(projection).toMatchObject({
      runtimeStatus: "UNKNOWN",
      rawRuntimeStatus: "AWAITING_OPERATOR",
      lifecyclePhase: "failed",
      isTerminal: false,
    });
    expect(projection.contractWarning).toContain(
      "AWAITING_OPERATOR",
    );
    expect(projection.statusLabel).toEqual(
      literalText("AWAITING_OPERATOR"),
    );
    expect(projection.statusLabel).not.toEqual(literalText("CLOSED"));
  });

  it("keeps the original casing and whitespace in rawRuntimeStatus", () => {
    expect(mapRuntimeStatus(" analyzed ")).toMatchObject({
      runtimeStatus: "ANALYZED",
      rawRuntimeStatus: " analyzed ",
      lifecyclePhase: "analysis",
    });
  });

  it.each([
    ["PENDING_HUMAN_REVIEW", "status.PENDING_HUMAN_REVIEW"],
    ["APPROVED", "status.APPROVED"],
    ["REJECTED", "status.REJECTED"],
    ["TASK_CREATED", "status.TASK_CREATED"],
    ["CLOSED", "status.CLOSED"],
  ] as const)("localizes known user-visible status %s", (status, key) => {
    const projection = mapRuntimeStatus(status);

    expect(projection.statusLabel).toEqual(messageText(key));
    expect(projection.statusLabel).not.toEqual(literalText(status));
  });
});

describe("severity projection", () => {
  it.each([
    ["LOW", "info"],
    ["MEDIUM", "attention"],
    ["HIGH", "warning"],
    ["CRITICAL", "critical"],
  ] as const)("maps %s to %s", (rawSeverity, severity) => {
    expect(mapSeverity(rawSeverity)).toEqual({
      severity,
      rawSeverity,
      contractWarning: null,
    });
  });

  it("preserves Runtime UNKNOWN and exposes that uncertainty as a warning", () => {
    const projection = mapSeverity("UNKNOWN");

    expect(projection.severity).toBe("info");
    expect(projection.rawSeverity).toBe("UNKNOWN");
    expect(projection.contractWarning).toBe(
      "Unknown severity: UNKNOWN",
    );
  });

  it("preserves an unrecognized severity and returns a contract warning", () => {
    expect(mapSeverity("URGENT")).toEqual({
      severity: "attention",
      rawSeverity: "URGENT",
      contractWarning: "Unknown severity: URGENT",
    });
  });

  it.each([null, ""] as const)(
    "treats the nullable wire value %s as an explicit empty projection",
    (rawSeverity) => {
      expect(mapSeverity(rawSeverity)).toEqual({
        severity: "info",
        rawSeverity,
        contractWarning: null,
      });
    },
  );
});

describe("adapter compatibility fields", () => {
  it("keeps nullable event fields and falls back only to the event id for a title", () => {
    const event = adaptEventView({
      eventId: "event_missing_projection",
      status: "NEW",
      severity: null,
      title: null,
      detail: null,
      sourceLabel: null,
      occurredAt: null,
      occurredLabel: null,
      location: null,
      assetId: null,
      actionSummaryId: null,
      unknownFields: ["description", "timestamp"],
    });

    expect(event).toMatchObject({
      id: "event_missing_projection",
      title: literalText("event_missing_projection"),
      detail: null,
      sourceLabel: null,
      occurredAt: null,
      location: null,
      rawSeverity: null,
      actionSummaryId: null,
      quality: {
        availability: "partial",
        unknownFields: ["description", "timestamp"],
      },
    });
  });

  it("preserves the raw Runtime status on a Pulse notice", () => {
    const notice = adaptPulseNotice({
      id: "notice_unknown_status",
      eventId: "event_unknown_status",
      status: "AWAITING_OPERATOR",
      severity: "HIGH",
      title: literalText("Unknown status"),
      summary: literalText("Compatibility path"),
      facts: null,
      analysis: null,
      nextAction: null,
      requiresHumanAction: false,
      createdAt: null,
      sourceNotificationStatus: null,
    });

    expect(
      (notice as unknown as Record<string, unknown>).rawRuntimeStatus,
    ).toBe("AWAITING_OPERATOR");
    expect(notice.runtimeStatus).toBe("UNKNOWN");
    expect(notice.quality.contractWarnings).toContain(
      "Unknown EventStatus: AWAITING_OPERATOR",
    );
  });
});
