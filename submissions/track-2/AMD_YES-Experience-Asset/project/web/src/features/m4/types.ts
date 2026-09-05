export type M4ArtifactState =
  | 'NEEDS_INPUT'
  | 'REVIEW_READY'
  | 'CONFIRMED'
  | 'COMPLETE_WITH_GAPS'
  | 'INVALIDATED';

export type InsightRole =
  | 'LESSON'
  | 'SUPPORT'
  | 'COUNTERFACTUAL'
  | 'LIMITATION'
  | 'COUNTEREXAMPLE'
  | 'APPLICABILITY';

/** Roles that carry the boundary a lesson needs before it is safe to reuse. */
export const BOUNDARY_ROLES: InsightRole[] = ['LIMITATION', 'COUNTEREXAMPLE', 'APPLICABILITY'];

export type StatementStatus =
  | 'SOURCE_FACT'
  | 'USER_JUDGMENT'
  | 'AGENT_INFERENCE'
  | 'UNRESOLVED';

export interface InsightStatementV1 {
  statement_id: string;
  role: InsightRole;
  text: string;
  status: StatementStatus;
  source_statement_ids: string[];
  source_decision_ids: string[];
  is_visible_gap: boolean;
  gap_reason: string | null;
}

export interface InsightEntryV1 {
  insight_id: string;
  title: string;
  source_decision_ids: string[];
  statements: InsightStatementV1[];
}

export interface InsightBoundaryMapV1 {
  schema_version: '0.1.0';
  artifact_id: string;
  asset_id: string;
  base_m3_artifact_id: string;
  base_canonical_version_id: string;
  generated_by_run_id: string;
  state: M4ArtifactState;
  entries: InsightEntryV1[];
  dependency_decision_ids: string[];
  dependency_statement_ids: string[];
  unresolved_question_ids: string[];
  created_at: string;
  updated_at: string;
  invalidated_by_m3_artifact_id: string | null;
  invalidated_by_canonical_version_id: string | null;
  invalidation_reason: string | null;
  affected_insight_ids: string[];
  reusable_insight_ids: string[];
}

export interface M4EvidenceStatementV1 {
  statement_id: string;
  text: string;
  status: StatementStatus;
  source_refs: string[];
}

export type ProgressState = 'QUEUED' | 'RUNNING' | 'WAITING_FOR_USER' | 'TERMINAL';

export type M4ProgressStage =
  | 'LOAD_CONTEXT'
  | 'PLAN_INSIGHTS'
  | 'VALIDATE_OUTPUT'
  | 'REPAIR_OUTPUT'
  | 'PERSIST_MAP'
  | 'VERIFY_MAP'
  | 'REPLAN'
  | 'TERMINAL';

export type TerminalState =
  | 'SUCCEEDED'
  | 'NEEDS_USER_INPUT'
  | 'PAUSED'
  | 'CANCELLED'
  | 'TIMED_OUT'
  | 'MODEL_UNAVAILABLE'
  | 'MODEL_OOM'
  | 'INVALID_MODEL_OUTPUT'
  | 'STORAGE_ERROR'
  | 'POLICY_BLOCKED'
  | 'DELETION_FAILED'
  | 'INTERNAL_ERROR';

export type M4FailureCode =
  | 'UPSTREAM_STALE'
  | 'INVALID_MODEL_OUTPUT'
  | 'STRUCTURED_REPAIR_EXHAUSTED'
  | 'MODEL_CONTEXT_BUDGET_EXCEEDED'
  | 'PERMISSION_DENIED'
  | 'STORAGE_ERROR'
  | 'MODEL_UNAVAILABLE'
  | 'MODEL_TIMED_OUT';

export interface M4ProgressV1 {
  schema_version: '1.0.0';
  run_id: string;
  asset_id: string;
  sequence: number;
  stage: M4ProgressStage;
  state: ProgressState;
  message: string;
  occurred_at: string;
}

export interface M4FailureV1 {
  schema_version: '1.0.0';
  run_id: string;
  asset_id: string;
  failure_code: M4FailureCode;
  terminal_state: TerminalState;
  retryable: boolean;
  safe_user_message: string;
  last_durable_artifact_id: string | null;
  occurred_at: string;
}

export interface M4RunStatusV1 {
  schema_version: '1.0.0';
  run_id: string;
  asset_id: string;
  state: ProgressState;
  progress: M4ProgressV1 | null;
  failure: M4FailureV1 | null;
}

export interface M4WorkspaceV1 {
  schema_version: '1.0.0';
  asset_id: string;
  canonical_version_id: string;
  canonical_content_hash: string;
  map: InsightBoundaryMapV1 | null;
  evidence_statements: M4EvidenceStatementV1[];
  run_status: M4RunStatusV1 | null;
}
