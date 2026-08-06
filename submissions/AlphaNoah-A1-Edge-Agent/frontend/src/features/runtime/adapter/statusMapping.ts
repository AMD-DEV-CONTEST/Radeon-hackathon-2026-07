import type {
  LifecyclePhase,
  PresentationSeverity,
  PulseNoticeKind,
  RuntimeEventStatus,
  ViewText,
} from "../models";
import { literalText, messageText } from "../models";

const runtimeStatuses = new Set<RuntimeEventStatus>([
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
]);

export interface RuntimeStatusProjection {
  readonly runtimeStatus: RuntimeEventStatus | "UNKNOWN";
  readonly rawRuntimeStatus: string;
  readonly lifecyclePhase: LifecyclePhase;
  readonly statusLabel: ViewText;
  readonly requiresHumanAction: boolean;
  readonly isTerminal: boolean;
  readonly contractWarning: string | null;
}

export interface SeverityProjection {
  readonly severity: PresentationSeverity;
  readonly rawSeverity: string | null;
  readonly contractWarning: string | null;
}

export function mapRuntimeStatus(
  rawStatus: string,
): RuntimeStatusProjection {
  const normalized = rawStatus.trim().toUpperCase();
  const runtimeStatus = runtimeStatuses.has(
    normalized as RuntimeEventStatus,
  )
    ? (normalized as RuntimeEventStatus)
    : "UNKNOWN";

  if (runtimeStatus === "UNKNOWN") {
    return {
      runtimeStatus,
      rawRuntimeStatus: rawStatus,
      lifecyclePhase: "failed",
      statusLabel: literalText(rawStatus || "UNKNOWN"),
      requiresHumanAction: false,
      isTerminal: false,
      contractWarning: `Unknown EventStatus: ${rawStatus || "<empty>"}`,
    };
  }

  const lifecyclePhase = lifecyclePhaseByStatus[runtimeStatus];
  return {
    runtimeStatus,
    rawRuntimeStatus: rawStatus,
    lifecyclePhase,
    statusLabel: statusLabelByPhase(lifecyclePhase, runtimeStatus),
    requiresHumanAction:
      runtimeStatus === "PENDING_HUMAN_REVIEW" ||
      runtimeStatus === "NEEDS_MORE_EVIDENCE" ||
      runtimeStatus === "ESCALATED",
    isTerminal:
      runtimeStatus === "CLOSED" ||
      runtimeStatus === "REJECTED" ||
      runtimeStatus === "FAILED" ||
      runtimeStatus === "CANCELLED",
    contractWarning: null,
  };
}

export function mapSeverity(
  rawSeverity: string | null,
): SeverityProjection {
  if (rawSeverity === null || rawSeverity.trim() === "") {
    return {
      severity: "info",
      rawSeverity,
      contractWarning: null,
    };
  }

  switch (rawSeverity.trim().toUpperCase()) {
    case "LOW":
      return {
        severity: "info",
        rawSeverity,
        contractWarning: null,
      };
    case "MEDIUM":
      return {
        severity: "attention",
        rawSeverity,
        contractWarning: null,
      };
    case "HIGH":
      return {
        severity: "warning",
        rawSeverity,
        contractWarning: null,
      };
    case "CRITICAL":
      return {
        severity: "critical",
        rawSeverity,
        contractWarning: null,
      };
    case "UNKNOWN":
      return {
        severity: "info",
        rawSeverity,
        contractWarning: "Unknown severity: UNKNOWN",
      };
    default:
      return {
        severity: "attention",
        rawSeverity,
        contractWarning: `Unknown severity: ${rawSeverity}`,
      };
  }
}

export function derivePulseNoticeKind({
  severity,
  runtimeStatus,
  requiresHumanAction,
}: {
  severity: PresentationSeverity;
  runtimeStatus: RuntimeEventStatus | "UNKNOWN";
  requiresHumanAction: boolean;
}): PulseNoticeKind {
  if (severity === "critical") {
    return "critical";
  }
  if (
    requiresHumanAction ||
    runtimeStatus === "PENDING_HUMAN_REVIEW"
  ) {
    return "approval_required";
  }
  if (severity === "warning" || severity === "attention") {
    return "attention";
  }
  return "informational";
}

export function pulsePriority(kind: PulseNoticeKind): number {
  switch (kind) {
    case "critical":
      return 400;
    case "approval_required":
      return 300;
    case "attention":
      return 200;
    case "informational":
      return 100;
  }
}

const lifecyclePhaseByStatus: Record<
  RuntimeEventStatus,
  LifecyclePhase
> = {
  NEW: "detected",
  ANALYZED: "analysis",
  PENDING_HUMAN_REVIEW: "review",
  APPROVED: "review",
  TASK_CREATED: "task",
  IN_PROGRESS: "task",
  EVIDENCE_SUBMITTED: "evidence",
  UNDER_REVIEW: "evidence",
  CLOSED: "resolved",
  REJECTED: "review",
  NEEDS_MORE_EVIDENCE: "evidence",
  FAILED: "failed",
  CANCELLED: "resolved",
  ESCALATED: "review",
};

function statusLabelByPhase(
  phase: LifecyclePhase,
  status: RuntimeEventStatus,
): ViewText {
  if (
    status === "NEEDS_MORE_EVIDENCE" ||
    status === "FAILED" ||
    status === "CANCELLED" ||
    status === "ESCALATED"
  ) {
    return literalText(status);
  }
  if (status === "NEW") {
    return messageText("status.NEW");
  }
  if (status === "PENDING_HUMAN_REVIEW") {
    return messageText("status.PENDING_HUMAN_REVIEW");
  }
  if (status === "APPROVED") {
    return messageText("status.APPROVED");
  }
  if (status === "REJECTED") {
    return messageText("status.REJECTED");
  }
  if (status === "TASK_CREATED") {
    return messageText("status.TASK_CREATED");
  }
  if (status === "CLOSED") {
    return messageText("status.CLOSED");
  }

  switch (phase) {
    case "detected":
      return messageText("status.NEW");
    case "analysis":
      return messageText("status.ANALYZING");
    case "review":
      return messageText("lifecycle.review");
    case "task":
      return messageText("status.TASK_RUNNING");
    case "evidence":
      return messageText("status.WAITING_EVIDENCE");
    case "resolved":
      return messageText("lifecycle.closed");
    case "failed":
      return literalText(status);
  }
}
