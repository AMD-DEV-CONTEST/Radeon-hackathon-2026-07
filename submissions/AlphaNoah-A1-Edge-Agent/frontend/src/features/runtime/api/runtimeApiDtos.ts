/**
 * Current Web Adapter wire contracts. These names deliberately remain
 * snake_case and are not re-exported from the runtime feature barrel.
 */
export interface RuntimeAnalysisDto {
  readonly detected_issue: string;
  readonly decision_type: string;
  readonly reasoning_summary: string;
  readonly evidence: readonly string[];
  readonly model_or_rule: string;
  readonly confidence: number;
  readonly requires_human_review: boolean;
  readonly severity: string;
}

export interface RuntimeEventDetailDto {
  readonly event_id: string;
  readonly status: string;
  readonly skill_id: string | null;
  readonly skill_version: string | null;
  readonly analysis: RuntimeAnalysisDto | null;
  readonly decision: {
    readonly decision_id: string;
    readonly status: string;
    readonly requires_human_review: boolean;
  } | null;
}

export interface RuntimeTaskDto {
  readonly event_id: string;
  readonly task: {
    readonly task_id: string;
    readonly status: string;
    readonly owner: string;
  } | null;
}

export interface RuntimeTimelineEntryDto {
  readonly sequence: number;
  readonly timestamp: string;
  readonly action: string;
  readonly entity_type: string;
  readonly entity_id: string;
  readonly status: string;
}

export interface RuntimeApiErrorDto {
  readonly error_code: string;
  readonly message: string;
}

export type RuntimeProjectionSeverityDto =
  | "UNKNOWN"
  | "LOW"
  | "MEDIUM"
  | "HIGH"
  | "CRITICAL";

export interface RuntimeResponsibilityProjectionDto {
  readonly id: string;
  readonly name: string;
}

export interface RuntimeEventProjectionDto {
  readonly id: string;
  readonly type: string;
  readonly status: string;
  readonly timestamp: string;
  readonly severity: RuntimeProjectionSeverityDto;
  readonly location: string;
  readonly asset_id: string;
  readonly description: string;
  readonly responsibility: RuntimeResponsibilityProjectionDto | null;
}

export interface RuntimePulseProjectionDto {
  readonly level: "attention" | "critical";
  readonly title: string;
  readonly event_id: string;
}

export interface RuntimeDigitalEmployeeProjectionDto {
  readonly id: string;
  readonly name: string;
  readonly status: "working" | "unknown";
  readonly current_event_id: string | null;
  readonly responsibility: string;
  readonly skills: readonly {
    readonly name: string;
  }[];
}

export interface RuntimeWorkspaceProjectionDto {
  readonly version: "workspace-v1";
  readonly events: readonly RuntimeEventProjectionDto[];
  readonly active_event: RuntimeEventProjectionDto | null;
  readonly pulse: RuntimePulseProjectionDto | null;
  readonly employees: readonly RuntimeDigitalEmployeeProjectionDto[];
}
