/**
 * TypeScript mirror of the checked-in E1-A public contracts.
 *
 * Source of truth: `web/contracts/` (vendored verbatim from final
 * `main@431e1a5` E1-A contracts — see `web/contracts/PROVENANCE.md`). These types
 * are NOT a fork of the backend schema: `contract.test.ts` validates public mock
 * fixtures against every relevant vendored JSON Schema with Ajv.
 *
 * The UI must never invent fields the contract does not define. Model output and
 * tool-call proposals never grant execution permission.
 */

export const CANONICAL_SCHEMA_VERSION = '1.0.0' as const;

/* ------------------------------------------------------------------ */
/* Health (OpenAPI: HealthStatusV1, GET /api/v1/health)               */
/* ------------------------------------------------------------------ */

export type HealthOverall = 'ok' | 'degraded';
export type DatabaseStatus = 'ok' | 'unavailable' | 'not_configured';
export type GpuViability = 'VERIFIED' | 'NOT_VERIFIED' | 'BLOCKED';

export interface HealthStatusV1 {
  status: HealthOverall;
  service?: 'experience-asset-agent';
  app_version: string;
  canonical_schema_version?: typeof CANONICAL_SCHEMA_VERSION;
  inference_mode?: 'local_only';
  database: DatabaseStatus;
  model_endpoint: string;
  model_profile: string;
  gpu_viability: GpuViability;
  checked_at: string;
}

/* ------------------------------------------------------------------ */
/* Progress (progress-event-v1.schema.json)                           */
/* ------------------------------------------------------------------ */

export type ProgressState = 'QUEUED' | 'RUNNING' | 'WAITING_FOR_USER' | 'TERMINAL';

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

export interface ProgressEventV1 {
  event_id: string;
  run_id: string;
  asset_id?: string | null;
  version_id?: string | null;
  sequence: number;
  stage: string;
  state: ProgressState;
  terminal_state?: TerminalState | null;
  percent?: number | null;
  percent_basis?: 'milestones_done/milestones_total' | null;
  milestones_done?: number | null;
  milestones_total?: number | null;
  internal_completed_units?: number | null;
  internal_total_units?: number | null;
  eta_seconds?: number | null;
  eta_basis?: string | null;
  eta_history_sample_size?: number | null;
  message: string;
  occurred_at: string;
  schema_version?: typeof CANONICAL_SCHEMA_VERSION;
}

/* ------------------------------------------------------------------ */
/* Terminal result (terminal-result-v1.schema.json)                   */
/* ------------------------------------------------------------------ */

export interface TerminalResultV1 {
  run_id: string;
  state: TerminalState;
  retryable: boolean;
  safe_user_message: string;
  recovery_action: string;
  last_durable_version_id?: string | null;
  internal_error_class?: string | null;
  elapsed_ms: number;
  model_call_count: number;
  finished_at: string;
  schema_version?: typeof CANONICAL_SCHEMA_VERSION;
}

/* ------------------------------------------------------------------ */
/* Structured proposal (structured-proposal-v1.schema.json)           */
/* ------------------------------------------------------------------ */

export interface ToolCallProposal {
  name: string;
  arguments: Record<string, unknown>;
  requested_reason: string;
  /** Always false in a proposal: model output never grants execution. */
  permission_granted: false;
}

export interface StructuredProposalV1 {
  summary: string;
  proposed_statements: unknown[];
  questions: unknown[];
  tool_call_proposals: ToolCallProposal[];
  schema_version?: typeof CANONICAL_SCHEMA_VERSION;
}

/* ------------------------------------------------------------------ */
/* Durable Agent run contracts (AgentRunStateV1 and component schemas) */
/* ------------------------------------------------------------------ */

export type PlanStepKind =
  | 'RETRIEVE'
  | 'ASK'
  | 'EXTRACT'
  | 'CLASSIFY'
  | 'UPDATE_ARTIFACT'
  | 'VERIFY'
  | 'EVALUATE_ROUTE'
  | 'PRIVACY_REVIEW'
  | 'RENDER';

export type PlanStepStatus =
  | 'PENDING'
  | 'IN_PROGRESS'
  | 'SUCCEEDED'
  | 'DENIED'
  | 'FAILED'
  | 'SKIPPED';

export type AgentRetrievalScope =
  | 'CURRENT_SOURCE'
  | 'CROSS_ASSET_SUMMARY'
  | 'CROSS_ASSET_DETAIL';

export interface WorkPlanStepV1 {
  step_id: string;
  step_kind: PlanStepKind;
  reason: string;
  dependency_step_ids?: string[];
  required_evidence_refs?: string[];
  required_permission?: string | null;
  status?: PlanStepStatus;
  stop_condition: string;
}

export interface WorkPlanV1 {
  plan_id: string;
  run_id: string;
  milestone: Milestone;
  goal: string;
  steps: WorkPlanStepV1[];
  revision: number;
  created_at: string;
  revised_at: string;
}

export interface RetrievedEvidenceReference {
  retrieval_id: string;
  scope: AgentRetrievalScope;
  asset_id: string;
  version_id?: string | null;
  source_id?: string | null;
  span_id?: string | null;
  related_asset_id?: string | null;
  provenance_ref: string;
  content_hash: string;
  no_match?: boolean;
}

export interface RuntimeToolCallProposal {
  proposal_id: string;
  name: string;
  arguments: Record<string, unknown>;
  base_version_id: string;
  knowledge_card_version_id?: string | null;
  knowledge_card_hash?: string | null;
  proposed_at: string;
  permission_granted?: false;
}

export interface ConfirmedRelationBinding {
  relation_id: string;
  related_asset_id: string;
}

export interface PolicyDecision {
  decision_id: string;
  run_id: string;
  proposal_id: string;
  outcome: 'ALLOW' | 'DENY';
  reason_codes: string[];
  policy_version: string;
  decided_at: string;
}

export interface ToolExecutionRecord {
  execution_id: string;
  run_id: string;
  proposal_id: string;
  policy_decision_id: string;
  tool_name: string;
  sanitized_argument_hash: string;
  status: 'SUCCEEDED' | 'DENIED' | 'FAILED' | 'TIMED_OUT';
  observation_refs?: string[];
  error_class?: string | null;
  started_at: string;
  finished_at: string;
}

export interface VerificationReport {
  verification_id: string;
  run_id: string;
  execution_id?: string | null;
  outcome: 'VERIFIED' | 'NEEDS_INPUT' | 'REPLAN' | 'REJECTED';
  checks: Record<string, boolean>;
  finding_codes?: string[];
  safe_summary: string;
  verified_at: string;
}

export interface AgentRunStateV1 {
  schema_version?: typeof CANONICAL_SCHEMA_VERSION;
  run_id: string;
  asset_id: string;
  base_version_id: string;
  command_id: string;
  user_goal: string;
  acceptance_checks: string[];
  permission_snapshot: Record<string, boolean>;
  current_milestone: Milestone;
  work_plan: WorkPlanV1;
  retrieval_scope: AgentRetrievalScope;
  knowledge_card_version_id?: string | null;
  knowledge_card_hash?: string | null;
  relation_candidate_ids?: string[];
  confirmed_relation_ids?: string[];
  confirmed_related_asset_ids?: string[];
  confirmed_relation_bindings?: ConfirmedRelationBinding[];
  retrieved_evidence?: RetrievedEvidenceReference[];
  tool_proposals?: RuntimeToolCallProposal[];
  policy_decisions?: PolicyDecision[];
  tool_executions?: ToolExecutionRecord[];
  structured_proposal_hash?: string | null;
  validation_findings?: string[];
  verification_report?: VerificationReport | null;
  step_budget: number;
  model_call_budget: number;
  retry_budget: number;
  steps_used: number;
  model_calls_used: number;
  retries_used: number;
  model_id: string;
  server_base_url: string;
  last_durable_version_id: string;
  terminal_state?: TerminalState | null;
  updated_at: string;
}

/* ------------------------------------------------------------------ */
/* Canonical Experience Asset (experience-asset-v1.schema.json)       */
/* Only the fields the E1-B status shell reads are modelled here.      */
/* Unknown fields are preserved by treating the payload as a superset. */
/* ------------------------------------------------------------------ */

export type Milestone = 'M1' | 'M2' | 'M3' | 'M4' | 'M5';

export type MilestoneStateValue =
  | 'NOT_STARTED'
  | 'IN_PROGRESS'
  | 'NEEDS_INPUT'
  | 'REVIEW_READY'
  | 'CONFIRMED'
  | 'COMPLETE_WITH_GAPS'
  | 'INVALIDATED'
  | 'FAILED';

export type AssetLifecycle =
  | 'ACTIVE'
  | 'PAUSED'
  | 'ROUTE_REVIEW'
  | 'EXPORT_READY'
  | 'DELETION_PENDING'
  | 'DELETED';

export type StatementStatus =
  | 'SOURCE_FACT'
  | 'USER_JUDGMENT'
  | 'AGENT_INFERENCE'
  | 'UNRESOLVED';

export type ConfirmationState = 'UNCONFIRMED' | 'CONFIRMED' | 'CORRECTED' | 'REJECTED';

export type QuestionState = 'OPEN' | 'ANSWERED' | 'SKIPPED' | 'DEFERRED';

export type RouteType =
  | 'PRIVATE_SELF'
  | 'BEGINNER'
  | 'PEER'
  | 'CUSTOMER_EVALUATOR'
  | 'PUBLIC';

export type RouteEligibility =
  | 'ELIGIBLE'
  | 'INELIGIBLE'
  | 'ELIGIBLE_AFTER_PRIVACY_APPROVAL'
  | 'BLOCKED';

export type ExportFormat = 'HTML' | 'MARKDOWN' | 'JSON';
export type ExportState = 'CURRENT' | 'SUPERSEDED' | 'BLOCKED' | 'FAILED' | 'DELETED';

export interface VersionLineage {
  version_id: string;
  parent_version_id?: string | null;
  change_kind: string;
  change_reason: string;
  created_at: string;
  derived_by_run_id?: string | null;
  schema_version?: typeof CANONICAL_SCHEMA_VERSION;
}

export interface Statement {
  statement_id: string;
  text: string;
  status: StatementStatus;
  confirmation?: ConfirmationState;
  evidence_strength?: 'DIRECT' | 'INDIRECT' | 'SELF_REPORTED' | 'NONE';
  source_refs?: unknown[];
  derived_from?: string[];
  sensitivity_tags?: string[];
  created_in_version: string;
  last_changed_in_version: string;
}

export interface QuestionRecord {
  question_id: string;
  question: string;
  why_it_matters: string;
  milestone: Milestone;
  state?: QuestionState;
  affected_statement_ids?: string[];
  created_by_run_id: string;
  created_in_version_id: string;
}

export interface RouteDecision {
  route: RouteType;
  eligibility: RouteEligibility;
  explanation: string;
  reason_codes?: string[];
  supporting_statement_ids?: string[];
  missing_statement_ids?: string[];
  canonical_version_id: string;
  policy_version: string;
  model_run_id?: string | null;
}

export interface MilestoneArtifact {
  artifact_id: string;
  artifact_type: string;
  asset_id: string;
  version_id: string;
  milestone: Milestone;
  state: MilestoneStateValue;
  statement_ids?: string[];
  unresolved_question_ids?: string[];
  generated_by_run_id: string;
  user_review_status?: 'NOT_REVIEWED' | 'ACCEPTED' | 'ACCEPTED_WITH_GAPS' | 'REJECTED';
  invalidated_by_version_id?: string | null;
  created_at: string;
  updated_at: string;
  payload?: Record<string, unknown>;
}

export interface ExportRecord {
  export_id: string;
  asset_id: string;
  version_id: string;
  route: RouteType;
  route_draft_hash: string;
  format: ExportFormat;
  file_hash: string;
  path: string;
  created_at: string;
  state: ExportState;
}

/* ------------------------------------------------------------------ */
/* E5 relation ledger (relation-workspace-v1.schema.json et al.)        */
/*                                                                      */
/* Relation state no longer lives on the Experience Asset snapshot. The  */
/* snapshot is immutable and content-hashed, so persisting a             */
/* confirmation there would append a content version and change the      */
/* hash — while the non-contamination invariant requires that hash       */
/* identical before and after a relation read.                          */
/*                                                                      */
/* `RelationWorkspaceV1` is the read-only composition the API serves     */
/* instead. It is never written back into the snapshot, so reading a     */
/* relation cannot change the asset.                                     */
/* ------------------------------------------------------------------ */

/** Closed relation vocabulary. A model-invented synonym would read as a
 *  distinct relation to the user while carrying no admissibility rule. */
export type RelationType =
  | 'SAME_THEME'
  | 'METHOD_REUSE'
  | 'COUNTEREXAMPLE'
  | 'SUPPLEMENT'
  | 'PREREQUISITE'
  | 'FOLLOW_UP';

/** `NO_MATCH` is a semantic claim and is cached; `TECHNICAL_FAILURE` is not.
 *  Collapsing them would make an outage indistinguishable from a proven
 *  absence of relation, and the cache would preserve the outage forever. */
export type DiscoveryOutcome =
  | 'NOT_READY'
  | 'RUNNING'
  | 'CANDIDATE'
  | 'NO_MATCH'
  | 'TECHNICAL_FAILURE'
  | 'STALE';

export type DiscoveryFailureClass =
  | 'MODEL_UNAVAILABLE'
  | 'MODEL_TIMED_OUT'
  | 'MALFORMED_MODEL_OUTPUT'
  | 'RUNTIME_VALIDATION_REJECTED'
  | 'STORAGE_CONFLICT'
  | 'STALE_BINDING';

export type RelationLifecycle =
  | 'PROPOSED'
  | 'CONFIRMED'
  | 'DECLINED'
  | 'STALE'
  | 'INVALIDATED';

export type ProjectionLifecycle = 'BUILDING' | 'ACTIVE' | 'STALE' | 'INVALIDATED';

/** Readiness has no BUILDING: it is minted whole by one explicit acceptance.
 *  Reusing ProjectionLifecycle let a card claim CONFIRMED while sitting in
 *  BUILDING, which two consumers could read as opposite answers. */
export type ReadinessLifecycle = 'ACTIVE' | 'STALE' | 'INVALIDATED';

/** A confirmed relation exists only because a confirmation happened, so
 *  PROPOSED and DECLINED — which belong to a candidate — cannot apply. */
export type ConfirmedRelationLifecycle = 'CONFIRMED' | 'STALE' | 'INVALIDATED';

export type ProjectionEdgeType =
  | 'HAS_CUE'
  | 'HAS_CHANGE'
  | 'HAS_SURPRISE'
  | 'HAS_CONFLICT'
  | 'HAS_ALTERNATIVE'
  | 'HAS_REASON'
  | 'HAS_ACTION'
  | 'HAS_RESULT'
  | 'HAS_EVIDENCE'
  | 'HAS_SUPPORT'
  | 'HAS_COUNTERFACTUAL'
  | 'HAS_LIMITATION'
  | 'HAS_COUNTEREXAMPLE'
  | 'HAS_APPLICABILITY';

/** Sidecar readiness, keyed by asset, version and card hash rather than
 *  stored on the snapshot it describes. */
export interface KnowledgeCardReadinessRecordV1 {
  schema_version?: '1.0.0';
  readiness_id: string;
  asset_id: string;
  version_id: string;
  m4_artifact_id: string;
  knowledge_card_hash: string;
  milestone_state: 'CONFIRMED' | 'COMPLETE_WITH_GAPS';
  explicit_user_acceptance?: true;
  accepted_gap_statement_ids?: string[];
  accepted_at: string;
  lifecycle?: ReadinessLifecycle;
  invalidated_at?: string | null;
  invalidation_reason?: string | null;
}

/** Roles are absent together for a root-to-root mapping, which is what
 *  SAME_THEME claims, and present together for a role-level relation. A mapping
 *  pairing a root with a member describes a correspondence between things of
 *  different kinds, which no relation type defines. */
export interface RelationNodeMappingV1 {
  current_node_id: string;
  historical_node_id: string;
  /** Optional as well as nullable: the schema does not require the keys, and
   *  the backend reads an omitted role as a root mapping. Requiring them here
   *  would reject an object the product accepts. */
  current_role?: ProjectionEdgeType | null;
  historical_role?: ProjectionEdgeType | null;
}

/** Side-attributed provenance. A flat reference list cannot say which asset a
 *  reference belongs to, and an explanation that cannot be attributed to both
 *  sides is not bilateral. */
export interface RelationProvenanceRefV1 {
  side: 'CURRENT' | 'HISTORICAL';
  node_id: string;
  statement_ids: string[];
  evidence_refs?: string[];
  source_refs?: string[];
}

/** A validated candidate. The relation reason is rendered by the Runtime from
 *  validated canonical content rather than carried as model prose, so there is
 *  no free-text `reason` field: model prose promoted into a durable candidate
 *  would become a claim the user attributes to their own evidence. */
export interface RelationCandidateV1 {
  schema_version?: '1.0.0';
  candidate_id: string;
  discovery_fingerprint: string;
  current_asset_id: string;
  current_projection_id: string;
  related_asset_id: string;
  historical_projection_id: string;
  relation_type: RelationType;
  title: string;
  summary: string;
  node_mappings: RelationNodeMappingV1[];
  current_boundary_node_ids: string[];
  historical_boundary_node_ids?: string[];
  provenance: RelationProvenanceRefV1[];
  validation_contract_version?: string;
  lifecycle?: RelationLifecycle;
  detail_included?: false;
  created_at: string;
}

export interface RelationCandidateDecisionV1 {
  schema_version?: '1.0.0';
  decision_id: string;
  candidate_id: string;
  current_asset_id: string;
  current_version_id: string;
  current_knowledge_card_hash: string;
  related_asset_id: string;
  user_action: 'CONFIRM' | 'DECLINE';
  decided_at: string;
}

/** `relation_id` is distinct from `source_candidate_id`: the relation is a new
 *  durable object, the candidate is the proposal it came from. */
export interface ConfirmedAssetRelationV1 {
  schema_version?: '1.0.0';
  relation_id: string;
  source_candidate_id: string;
  relation_type: RelationType;
  current_asset_id: string;
  current_version_id: string;
  current_projection_id: string;
  current_knowledge_card_hash: string;
  related_asset_id: string;
  related_version_id: string;
  historical_projection_id: string;
  lifecycle: ConfirmedRelationLifecycle;
  confirmed_at: string;
  invalidated_at?: string | null;
  invalidation_reason?: string | null;
}

export interface RelationWorkspaceV1 {
  schema_version?: '1.0.0';
  asset_id: string;
  canonical_version_id: string;
  readiness?: KnowledgeCardReadinessRecordV1 | null;
  discovery_outcome?: DiscoveryOutcome;
  failure_class?: DiscoveryFailureClass | null;
  candidates?: RelationCandidateV1[];
  decisions?: RelationCandidateDecisionV1[];
  confirmed_relations?: ConfirmedAssetRelationV1[];
}

export interface ExperienceAssetV1 {
  asset_id: string;
  version_id: string;
  schema_version?: typeof CANONICAL_SCHEMA_VERSION;
  lifecycle?: AssetLifecycle;
  current_milestone?: Milestone;
  created_at: string;
  updated_at: string;
  context?: string;
  goal?: string;
  user_intent?: string;
  sources?: unknown[];
  statements?: Statement[];
  unresolved_questions?: QuestionRecord[];
  milestone_states: Partial<Record<Milestone, MilestoneStateValue>>;
  milestone_artifacts?: MilestoneArtifact[];
  route_decisions: RouteDecision[];
  route_drafts?: unknown[];
  privacy_findings?: unknown[];
  approvals?: unknown[];
  exports?: ExportRecord[];
  lineage: VersionLineage;
  derivation_metadata?: Record<string, unknown>;
}

/* ------------------------------------------------------------------ */
/* Retrieval-phase trace (retrieval-phase-trace-v1.schema.json)         */
/* Vendored verbatim from the public RAG contract on `main`             */
/* (qa/schema/retrieval_phase_trace.schema.json) — see                  */
/* contracts/rag-contract-provenance.json. This is the canonical,       */
/* backend-owned shape that gates cross-asset relation discovery. The   */
/* UI derives its view from this trace and never invents the gate.      */
/* ------------------------------------------------------------------ */

export type RetrievalPhaseEventType =
  | 'current_source_retrieval'
  | 'current_card_changed'
  | 'knowledge_card_ready'
  | 'relation_candidate_search'
  | 'relation_confirmation'
  | 'relation_detail_retrieval'
  | 'relation_no_match';

export type RetrievalScope = 'current_asset' | 'cross_asset_summary' | 'cross_asset_detail';

export interface RetrievalPhaseEvent {
  sequence: number;
  event_type: RetrievalPhaseEventType;
  scope?: RetrievalScope;
  knowledge_card_version?: string;
  knowledge_card_hash?: string;
  milestone_state?: string;
  explicit_user_acceptance?: boolean;
  relation_id?: string;
  related_asset_id?: string;
  confirmed?: boolean;
  detail_included?: boolean;
  provenance_refs?: string[];
  mutated_current_statements?: boolean;
  current_statements_hash_before?: string;
  current_statements_hash_after?: string;
  /**
   * The schema sets `additionalProperties: true`. These summary-only fields are
   * safe to render on a candidate card; they never carry historical detail body.
   */
  relation_type?: string;
  related_asset_title?: string;
  reason?: string;
}

export interface RetrievalPhaseTraceV1 {
  schema_version: string;
  asset_id: string;
  events: RetrievalPhaseEvent[];
}

export const ALL_MILESTONES: Milestone[] = ['M1', 'M2', 'M3', 'M4', 'M5'];
export const ALL_ROUTES: RouteType[] = [
  'PRIVATE_SELF',
  'BEGINNER',
  'PEER',
  'CUSTOMER_EVALUATOR',
  'PUBLIC',
];
