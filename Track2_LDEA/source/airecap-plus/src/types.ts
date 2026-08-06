/** L0/L1 types aligned with docs/schemas/s (rules@1.2, envelope s/1.0). */

export const SCHEMA_VERSION = "s/1.0" as const;
export const RULES_VER = "rules@1.2" as const;

export type Id = string;
export type DateTime = string; // ISO-8601
export type Actor = "user" | "agent" | "tool" | "system";
export type Signal = "high" | "low";

export type EventKind =
  | "goal_set"
  | "claim_made"
  | "file_change"
  | "command_result"
  | "test_result"
  | "decision_made"
  | "verification_result"
  | "blocker_found"
  | "outcome_upsert"
  | "session_end";

export type OutcomeType =
  | "feature"
  | "bugfix"
  | "problem"
  | "decision"
  | "spike"
  | "refactor"
  | "chore"
  | "docs"
  | "investigation";

export type OutcomeStatus =
  | "claimed"
  | "evidenced"
  | "verified"
  | "contradicted"
  | "abandoned"
  | "superseded";

export type GoalStatus = "open" | "achieved" | "abandoned" | "superseded";

export type EvidenceRelation =
  | "supports"
  | "refutes"
  | "defines"
  | "verifies"
  | "scopes";

export type BindMethod =
  | "structured"
  | "user"
  | "focus"
  | "time_scope"
  | "llm";

export type ClampReason =
  | "none"
  | "ceiling_claimed"
  | "floor_evidenced"
  | "ceiling_evidenced"
  | "floor_verified"
  | "ceiling_contradicted"
  | "feat_verified_cap";

export type RefKind =
  | "file"
  | "commit"
  | "test"
  | "message"
  | "url"
  | "issue"
  | "pr"
  | "blob"
  | "command"
  | "outcome"
  | "goal";

export interface Ref {
  kind: RefKind;
  value: string;
  label?: string;
}

export interface PathChange {
  path: string;
  change: "add" | "mod" | "del" | "rename";
  plus?: number;
  minus?: number;
  blob_ref?: string;
  from_path?: string;
}

export interface Scope {
  paths: string[];
  symbols: string[];
  services: string[];
  commands: string[];
}

export interface EvidenceLink {
  event_id: Id;
  relation: EvidenceRelation;
  method: BindMethod;
  confidence: number;
  note?: string;
}

export interface ExternalLinks {
  issue?: string;
  pr?: string;
  commit?: string;
  test?: string;
}

export interface VerificationAnchor {
  kind: "test" | "repro" | "user_accept" | "ci";
  key: string;
  event_id?: Id;
}

// --- L0 payloads ---

export interface GoalSetPayload {
  goal_id?: Id;
  statement: string;
  success_criteria?: string[];
  non_goals?: string[];
  stable_key?: string;
  supersedes_goal_id?: Id;
}

export type ClaimKind =
  | "completed"
  | "fixed"
  | "implemented"
  | "works_now"
  | "progress"
  | "other";

export interface ClaimMadePayload {
  text: string;
  claim_kind: ClaimKind;
  outcome_id?: Id;
  goal_id?: Id;
  type_hint?: OutcomeType;
  title_hint?: string;
  scope_hint?: Partial<Scope>;
}

export interface FileChangePayload {
  paths: PathChange[];
  commit?: string;
  outcome_id?: Id;
  is_revert?: boolean;
  summary?: string;
}

export interface CommandResultPayload {
  cmd: string;
  cmd_normalized?: string;
  exit_code: number;
  classification: "test" | "build" | "repro" | "lint" | "other";
  duration_ms?: number;
  stdout_ref?: string;
  stderr_ref?: string;
  stdout_excerpt?: string;
  stderr_excerpt?: string;
  outcome_id?: Id;
}

export interface TestCaseResult {
  name: string;
  status: "pass" | "fail" | "skip";
  file?: string;
  duration_ms?: number;
  message?: string;
}

export interface TestResultPayload {
  framework?: string;
  tests: TestCaseResult[];
  suite_status: "pass" | "fail" | "mixed";
  repro_key?: string;
  outcome_id?: Id;
  raw_ref?: string;
}

export interface DecisionMadePayload {
  decision: string;
  alternatives_rejected?: string[];
  rationale?: string;
  outcome_id?: Id;
  goal_id?: Id;
  conclusion?: string;
}

export interface VerificationResultPayload {
  verdict: "pass" | "fail";
  method: "user_accept" | "repro" | "test" | "ci" | "agent_self";
  notes?: string;
  outcome_id?: Id;
  repro_key?: string;
}

export interface BlockerFoundPayload {
  description: string;
  severity?: "low" | "med" | "high";
  outcome_id?: Id;
  goal_id?: Id;
}

export interface OutcomeUpsertPayload {
  source: "rules" | "llm" | "user";
  op:
    | "create"
    | "patch"
    | "merge"
    | "split"
    | "supersede"
    | "session_end_sweep";
  outcome_id?: Id;
  outcome_ids?: Id[];
  patch?: Partial<
    Pick<
      OutcomeCandidate,
      | "title"
      | "type"
      | "status"
      | "confidence"
      | "confidence_raw"
      | "clamp_reason"
      | "goal_id"
      | "stable_key"
      | "scope"
      | "summary_blob"
      | "tags"
      | "terminal_reason"
      | "superseded_by"
      | "merge_of"
      | "links"
    >
  >;
  focus_outcome_id?: Id;
  clear_focus?: boolean;
  evidence_link?: EvidenceLink;
  note?: string;
}

export interface SessionEndPayload {
  reason?: "normal" | "abort" | "timeout" | "user";
  apply_ab2?: boolean;
}

export type EventPayload =
  | GoalSetPayload
  | ClaimMadePayload
  | FileChangePayload
  | CommandResultPayload
  | TestResultPayload
  | DecisionMadePayload
  | VerificationResultPayload
  | BlockerFoundPayload
  | OutcomeUpsertPayload
  | SessionEndPayload;

export interface EventBase {
  schema_version?: typeof SCHEMA_VERSION;
  id: Id;
  ts: DateTime;
  session_id: Id;
  actor: Actor;
  signal: Signal;
  refs?: Ref[];
  agent_id?: string;
}

export type Event =
  | (EventBase & { kind: "goal_set"; payload: GoalSetPayload })
  | (EventBase & { kind: "claim_made"; payload: ClaimMadePayload })
  | (EventBase & { kind: "file_change"; payload: FileChangePayload })
  | (EventBase & { kind: "command_result"; payload: CommandResultPayload })
  | (EventBase & { kind: "test_result"; payload: TestResultPayload })
  | (EventBase & { kind: "decision_made"; payload: DecisionMadePayload })
  | (EventBase & {
      kind: "verification_result";
      payload: VerificationResultPayload;
    })
  | (EventBase & { kind: "blocker_found"; payload: BlockerFoundPayload })
  | (EventBase & { kind: "outcome_upsert"; payload: OutcomeUpsertPayload })
  | (EventBase & { kind: "session_end"; payload: SessionEndPayload });

// --- L1 ---

export interface GoalProgress {
  ratio_verified: number;
  ratio_evidenced: number;
  active_count: number;
  verified_count: number;
  evidenced_count: number;
  headline?: string;
  computed_at?: DateTime;
}

export interface Goal {
  schema_version?: typeof SCHEMA_VERSION;
  id: Id;
  session_id: Id;
  stable_key?: string;
  statement: string;
  success_criteria: string[];
  non_goals: string[];
  status: GoalStatus;
  outcome_ids: Id[];
  supersedes?: Id;
  source_event_id?: Id;
  created_at: DateTime;
  updated_at: DateTime;
  progress?: GoalProgress;
}

export interface OutcomeCandidate {
  schema_version?: typeof SCHEMA_VERSION;
  id: Id;
  session_id: Id;
  goal_id?: Id;
  stable_key?: string;
  type: OutcomeType;
  title: string;
  status: OutcomeStatus;
  confidence: number;
  confidence_raw: number;
  clamp_reason: ClampReason;
  evidence_links: EvidenceLink[];
  counter_evidence: EvidenceLink[];
  scope: Scope;
  started_at: DateTime;
  updated_at: DateTime;
  verified_at?: DateTime;
  terminal_reason?: string;
  merge_of: Id[];
  superseded_by?: Id;
  aggregator_version: typeof RULES_VER;
  summary_blob: string;
  links?: ExternalLinks;
  tags: string[];
  title_locked?: boolean;
  once_verified?: boolean;
  verification_anchors: VerificationAnchor[];
}

export interface AggregatorConstants {
  C_claim: number;
  C_orphan_ev: number;
  C_feat_verified_cap: number;
  C_focus_bind: number;
  T_evidence: number;
  T_bind_auto: number;
  T_bind_llm: number;
  T_merge_sim: number;
  tau_hours: number;
  W_after_min: number;
  W_idle_hours: number;
  r_c3_enabled: false;
  online_merge_rm1: true;
  focus_strict_scope: boolean;
}

export interface SessionStore {
  schema_version: typeof SCHEMA_VERSION;
  session_id: Id;
  aggregator_version: typeof RULES_VER;
  status: "open" | "ended";
  started_at?: DateTime;
  ended_at?: DateTime;
  updated_at: DateTime;
  goals: Goal[];
  outcomes: OutcomeCandidate[];
  orphan_event_ids: Id[];
  active_goal_id?: Id;
  focus_outcome_id?: Id;
  counters: {
    events_seen: number;
    high_signal_seen: number;
    last_event_id?: Id;
  };
  constants: AggregatorConstants;
  /** In-memory only: full event log for replay/anchors (not part of store.json schema). */
  _events?: Event[];
}

export interface BindHit {
  outcome_id: Id;
  method: BindMethod;
  confidence: number;
}

export function emptyScope(partial?: Partial<Scope>): Scope {
  return {
    paths: partial?.paths ? [...partial.paths] : [],
    symbols: partial?.symbols ? [...partial.symbols] : [],
    services: partial?.services ? [...partial.services] : [],
    commands: partial?.commands ? [...partial.commands] : [],
  };
}
