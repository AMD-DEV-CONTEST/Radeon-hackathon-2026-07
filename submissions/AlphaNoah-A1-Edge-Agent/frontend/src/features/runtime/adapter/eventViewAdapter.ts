import type {
  EventView,
  PresentationSeverity,
  ViewText,
} from "../models";
import { literalText, messageText } from "../models";
import { mapRuntimeStatus, mapSeverity } from "./statusMapping";

export interface EventAdapterInput {
  readonly eventId: string;
  readonly status: string;
  readonly severity: string | null;
  readonly title: ViewText | null;
  readonly detail: ViewText | null;
  readonly sourceLabel: ViewText | null;
  readonly occurredAt: string | null;
  readonly occurredLabel: ViewText | null;
  readonly location: ViewText | null;
  readonly assetId: string | null;
  readonly requiresHumanAction?: boolean;
  readonly actionSummaryId: string | null;
  readonly unknownFields?: readonly string[];
}

export function adaptEventView(
  input: EventAdapterInput,
): EventView {
  const status = mapRuntimeStatus(input.status);
  const severity = mapSeverity(input.severity);
  const warnings = [
    status.contractWarning,
    severity.contractWarning,
  ].filter((warning): warning is string => warning !== null);
  const unknownFields = input.unknownFields ?? [];

  return {
    id: input.eventId,
    title: input.title ?? literalText(input.eventId),
    detail: input.detail,
    sourceLabel: input.sourceLabel,
    occurredAt: input.occurredAt,
    occurredLabel: input.occurredLabel,
    location: input.location,
    assetId: input.assetId,
    runtimeStatus: status.runtimeStatus,
    rawRuntimeStatus: status.rawRuntimeStatus,
    statusLabel: status.statusLabel,
    lifecyclePhase: status.lifecyclePhase,
    severity: severity.severity,
    rawSeverity: severity.rawSeverity,
    severityLabel: severityLabel(
      severity.severity,
      severity.contractWarning,
      input.severity,
    ),
    requiresHumanAction:
      input.requiresHumanAction ?? status.requiresHumanAction,
    isTerminal: status.isTerminal,
    actionSummaryId: input.actionSummaryId,
    quality: {
      availability:
        unknownFields.length > 0 || warnings.length > 0
          ? "partial"
          : "available",
      unknownFields,
      contractWarnings: warnings,
    },
  };
}

function severityLabel(
  severity: PresentationSeverity,
  contractWarning: string | null,
  rawSeverity: string | null,
): ViewText {
  if (contractWarning) {
    return literalText(rawSeverity?.trim() || "UNKNOWN");
  }

  return messageText(`severity.${severity}`);
}
