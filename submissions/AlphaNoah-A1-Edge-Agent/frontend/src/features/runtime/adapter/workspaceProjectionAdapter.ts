import type {
  RuntimeEventProjectionDto,
  RuntimeWorkspaceProjectionDto,
} from "../api/runtimeApiDtos";
import {
  literalText,
  messageText,
  type ActionSummary,
  type WorkspaceSnapshot,
} from "../models";
import { adaptActionSummary } from "./actionSummaryAdapter";
import { adaptEventView } from "./eventViewAdapter";
import { adaptHealthView } from "./healthViewAdapter";

const workspaceUnknownFields = [
  "site",
  "health",
  "context_signals",
  "command_suggestions",
  "observed_at",
] as const;

const actionUnknownFields = [
  "analysis",
  "decision",
  "task",
  "evidence",
  "timeline",
] as const;

export function adaptWorkspaceProjection(
  dto: RuntimeWorkspaceProjectionDto,
): WorkspaceSnapshot {
  const eventDtos = prioritizeActiveEvent(
    dto.events,
    dto.active_event,
  );
  const actionSummaries = eventDtos.map(adaptEventActionSummary);
  const events = eventDtos.map((event) =>
    adaptEventView({
      eventId: event.id,
      status: event.status,
      severity: event.severity,
      title: literalText(event.type),
      detail: literalText(event.description),
      sourceLabel: event.responsibility
        ? literalText(event.responsibility.name)
        : null,
      occurredAt: event.timestamp,
      occurredLabel: null,
      location: literalText(event.location),
      assetId: event.asset_id,
      actionSummaryId: actionSummaryId(event.id),
      unknownFields: [],
    }),
  );
  const currentFocus =
    dto.active_event === null
      ? null
      : (actionSummaries.find(
          (summary) =>
            summary.eventId === dto.active_event?.id,
        ) ?? null);

  return {
    source: "http",
    site: {
      id: null,
      name: messageText("workspace.runtimeName"),
      area: null,
      observationLabel: null,
    },
    health: adaptHealthView({
      state: "unknown",
      label: literalText("UNKNOWN"),
      components: [],
      observedAt: null,
      unknownFields: ["health"],
    }),
    contextSignals: [],
    // Noah Pulse has an independent GET /api/pulse owner in F03-D2.
    // The aggregate field is decoded for contract safety but is not a
    // second UI state source.
    activeNotices: [],
    events,
    actionSummaries,
    currentFocus,
    commandSuggestions: [],
    observedAt: null,
    quality: {
      availability: "partial",
      unknownFields: workspaceUnknownFields,
      contractWarnings: [],
    },
  };
}

function prioritizeActiveEvent(
  events: readonly RuntimeEventProjectionDto[],
  activeEvent: RuntimeEventProjectionDto | null,
): readonly RuntimeEventProjectionDto[] {
  if (activeEvent === null) {
    return events;
  }

  return [
    activeEvent,
    ...events.filter((event) => event.id !== activeEvent.id),
  ];
}

function adaptEventActionSummary(
  event: RuntimeEventProjectionDto,
): ActionSummary {
  const facts = [
    literalText(event.timestamp),
    literalText(event.location),
    literalText(event.asset_id),
    ...(event.responsibility
      ? [literalText(event.responsibility.name)]
      : []),
  ];

  return adaptActionSummary({
    id: actionSummaryId(event.id),
    eventId: event.id,
    heading: literalText(event.type),
    facts,
    aiUnderstanding: null,
    rawSeverity: event.severity,
    riskExplanation: null,
    suggestedAction: null,
    humanDecision: null,
    decision: null,
    task: null,
    evidenceStatus: null,
    timeline: [],
    unknownFields: actionUnknownFields,
  });
}

function actionSummaryId(eventId: string): string {
  return `workspace-action-${eventId}`;
}
