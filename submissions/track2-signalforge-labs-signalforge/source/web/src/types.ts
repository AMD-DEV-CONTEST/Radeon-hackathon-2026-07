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
  intelligence_audit: boolean;
  protected_capture: boolean;
};

export type ProductCompany = {
  company_id: string;
  display_name: string;
  primary_ticker: string;
  tickers: string[];
  research_cluster: string;
  peer_group: string;
  research_role: string;
  activation_state: string;
  research_enabled: boolean;
  reason_codes: string[];
  metric_state_count: Record<string, number>;
  profile_sha256: string;
};

export type ProductPeerLane = {
  lane_id: string;
  company_ids: string[];
  comparison_type: string;
  decision_question: string;
  allowed_question_ids: string[];
  allowed_metric_ids: string[];
  enabled: boolean;
  reason_codes: string[];
  lane_sha256: string;
};

export type ProductCatalog = {
  schema_version: "signalforge/technology20-public-catalog/v1";
  universe_id: string;
  as_of: string;
  company_policy_version: string;
  activation_policy_version: string;
  peer_lane_policy_version: string;
  source_registry_sha256: string;
  companies: ProductCompany[];
  peer_lanes: ProductPeerLane[];
  claim_boundary: string;
};

export type FinancialResult = {
  operation_id: string;
  formula_version: string;
  periods: string[];
  source_as_of: string;
  outputs: Array<{
    output_id: string;
    quantity: { value: string; unit: string; currency?: string; scale?: number };
    status: string;
  }>;
  evidence_refs: string[];
  receipt_sha256: string;
};

export type FinancialCompany = {
  company_id: string;
  primary_ticker: string;
  display_name: string;
  report_sha256: string;
  results: FinancialResult[];
  abstentions: Array<{ operation_id: string; code: string; message: string }>;
};

export type FinancialSummary = {
  schema_version: "signalforge/technology20-public-financial-summary/v1";
  universe_id: string;
  as_of: string;
  companies: FinancialCompany[];
  claim_boundary: string;
};

export type PeerEvaluation = {
  lane_id: string;
  company_ids: string[];
  receipts: Array<{
    disposition: "comparable" | "comparable_with_caveat" | "not_comparable";
    operands: Array<{ canonical_metric_id: string }>;
    required_caveat_ids?: string[];
    reason_codes?: string[];
    receipt_sha256: string;
  }>;
  abstentions: Array<{ metric_ids: string[]; code: string; message: string }>;
  releasable_metric_ids: string[];
  withheld_metric_ids: string[];
  promoted: boolean;
  reason_codes: string[];
};

export type PeerEvaluationSuite = {
  schema_version: "signalforge/technology20-peer-evaluation/v1";
  universe_id: string;
  as_of: string;
  policy_version: string;
  lanes: PeerEvaluation[];
  claim_boundary: string;
};

export type RetentionView = {
  requested: boolean;
  status: "not_requested" | "pending" | "saved" | "failed" | "unavailable" | "deleted";
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

export type ExecutionStatus =
  | "pending"
  | "ready"
  | "running"
  | "passed"
  | "failed"
  | "degraded"
  | "repairing"
  | "skipped"
  | "cancelled"
  | "withheld"
  | "unavailable";

export type ExecutionChecklistItem = {
  check_id: string;
  label: string;
  status: ExecutionStatus;
  authority: string;
  required: boolean;
  reference_ids?: string[];
  completed_at?: string;
  safe_detail?: string;
};

export type ExecutionPhase = {
  phase_id: string;
  order: number;
  safe_label: string;
  safe_objective: string;
  mandatory: boolean;
  status: ExecutionStatus;
  step_ids: string[];
  safe_summary: string;
};

export type ExecutionStep = {
  step_id: string;
  parent_step_id?: string;
  parent_phase_id: string;
  phase: string;
  kind: string;
  safe_label: string;
  safe_objective: string;
  role_id?: string;
  wave?: number;
  depends_on?: string[];
  mandatory: boolean;
  status: ExecutionStatus;
  route?: string;
  route_reason_code?: string;
  authorized_capability_ids?: string[];
  evidence_requirement_classes?: string[];
  checklist: ExecutionChecklistItem[];
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  attempt: number;
  max_attempts: number;
  reference_ids?: string[];
  failure_code?: string;
  degradation_code?: string;
  safe_summary: string;
};

export type ExecutionPlan = {
  schema_version: "signalforge/execution-plan/v1";
  run_id: string;
  request_id: string;
  plan_id?: string;
  status: ExecutionStatus;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  total_steps: number;
  terminal_steps: number;
  progress_ratio: number;
  max_parallel_specialists: number;
  current_wave?: number;
  route_summary?: string[];
  phases: ExecutionPhase[];
  steps: ExecutionStep[];
  degradation_summary?: string[];
  last_sequence: number;
  projection_sha256: string;
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
  execution_plan?: ExecutionPlan;
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
  trace_id: string;
  parent_run_id?: string;
  status: "running" | "completed" | "failed" | "cancelled";
  started_at: string;
  completed_at?: string;
  result?: Projection;
  execution_plan?: ExecutionPlan;
  failure?: { code: string; retryable: boolean };
  retention: RetentionView;
};

export type CaptureState = {
  enabled: boolean;
  available: boolean;
  status: "disabled" | "active" | "expired" | "purged" | "capacity_exceeded";
  expires_at?: string;
  stored_bytes: number;
  maximum_bytes: number;
};

export type ModelCallAudit = {
  model_call_id: string;
  step_id: string;
  role_id: string;
  role_class: string;
  provider_id: string;
  model_id: string;
  route: string;
  prompt_template_id: string;
  prompt_instance_id: string;
  system_prompt_sha256: string;
  request_payload_sha256: string;
  response_payload_sha256?: string;
  response_schema_sha256?: string;
  input_tokens: number;
  output_tokens: number;
  max_output_tokens: number;
  started_at: string;
  duration_ms: number;
  ttft_ms: number;
  finish_reason?: string;
  status: string;
  failure_code?: string;
};

export type RetrievalAudit = {
  retrieval_id: string;
  step_id: string;
  role_id: string;
  method: string;
  index_version?: string;
  query_sha256?: string;
  context_packet_id: string;
  evidence_ids: string[];
  evidence_sources?: Array<{
    evidence_id: string;
    source_type: string;
    locator: string;
    document_section?: string;
    content_sha256: string;
    as_of: string;
  }>;
  chunk_ids?: string[];
  document_ids?: string[];
  graph_traversal_ids?: string[];
  dropped_ids?: string[];
  estimated_tokens: number;
  status: string;
  completed_at: string;
};

export type EngineCallAudit = {
  engine_call_id: string;
  step_id: string;
  requested_by: string;
  engine_id: string;
  engine_version: string;
  operation_id: string;
  formula_version: string;
  receipt_id: string;
  receipt_sha256: string;
  input_refs: string[];
  output_refs: string[];
  evidence_refs?: string[];
  invariants_total: number;
  invariants_passed: number;
  status: string;
  generated_at: string;
};

export type ReviewAudit = {
  review_id: string;
  role_id: string;
  decision: string;
  repair_pass: number;
  approved_claims?: string[];
  rejected_claims?: string[];
};

export type ReleaseAudit = {
  answer_id: string;
  primary_intent: string;
  section_types: string[];
  claim_refs: string[];
  evidence_refs: string[];
  receipt_refs: string[];
  status: string;
};

export type LifecycleAudit = {
  sequence: number;
  step_id?: string;
  event_type: string;
  status: string;
  wave?: number;
  role_id?: string;
  route?: string;
  route_reason_code?: string;
  attempt?: number;
  specialist_count?: number;
  concurrency_limit?: number;
  succeeded_count?: number;
  failed_count?: number;
  observed_concurrency?: number;
  failure_code?: string;
  at: string;
};

export type IntelligenceRecord = {
  schema_version: string;
  run_id: string;
  request_id: string;
  trace_id: string;
  status: string;
  capture: CaptureState;
  started_at: string;
  completed_at?: string;
  timeline: LifecycleAudit[];
  model_calls: ModelCallAudit[];
  retrievals: RetrievalAudit[];
  engine_calls: EngineCallAudit[];
  reviews: ReviewAudit[];
  release?: ReleaseAudit;
};

export type ProtectedModelCall = {
  model_call_id: string;
  prompt_instance_id: string;
  messages: Array<{ role: string; content: string }>;
  response_format?: Record<string, unknown>;
  parameters: { model: string; max_tokens: number; temperature: number; stream: boolean };
  raw_output?: string;
};

export type ProtectedIntelligenceRecord = {
  schema_version: string;
  run_id: string;
  request_id: string;
  question: string;
  created_at: string;
  expires_at: string;
  model_calls: ProtectedModelCall[];
  receipts: Array<{ receipt_id: string; payload: unknown }>;
};
