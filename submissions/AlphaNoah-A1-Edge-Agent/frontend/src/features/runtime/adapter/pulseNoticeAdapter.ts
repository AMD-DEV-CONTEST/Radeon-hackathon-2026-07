import type {
  PulseNotice,
  ViewText,
} from "../models";
import { messageText } from "../models";
import {
  derivePulseNoticeKind,
  mapRuntimeStatus,
  mapSeverity,
  pulsePriority,
} from "./statusMapping";

export interface PulseNoticeAdapterInput {
  readonly id: string;
  readonly eventId: string;
  readonly status: string;
  readonly severity: string | null;
  readonly title: ViewText;
  readonly summary: ViewText;
  readonly facts: ViewText | null;
  readonly analysis: ViewText | null;
  readonly nextAction: ViewText | null;
  readonly requiresHumanAction: boolean;
  readonly createdAt: string | null;
  readonly sourceNotificationStatus: string | null;
}

export function adaptPulseNotice(
  input: PulseNoticeAdapterInput,
): PulseNotice {
  const status = mapRuntimeStatus(input.status);
  const severity = mapSeverity(input.severity);
  const kind = derivePulseNoticeKind({
    severity: severity.severity,
    runtimeStatus: status.runtimeStatus,
    requiresHumanAction: input.requiresHumanAction,
  });
  const warnings = [
    status.contractWarning,
    severity.contractWarning,
  ].filter((warning): warning is string => warning !== null);

  return {
    id: input.id,
    eventId: input.eventId,
    kind,
    stateLabel: noticeStateLabel(kind),
    severity: severity.severity,
    priority: pulsePriority(kind),
    title: input.title,
    summary: input.summary,
    facts: input.facts,
    analysis: input.analysis,
    nextAction: input.nextAction,
    requiresHumanAction: input.requiresHumanAction,
    createdAt: input.createdAt,
    runtimeStatus: status.runtimeStatus,
    rawRuntimeStatus: status.rawRuntimeStatus,
    sourceNotificationStatus: input.sourceNotificationStatus,
    quality: {
      availability: warnings.length > 0 ? "partial" : "available",
      unknownFields: [],
      contractWarnings: warnings,
    },
  };
}

function noticeStateLabel(
  kind: PulseNotice["kind"],
): ViewText {
  switch (kind) {
    case "informational":
      return messageText("pulse.state.informational");
    case "attention":
      return messageText("pulse.state.attention");
    case "approval_required":
      return messageText("pulse.reviewNeeded");
    case "critical":
      return messageText("severity.critical");
  }
}
