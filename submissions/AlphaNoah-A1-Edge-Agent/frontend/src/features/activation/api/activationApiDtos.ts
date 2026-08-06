export const DEMO_ACTIVATION_PROJECTION_VERSION = "f03c-demo-v1";
export const DEMO_ACTIVATION_SCENARIO =
  "synthetic-restaurant-aircon-a08";

export interface DemoActivationRequestDto {
  readonly scenario_id: typeof DEMO_ACTIVATION_SCENARIO;
  readonly description: string;
  readonly request_id: string;
}

export interface DemoActivationResponseDto {
  readonly projection_version:
    typeof DEMO_ACTIVATION_PROJECTION_VERSION;
  readonly replayed: boolean;
  readonly event: {
    readonly event_id: string;
    readonly event_type: "device_not_shutdown";
    readonly source: "demo_activation";
    readonly timestamp: string;
    readonly status: string;
    readonly severity: string;
    readonly asset_id: "A08-AIRCON";
    readonly location: "Restaurant-Private-Room-A08";
    readonly description: string;
  };
  readonly responsibility: {
    readonly owner_id: string;
    readonly owner_name: string;
    readonly match_type:
      | "asset"
      | "location"
      | "event_type"
      | "unassigned";
    readonly matched_key: string;
  };
  readonly analysis: {
    readonly detected_issue: string;
    readonly reasoning_summary: string;
    readonly confidence: number;
    readonly requires_human_review: boolean;
    readonly knowledge_sources: readonly string[];
  } | null;
  readonly notification: {
    readonly notification_id: string;
    readonly status: "CREATED" | "DELIVERED" | "FAILED";
    readonly created_at: string;
  } | null;
  readonly human_review: {
    readonly decision_id: string;
    readonly status: string;
    readonly required: boolean;
    readonly allowed_actions: readonly ("approve" | "reject")[];
  } | null;
  readonly work_records: readonly {
    readonly id: string;
    readonly sequence: number;
    readonly occurred_at: string;
    readonly kind:
      | "event_received"
      | "responsibility_matched"
      | "analysis"
      | "knowledge_lookup"
      | "human_review";
    readonly title: string;
    readonly event_id: string;
    readonly task_id: null;
  }[];
  readonly quality: {
    readonly availability: "available" | "partial" | "unavailable";
    readonly unknown_fields: readonly string[];
    readonly contract_warnings: readonly string[];
  };
}

export interface DemoActivationErrorDto {
  readonly error_code: string;
  readonly message: string;
  readonly event_id?: string;
}
