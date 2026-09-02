import type {
  DataQuality,
  ViewText,
} from "../../runtime";

export type DigitalEmployeeStage =
  | "intern"
  | "trial"
  | "production"
  | "paused"
  | "retired";

export type DigitalEmployeeOperationalStatus =
  | "online"
  | "offline"
  | "working"
  | "unknown";

export type DigitalEmployeeDisplayTone =
  | "info"
  | "attention"
  | "warning"
  | "critical"
  | "success";

export interface DigitalEmployeeStateProjection<
  TValue extends string,
> {
  readonly value: TValue | "unknown";
  readonly raw: string | null;
  readonly label: ViewText;
  readonly tone: DigitalEmployeeDisplayTone;
}

export interface ResponsibilityView {
  readonly id: string;
  readonly label: ViewText;
  readonly scope: ViewText | null;
  readonly quality: DataQuality;
}

export interface CapabilityModule {
  readonly id: string;
  readonly name: ViewText;
  readonly description: ViewText | null;
  readonly availability:
    | "available"
    | "limited"
    | "unavailable"
    | "unknown";
  readonly availabilityLabel: ViewText;
  readonly availabilityTone: DigitalEmployeeDisplayTone;
  readonly sourceSkill: {
    readonly skillId: string;
    readonly version: string;
  } | null;
  readonly quality: DataQuality;
}

export interface CurrentTaskView {
  readonly id: string;
  readonly title: ViewText;
  readonly runtimeStatus: string | null;
  readonly statusLabel: ViewText;
  readonly statusTone: DigitalEmployeeDisplayTone;
  readonly updatedAt: string | null;
  readonly eventId: string | null;
  readonly quality: DataQuality;
}

export interface TodayMetricsView {
  readonly handled: number | null;
  readonly pending: number | null;
  readonly windowStartedAt: string | null;
  readonly observedAt: string | null;
  readonly quality: DataQuality;
}

export type WorkRecordKind =
  | "event_detected"
  | "analysis"
  | "knowledge_lookup"
  | "human_review"
  | "task"
  | "evidence"
  | "completed"
  | "unknown";

export interface WorkRecord {
  readonly id: string;
  readonly occurredAt: string | null;
  readonly occurredLabel: ViewText | null;
  readonly title: ViewText;
  readonly detail: ViewText | null;
  readonly kind: WorkRecordKind;
  readonly eventId: string | null;
  readonly taskId: string | null;
  readonly rawAction: string | null;
  readonly quality: DataQuality;
}

export interface KnowledgeScopeView {
  readonly id: string;
  readonly label: ViewText;
  readonly sourceType:
    | "skill_hint"
    | "event_provenance"
    | "product_projection"
    | "unknown";
  readonly quality: DataQuality;
}

export interface PermissionSummaryView {
  readonly mode: "read_only" | "human_confirmed" | "unknown";
  readonly label: ViewText;
  readonly constraints: readonly ViewText[];
  readonly isAuthoritative: false;
  readonly quality: DataQuality;
}

export interface DigitalEmployeeView {
  readonly id: string;
  readonly name: ViewText;
  readonly description: ViewText | null;

  readonly status: DigitalEmployeeOperationalStatus;
  readonly rawStatus: string | null;
  readonly statusLabel: ViewText;
  readonly statusTone: DigitalEmployeeDisplayTone;
  readonly statusObservedAt: string | null;
  readonly currentEventId: string | null;

  readonly stage: DigitalEmployeeStage | "unknown";
  readonly rawStage: string | null;
  readonly stageLabel: ViewText;
  readonly stageTone: DigitalEmployeeDisplayTone;

  readonly responsibilities: readonly ResponsibilityView[];
  readonly skills: readonly CapabilityModule[];
  readonly currentTasks: readonly CurrentTaskView[];
  readonly todayMetrics: TodayMetricsView;
  readonly workRecords: readonly WorkRecord[];
  readonly knowledge: readonly KnowledgeScopeView[];
  readonly permissionSummary: PermissionSummaryView;

  readonly quality: DataQuality;
}

export interface DigitalEmployeeCollection {
  readonly source: "mock" | "http";
  readonly employees: readonly DigitalEmployeeView[];
  readonly observedAt: string | null;
  readonly quality: DataQuality;
}
