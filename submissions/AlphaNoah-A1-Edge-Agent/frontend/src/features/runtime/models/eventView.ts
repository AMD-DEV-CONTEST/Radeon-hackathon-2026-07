import type {
  DataQuality,
  PresentationSeverity,
  ViewText,
} from "./viewText";

export type RuntimeEventStatus =
  | "NEW"
  | "ANALYZED"
  | "PENDING_HUMAN_REVIEW"
  | "APPROVED"
  | "TASK_CREATED"
  | "IN_PROGRESS"
  | "EVIDENCE_SUBMITTED"
  | "UNDER_REVIEW"
  | "CLOSED"
  | "REJECTED"
  | "NEEDS_MORE_EVIDENCE"
  | "FAILED"
  | "CANCELLED"
  | "ESCALATED";

export type LifecyclePhase =
  | "detected"
  | "analysis"
  | "review"
  | "task"
  | "evidence"
  | "resolved"
  | "failed";

export interface EventView {
  readonly id: string;
  readonly title: ViewText;
  readonly detail: ViewText | null;
  readonly sourceLabel: ViewText | null;
  readonly occurredAt: string | null;
  readonly occurredLabel: ViewText | null;
  readonly location: ViewText | null;
  readonly assetId: string | null;
  readonly runtimeStatus: RuntimeEventStatus | "UNKNOWN";
  readonly rawRuntimeStatus: string;
  readonly statusLabel: ViewText;
  readonly lifecyclePhase: LifecyclePhase;
  readonly severity: PresentationSeverity;
  readonly rawSeverity: string | null;
  readonly severityLabel: ViewText;
  readonly requiresHumanAction: boolean;
  readonly isTerminal: boolean;
  readonly actionSummaryId: string | null;
  readonly quality: DataQuality;
}
