export type M3ArtifactState =
  | 'NEEDS_INPUT'
  | 'REVIEW_READY'
  | 'CONFIRMED'
  | 'COMPLETE_WITH_GAPS'
  | 'INVALIDATED';

export type LedgerRole =
  | 'ALTERNATIVE'
  | 'REASON'
  | 'DECISION'
  | 'ACTION'
  | 'OBSERVED_RESULT';

export type StatementStatus =
  | 'SOURCE_FACT'
  | 'USER_JUDGMENT'
  | 'AGENT_INFERENCE'
  | 'UNRESOLVED';

export type EvidenceDisposition = 'SUPPORTED' | 'CONFLICTING' | 'UNRESOLVED';
export type EvidenceStrength = 'DIRECT' | 'INDIRECT' | 'SELF_REPORTED' | 'NONE';
export type ConfirmationState = 'UNCONFIRMED' | 'CONFIRMED' | 'CORRECTED' | 'REJECTED';

export interface LedgerStatementV1 {
  statement_id: string;
  role: LedgerRole;
  text: string;
  status: StatementStatus;
  evidence_disposition: EvidenceDisposition;
  evidence_strength: EvidenceStrength;
  confirmation: ConfirmationState;
  confirmed_at: string | null;
  source_moment_ids: string[];
  source_statement_ids: string[];
  derived_from_statement_ids: string[];
  unresolved_reason: string | null;
}

export interface DecisionLedgerEntryV1 {
  decision_id: string;
  title: string;
  source_moment_ids: string[];
  statements: LedgerStatementV1[];
}

export interface DecisionEvidenceLedgerV1 {
  schema_version: '0.1.0';
  artifact_id: string;
  asset_id: string;
  base_m2_artifact_id: string;
  base_canonical_version_id: string;
  generated_by_run_id: string;
  state: M3ArtifactState;
  entries: DecisionLedgerEntryV1[];
  dependency_moment_ids: string[];
  dependency_statement_ids: string[];
  unresolved_question_ids: string[];
  created_at: string;
  updated_at: string;
  invalidated_by_m2_artifact_id: string | null;
  invalidated_by_canonical_version_id: string | null;
  invalidation_reason: string | null;
  affected_entry_ids: string[];
  affected_dependency_refs: string[];
  reusable_entry_ids: string[];
}

export interface M3EvidenceMomentV1 {
  moment_id: string;
  title: string;
  description: string;
}

export interface M3EvidenceStatementV1 {
  statement_id: string;
  text: string;
  source_labels: string[];
}

export type ProgressState = 'QUEUED' | 'RUNNING' | 'WAITING_FOR_USER' | 'TERMINAL';

export type M3ProgressStage =
  | 'LOAD_CONTEXT'
  | 'PLAN_LEDGER'
  | 'VALIDATE_OUTPUT'
  | 'REPAIR_OUTPUT'
  | 'EVALUATE_TOOL_POLICY'
  | 'PERSIST_LEDGER'
  | 'VERIFY_LEDGER'
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

export interface M3ProgressV1 {
  schema_version: '1.0.0';
  stage: M3ProgressStage;
  state: ProgressState;
  structured_repairs_used: number;
  structured_repair_budget: 2;
  replans_used: number;
  replan_budget: 1;
  model_calls_used: number;
  model_call_budget: 4;
  last_durable_artifact_id: string | null;
  safe_message: string;
  occurred_at: string;
  terminal_state: TerminalState | null;
}

export type M3FailureCode =
  | 'UPSTREAM_STALE'
  | 'INVALID_MODEL_OUTPUT'
  | 'STRUCTURED_REPAIR_EXHAUSTED'
  | 'TOOL_NOT_ALLOWLISTED'
  | 'INVALID_TOOL_ARGUMENTS'
  | 'FORGED_TOOL_PERMISSION'
  | 'PERMISSION_DENIED'
  | 'STORAGE_ERROR'
  | 'VERIFICATION_FAILED'
  | 'REPLAN_EXHAUSTED'
  | 'MODEL_CALL_BUDGET_EXHAUSTED'
  | 'MODEL_UNAVAILABLE'
  | 'MODEL_TIMED_OUT'
  | 'INTERNAL_ERROR';

export interface M3FailureV1 {
  code: M3FailureCode;
  terminal_state: TerminalState;
  retryable: boolean;
  safe_user_message: string;
  recovery_action: string;
  finding_codes: string[];
  occurred_at: string;
}

export interface M3WorkspaceV1 {
  artifact: DecisionEvidenceLedgerV1;
  is_current: boolean;
  history_artifact_ids: string[];
  evidence_moments: M3EvidenceMomentV1[];
  evidence_statements: M3EvidenceStatementV1[];
  progress: M3ProgressV1;
  latest_failure: M3FailureV1 | null;
  allowed_actions: Array<'EDIT' | 'CONFIRM' | 'REGENERATE'>;
}
