import type { DemoActivationResponseDto } from "../api/activationApiDtos";
import { bindDemoOwnerToEmployee } from "./activationBindings";
import {
  adaptActionSummary,
} from "../../runtime/adapter/actionSummaryAdapter";
import {
  adaptEventView,
} from "../../runtime/adapter/eventViewAdapter";
import {
  adaptPulseNotice,
} from "../../runtime/adapter/pulseNoticeAdapter";
import {
  availableDataQuality,
  literalText,
  messageText,
  type DataQuality,
} from "../../runtime";
import type {
  CurrentTaskView,
  WorkRecord,
  WorkRecordKind,
} from "../../digital-employees";
import type {
  ActivationDisplayState,
  ActivationSnapshot,
} from "../models/activationSnapshot";

export function adaptActivationSnapshot(
  dto: DemoActivationResponseDto,
  source: ActivationSnapshot["source"],
): ActivationSnapshot {
  const activeEmployeeId = bindDemoOwnerToEmployee(
    dto.responsibility.owner_id,
    dto.responsibility.match_type,
  );
  const state = deriveActivationState(dto, activeEmployeeId);
  const hasCurrentWork =
    state === "working" || state === "approval_required";
  const quality = adaptQuality(dto, activeEmployeeId);
  const eventTitle = messageText("activation.event.title");
  const requiresHumanAction =
    dto.human_review?.required === true &&
    dto.human_review.status === "PENDING_HUMAN_REVIEW";
  const event = adaptEventView({
    eventId: dto.event.event_id,
    status: dto.event.status,
    severity: dto.event.severity,
    title: eventTitle,
    detail: literalText(dto.event.description),
    sourceLabel: messageText("activation.event.source"),
    occurredAt: dto.event.timestamp,
    occurredLabel: null,
    location: literalText(dto.event.location),
    assetId: dto.event.asset_id,
    requiresHumanAction,
    actionSummaryId: `activation-action-${dto.event.event_id}`,
    unknownFields: quality.unknownFields,
  });
  const notice = adaptPulseNotice({
    id:
      dto.notification?.notification_id ??
      `activation-notice-${dto.event.event_id}`,
    eventId: dto.event.event_id,
    status: dto.event.status,
    severity: dto.event.severity,
    title: eventTitle,
    summary:
      state === "unassigned"
        ? messageText("activation.pulse.unassigned")
        : messageText("activation.pulse.summary"),
    facts: literalText(
      `${dto.event.asset_id} · ${dto.event.description}`,
    ),
    analysis: dto.analysis
      ? literalText(dto.analysis.reasoning_summary)
      : null,
    nextAction: messageText(
      state === "unassigned"
        ? "activation.next.assign"
        : "activation.next.review",
    ),
    requiresHumanAction,
    createdAt:
      dto.notification?.created_at ?? dto.event.timestamp,
    sourceNotificationStatus: dto.notification?.status ?? null,
  });
  const action = adaptActionSummary({
    id: `activation-action-${dto.event.event_id}`,
    eventId: dto.event.event_id,
    heading: eventTitle,
    facts: [
      literalText(
        `${dto.event.asset_id} · ${dto.event.location}`,
      ),
      literalText(dto.event.description),
    ],
    aiUnderstanding: dto.analysis
      ? literalText(dto.analysis.reasoning_summary)
      : null,
    rawSeverity: dto.event.severity,
    riskExplanation: dto.analysis
      ? literalText(dto.analysis.detected_issue)
      : null,
    suggestedAction: messageText(
      state === "unassigned"
        ? "activation.next.assign"
        : "activation.next.review",
    ),
    humanDecision: requiresHumanAction
      ? messageText("activation.review.pending")
      : null,
    decision: dto.human_review
      ? {
          id: dto.human_review.decision_id,
          status: dto.human_review.status,
          requiresHumanReview: dto.human_review.required,
        }
      : null,
    task: null,
    evidenceStatus: null,
    timeline: dto.work_records.map((record) => ({
      sequence: record.sequence,
      timestamp: record.occurred_at,
      action: record.kind,
      entityType: "event",
      entityId: record.event_id,
      status: dto.event.status,
    })),
    unknownFields: quality.unknownFields,
  });
  const workRecords = dto.work_records
    .map(adaptWorkRecord)
    .sort((left, right) =>
      (right.occurredAt ?? "").localeCompare(
        left.occurredAt ?? "",
      ),
    );

  return {
    source,
    eventId: dto.event.event_id,
    activeEmployeeId,
    activeCapabilityId: null,
    state,
    event: {
      ...event,
      quality: mergeQuality(event.quality, quality),
    },
    notice: {
      ...notice,
      quality: mergeQuality(notice.quality, quality),
    },
    action: {
      ...action,
      quality: mergeQuality(action.quality, quality),
    },
    employeeCurrentWork:
      activeEmployeeId === null || !hasCurrentWork
        ? null
        : adaptCurrentWork(dto, quality),
    workRecords,
    observedAt: dto.event.timestamp,
    replayed: dto.replayed,
    quality,
  };
}

function deriveActivationState(
  dto: DemoActivationResponseDto,
  employeeId: string | null,
): Exclude<ActivationDisplayState, "activating"> {
  const rawStatus = dto.event.status.trim().toUpperCase();
  if (
    rawStatus === "FAILED" ||
    rawStatus === "ESCALATED" ||
    !knownRuntimeStatus(rawStatus)
  ) {
    return "failed";
  }
  if (
    rawStatus === "CLOSED" ||
    rawStatus === "REJECTED" ||
    rawStatus === "CANCELLED"
  ) {
    return "inactive";
  }
  if (employeeId === null) {
    return "unassigned";
  }
  if (
    rawStatus === "PENDING_HUMAN_REVIEW" ||
    dto.human_review?.required
  ) {
    return "approval_required";
  }
  return "working";
}

function knownRuntimeStatus(status: string): boolean {
  return new Set([
    "NEW",
    "ANALYZED",
    "PENDING_HUMAN_REVIEW",
    "APPROVED",
    "TASK_CREATED",
    "IN_PROGRESS",
    "EVIDENCE_SUBMITTED",
    "UNDER_REVIEW",
    "CLOSED",
    "REJECTED",
    "NEEDS_MORE_EVIDENCE",
    "FAILED",
    "CANCELLED",
    "ESCALATED",
  ]).has(status);
}

function adaptQuality(
  dto: DemoActivationResponseDto,
  employeeId: string | null,
): DataQuality {
  const warnings = [...dto.quality.contract_warnings];
  const unknownFields = [...dto.quality.unknown_fields];
  if (
    employeeId === null &&
    dto.responsibility.match_type !== "unassigned" &&
    dto.responsibility.owner_id !== "UNASSIGNED"
  ) {
    warnings.push(
      `Unknown Digital Employee owner binding: ${dto.responsibility.owner_id}`,
    );
    unknownFields.push("active_employee_id");
  }
  return {
    availability:
      dto.quality.availability === "available" &&
      warnings.length === 0 &&
      unknownFields.length === 0
        ? "available"
        : dto.quality.availability === "unavailable"
          ? "unavailable"
          : "partial",
    unknownFields: [...new Set(unknownFields)],
    contractWarnings: [...new Set(warnings)],
  };
}

function adaptCurrentWork(
  dto: DemoActivationResponseDto,
  quality: DataQuality,
): CurrentTaskView {
  return {
    id: `activation-work-${dto.event.event_id}`,
    title: messageText("activation.employee.currentWork"),
    runtimeStatus: dto.event.status,
    statusLabel: messageText(
      dto.event.status === "PENDING_HUMAN_REVIEW"
        ? "activation.review.pending"
        : "activation.employee.working",
    ),
    statusTone:
      dto.event.status === "PENDING_HUMAN_REVIEW"
        ? "attention"
        : "info",
    updatedAt: dto.event.timestamp,
    eventId: dto.event.event_id,
    quality,
  };
}

function adaptWorkRecord(
  record: DemoActivationResponseDto["work_records"][number],
): WorkRecord {
  const kind = workRecordKind(record.kind);
  return {
    id: record.id,
    occurredAt: record.occurred_at,
    occurredLabel: null,
    title: messageText(`activation.record.${record.kind}`),
    detail: null,
    kind,
    eventId: record.event_id,
    taskId: null,
    rawAction: record.kind,
    quality: availableDataQuality,
  };
}

function workRecordKind(
  kind: DemoActivationResponseDto["work_records"][number]["kind"],
): WorkRecordKind {
  switch (kind) {
    case "event_received":
      return "event_detected";
    case "responsibility_matched":
      return "analysis";
    case "analysis":
      return "analysis";
    case "knowledge_lookup":
      return "knowledge_lookup";
    case "human_review":
      return "human_review";
  }
}

function mergeQuality(
  first: DataQuality,
  second: DataQuality,
): DataQuality {
  return {
    availability:
      first.availability === "unavailable" ||
      second.availability === "unavailable"
        ? "unavailable"
        : first.availability === "partial" ||
            second.availability === "partial"
          ? "partial"
          : "available",
    unknownFields: [
      ...new Set([
        ...first.unknownFields,
        ...second.unknownFields,
      ]),
    ],
    contractWarnings: [
      ...new Set([
        ...first.contractWarnings,
        ...second.contractWarnings,
      ]),
    ],
  };
}
