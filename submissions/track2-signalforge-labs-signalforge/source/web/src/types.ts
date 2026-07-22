export type ScenarioControl = {
  rates: "higher_for_longer" | "easing";
  ai_spending: "slower" | "resilient";
};

export type WorkspaceConfig = {
  mode: "fixture" | "live";
  local_only: boolean;
  endpoint_scope: string;
  model: string;
  scenario_defaults: ScenarioControl;
  follow_ups_live: boolean;
  retention_available: boolean;
  retention_default: boolean;
};

export type RetentionView = {
  requested: boolean;
  status: "not_requested" | "pending" | "saved" | "failed" | "unavailable";
  case_id?: string;
  error_code?: string;
};

export type CaseSummary = {
  case_id: string;
  run_id: string;
  parent_run_id?: string;
  title: string;
  as_of: string;
  intent: string;
  saved_at: string;
  evidence_items: number;
  calculation_receipts: number;
  projection_sha256: string;
};

export type StoredCase = { summary: CaseSummary; case: Projection };

export type Company = { entity_id: string; label: string };

export type Section = {
  section_type: string;
  title: string;
  content: string;
  claim_refs?: string[];
  evidence_refs?: string[];
  receipt_refs?: string[];
  numerical_refs?: string[];
};

export type EvidenceCard = {
  evidence_id: string;
  source_type: string;
  document_section?: string;
  locator: string;
  content_sha256: string;
  as_of: string;
  used_in_sections: string[];
};

export type ReceiptOutput = {
  output_id: string;
  quantity: { value: string; unit: string };
  status: string;
};

export type CalculationCard = {
  receipt_id: string;
  operation_id: string;
  engine_id: string;
  engine_version: string;
  formula_version: string;
  status: string;
  outputs: ReceiptOutput[];
  invariant_results: Array<{ invariant_id: string; passed: boolean }>;
  warnings?: string[];
  evidence_refs?: string[];
  source_as_of: string;
  receipt_sha256: string;
  used_in_sections: string[];
};

export type SafeEvent = {
  sequence: number;
  run_id?: string;
  step_id?: string;
  type: string;
  status: string;
  label?: string;
  at: string;
  attributes?: Record<string, string>;
};

export type Projection = {
  schema_version: string;
  case_id: string;
  run_id: string;
  request_id: string;
  status: string;
  title: string;
  question: string;
  as_of: string;
  intent: string;
  companies: Company[];
  sections: Section[];
  evidence: EvidenceCard[];
  calculations: CalculationCard[];
  assumptions?: string[];
  limitations?: string[];
  next_actions?: string[];
  warnings?: Array<{ kind: string; role_id?: string; text: string }>;
  events: SafeEvent[];
  execution: {
    local_only: boolean;
    endpoint_scope: string;
    model: string;
    runtime_label: string;
  };
  metrics: {
    duration_ms: number;
    model_calls: number;
    context_packets: number;
    critiques: number;
    claims: number;
    supported_claims: number;
    evidence_coverage: number;
    required_sections: number;
    present_required_sections: number;
    max_concurrent_context: number;
  };
  follow_up_suggestions: Array<{ suggestion_id: string; label: string; question: string }>;
};

export type RunView = {
  run_id: string;
  parent_run_id?: string;
  status: "running" | "completed" | "failed" | "cancelled";
  started_at: string;
  completed_at?: string;
  result?: Projection;
  failure?: { code: string; retryable: boolean };
  retention: RetentionView;
};
