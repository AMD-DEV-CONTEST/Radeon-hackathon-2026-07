/**
 * Checked-in mock fixtures for the status shell.
 *
 * Progress and terminal fixtures reuse the vendored E1-A contract examples
 * verbatim. Canonical-asset fixtures are typed to `ExperienceAssetV1` and are
 * validated against the vendored JSON Schema by `contracts.contract.test.ts`.
 *
 * No private user content: all IDs are opaque placeholders and text is generic.
 */
import type {
  AgentRunStateV1,
  ExperienceAssetV1,
  Milestone,
  MilestoneStateValue,
  ProgressEventV1,
  ConfirmedAssetRelationV1,
  RelationCandidateDecisionV1,
  RelationCandidateV1,
  RelationWorkspaceV1,
  RetrievalPhaseTraceV1,
  RouteDecision,
  RouteType,
  Statement,
  TerminalResultV1,
} from '../contracts/types';
import type { StatusSnapshot } from './provider';

import progressRunning from '../../contracts/examples/progress-running.json';
import terminalModelUnavailable from '../../contracts/examples/terminal-model-unavailable.json';
import healthExample from '../../contracts/examples/health.json';

// Retrieval-phase trace fixtures. Each JSON file is verified against the public
// AC-30 checker (`qa/scripts/check_retrieval_phase.py`) — see the E1-B evidence
// packet — so these are traces the backend would actually emit.
import traceReady from './traces/relation-ready.json';
import traceNoMatch from './traces/relation-no-match.json';
import traceConfirmed from './traces/relation-confirmed.json';
import traceDetailDenied from './traces/relation-detail-denied.json';
import traceInvalidated from './traces/relation-invalidated.json';

export const PROGRESS_RUNNING = progressRunning as ProgressEventV1;
export const TERMINAL_MODEL_UNAVAILABLE = terminalModelUnavailable as TerminalResultV1;
export const HEALTH_OK = healthExample as StatusSnapshot['health'];

const HEALTH_DEGRADED: NonNullable<StatusSnapshot['health']> = {
  ...(healthExample as NonNullable<StatusSnapshot['health']>),
  status: 'degraded',
  database: 'unavailable',
  checked_at: '2026-07-24T05:00:03Z',
};

const ASSET_ID = '00000000-0000-4000-8000-000000000013';
const V_CURRENT = '00000000-0000-4000-8000-000000000014';
const V_PARENT = '00000000-0000-4000-8000-000000000010';
const RUN_ID = '00000000-0000-4000-8000-000000000012';
const PLAN_ID = '00000000-0000-4000-8000-000000000801';
const RETRIEVE_STEP_ID = '00000000-0000-4000-8000-000000000802';
const VERIFY_STEP_ID = '00000000-0000-4000-8000-000000000803';
const PROPOSAL_ID = '00000000-0000-4000-8000-000000000804';
const POLICY_DECISION_ID = '00000000-0000-4000-8000-000000000805';
const EXECUTION_ID = '00000000-0000-4000-8000-000000000806';

/** Final E1-A AgentRunStateV1, used by the active-run mock without inventing a frontend shape. */
export const AGENT_RUN_STATE: AgentRunStateV1 = {
  schema_version: '1.0.0',
  run_id: RUN_ID,
  asset_id: ASSET_ID,
  base_version_id: V_CURRENT,
  command_id: '00000000-0000-4000-8000-000000000807',
  user_goal: '校验当前经验资产的规范化状态。',
  acceptance_checks: [
    'current asset scope is preserved',
    'policy decision precedes execution',
    'verification records the bounded effect',
  ],
  permission_snapshot: { 'tool:search_current_experience': true },
  current_milestone: 'M2',
  work_plan: {
    plan_id: PLAN_ID,
    run_id: RUN_ID,
    milestone: 'M2',
    goal: '基于当前来源校验规范化资产。',
    steps: [
      {
        step_id: RETRIEVE_STEP_ID,
        step_kind: 'RETRIEVE',
        reason: '只读取当前资产的已批准来源。',
        dependency_step_ids: [],
        required_evidence_refs: ['source:current'],
        required_permission: 'tool:search_current_experience',
        status: 'SUCCEEDED',
        stop_condition: '返回限定来源引用或可见 no-match。',
      },
      {
        step_id: VERIFY_STEP_ID,
        step_kind: 'VERIFY',
        reason: '核对策略决定和实际工具结果。',
        dependency_step_ids: [RETRIEVE_STEP_ID],
        required_evidence_refs: ['observation:current-source'],
        required_permission: null,
        status: 'IN_PROGRESS',
        stop_condition: '工具结果被验证或运行显式停止。',
      },
    ],
    revision: 1,
    created_at: '2026-07-24T05:00:00Z',
    revised_at: '2026-07-24T05:00:00Z',
  },
  retrieval_scope: 'CURRENT_SOURCE',
  knowledge_card_version_id: null,
  knowledge_card_hash: null,
  relation_candidate_ids: [],
  confirmed_relation_ids: [],
  confirmed_related_asset_ids: [],
  confirmed_relation_bindings: [],
  retrieved_evidence: [
    {
      retrieval_id: '00000000-0000-4000-8000-000000000808',
      scope: 'CURRENT_SOURCE',
      asset_id: ASSET_ID,
      version_id: V_CURRENT,
      source_id: null,
      span_id: 'synthetic-current-source',
      related_asset_id: null,
      provenance_ref: 'source:current',
      content_hash: '2222222222222222222222222222222222222222222222222222222222222222',
      no_match: false,
    },
  ],
  tool_proposals: [
    {
      proposal_id: PROPOSAL_ID,
      name: 'search_current_experience',
      arguments: {
        asset_id: ASSET_ID,
        current_version_id: V_CURRENT,
        scope: 'CURRENT_SOURCE',
        query: 'synthetic current-source smoke',
        top_k: 3,
      },
      base_version_id: V_CURRENT,
      knowledge_card_version_id: null,
      knowledge_card_hash: null,
      proposed_at: '2026-07-24T05:00:00Z',
      permission_granted: false,
    },
  ],
  policy_decisions: [
    {
      decision_id: POLICY_DECISION_ID,
      run_id: RUN_ID,
      proposal_id: PROPOSAL_ID,
      outcome: 'ALLOW',
      reason_codes: ['ALLOWLIST_AND_SCOPE_VALID'],
      policy_version: 'runtime-policy/1.0.0',
      decided_at: '2026-07-24T05:00:00Z',
    },
  ],
  tool_executions: [
    {
      execution_id: EXECUTION_ID,
      run_id: RUN_ID,
      proposal_id: PROPOSAL_ID,
      policy_decision_id: POLICY_DECISION_ID,
      tool_name: 'search_current_experience',
      sanitized_argument_hash: '3333333333333333333333333333333333333333333333333333333333333333',
      status: 'SUCCEEDED',
      observation_refs: ['observation:current-source'],
      error_class: null,
      started_at: '2026-07-24T05:00:00Z',
      finished_at: '2026-07-24T05:00:01Z',
    },
  ],
  structured_proposal_hash: '4444444444444444444444444444444444444444444444444444444444444444',
  validation_findings: [],
  verification_report: {
    verification_id: '00000000-0000-4000-8000-000000000809',
    run_id: RUN_ID,
    execution_id: EXECUTION_ID,
    outcome: 'VERIFIED',
    checks: { current_asset_scope: true, policy_preceded_execution: true },
    finding_codes: [],
    safe_summary: '当前来源检索保持在限定资产范围内。',
    verified_at: '2026-07-24T05:00:01Z',
  },
  step_budget: 4,
  model_call_budget: 1,
  retry_budget: 0,
  steps_used: 2,
  model_calls_used: 1,
  retries_used: 0,
  model_id: 'deterministic-contract-fake',
  server_base_url: 'http://127.0.0.1/fake',
  last_durable_version_id: V_CURRENT,
  terminal_state: null,
  updated_at: '2026-07-24T05:00:01Z',
};

function statement(
  n: number,
  status: Statement['status'],
  confirmation: Statement['confirmation'],
  text: string,
): Statement {
  return {
    statement_id: `00000000-0000-4000-8000-0000000002${String(n).padStart(2, '0')}`,
    text,
    status,
    confirmation,
    evidence_strength: status === 'SOURCE_FACT' ? 'DIRECT' : 'SELF_REPORTED',
    source_refs: [],
    derived_from: [],
    sensitivity_tags: [],
    created_in_version: V_PARENT,
    last_changed_in_version: V_CURRENT,
  };
}

function routeDecision(
  route: RouteType,
  eligibility: RouteDecision['eligibility'],
  explanation: string,
  reason_codes: string[] = [],
): RouteDecision {
  return {
    route,
    eligibility,
    explanation,
    reason_codes,
    supporting_statement_ids: [],
    missing_statement_ids: [],
    canonical_version_id: V_CURRENT,
    policy_version: 'route-policy/0.1.0',
    model_run_id: null,
  };
}

/** Route readiness placeholders: mid-refinement, most routes still BLOCKED. */
const ROUTE_DECISIONS_MID: RouteDecision[] = [
  routeDecision('PRIVATE_SELF', 'ELIGIBLE', '仅自己查看，无需额外证据。'),
  routeDecision('BEGINNER', 'BLOCKED', '缺少足够已确认的关键步骤证据。', ['MISSING_EVIDENCE']),
  routeDecision('PEER', 'BLOCKED', '需要完成 M3 决策与证据台账。', ['MISSING_EVIDENCE']),
  routeDecision(
    'CUSTOMER_EVALUATOR',
    'INELIGIBLE',
    '当前经验类型不适用于客户/评审路线。',
    ['ROUTE_NOT_APPLICABLE'],
  ),
  routeDecision(
    'PUBLIC',
    'ELIGIBLE_AFTER_PRIVACY_APPROVAL',
    '存在待处理的隐私项，需显式审批后方可公开导出。',
    ['PRIVACY_REVIEW_REQUIRED'],
  ),
];

const MILESTONES_MID: Record<Milestone, MilestoneStateValue> = {
  M1: 'CONFIRMED',
  M2: 'IN_PROGRESS',
  M3: 'NOT_STARTED',
  M4: 'NOT_STARTED',
  M5: 'NOT_STARTED',
};

const STATEMENTS_MID: Statement[] = [
  statement(1, 'SOURCE_FACT', 'CONFIRMED', '项目在第 3 周切换了缓存策略。'),
  statement(2, 'USER_JUDGMENT', 'CONFIRMED', '切换缓存主要是为了降低尾延迟。'),
  statement(3, 'AGENT_INFERENCE', 'UNCONFIRMED', '团队可能低估了迁移成本。'),
  statement(4, 'UNRESOLVED', 'UNCONFIRMED', '缺少切换前后的具体延迟数据。'),
];

function baseAsset(): ExperienceAssetV1 {
  return {
    asset_id: ASSET_ID,
    version_id: V_CURRENT,
    schema_version: '1.0.0',
    lifecycle: 'ACTIVE',
    current_milestone: 'M2',
    created_at: '2026-07-24T04:58:00Z',
    updated_at: '2026-07-24T05:00:01Z',
    context: '一次关于服务端缓存策略调整的复盘。',
    goal: '把这次经验整理成可复用的经验资产。',
    user_intent: '沉淀个人经验以便未来参考。',
    sources: [],
    statements: STATEMENTS_MID,
    unresolved_questions: [
      {
        question_id: '00000000-0000-4000-8000-000000000301',
        question: '切换缓存前后的 P99 延迟分别是多少？',
        why_it_matters: '用于把“降低尾延迟”从判断升级为有证据的事实。',
        milestone: 'M2',
        state: 'OPEN',
        affected_statement_ids: ['00000000-0000-4000-8000-000000000204'],
        created_by_run_id: RUN_ID,
        created_in_version_id: V_CURRENT,
      },
    ],
    milestone_states: MILESTONES_MID,
    milestone_artifacts: [
      {
        artifact_id: '00000000-0000-4000-8000-000000000401',
        artifact_type: 'ExperienceBriefV1',
        asset_id: ASSET_ID,
        version_id: V_CURRENT,
        milestone: 'M1',
        state: 'CONFIRMED',
        statement_ids: ['00000000-0000-4000-8000-000000000201'],
        unresolved_question_ids: [],
        generated_by_run_id: RUN_ID,
        user_review_status: 'ACCEPTED',
        invalidated_by_version_id: null,
        created_at: '2026-07-24T04:59:00Z',
        updated_at: '2026-07-24T04:59:30Z',
      },
    ],
    route_decisions: ROUTE_DECISIONS_MID,
    route_drafts: [],
    privacy_findings: [],
    approvals: [],
    exports: [],
    lineage: {
      version_id: V_CURRENT,
      parent_version_id: V_PARENT,
      change_kind: 'MILESTONE_UPDATE',
      change_reason: '确认 M1 经验简报并开始 M2 关键时刻梳理。',
      created_at: '2026-07-24T05:00:01Z',
      derived_by_run_id: RUN_ID,
      schema_version: '1.0.0',
    },
    derivation_metadata: {},
  };
}

/** Healthy, mid-refinement, a run in progress. */
export function healthyAsset(): ExperienceAssetV1 {
  return baseAsset();
}

/** A correction invalidated a downstream milestone: stale notice + superseded export. */
export function staleAsset(): ExperienceAssetV1 {
  const asset = baseAsset();
  const invalidatedBy = '00000000-0000-4000-8000-000000000015';
  return {
    ...asset,
    lifecycle: 'ACTIVE',
    milestone_states: { ...MILESTONES_MID, M2: 'INVALIDATED' },
    milestone_artifacts: (asset.milestone_artifacts ?? []).map((a) =>
      a.milestone === 'M1'
        ? { ...a, invalidated_by_version_id: invalidatedBy, state: 'INVALIDATED' as const }
        : a,
    ),
    exports: [
      {
        export_id: '00000000-0000-4000-8000-000000000501',
        asset_id: ASSET_ID,
        version_id: V_PARENT,
        route: 'PRIVATE_SELF',
        route_draft_hash: '0000000000000000000000000000000000000000000000000000000000000000',
        format: 'HTML',
        file_hash: '1111111111111111111111111111111111111111111111111111111111111111',
        path: 'exports/00000000-0000-4000-8000-000000000013/00000000-0000-4000-8000-000000000010/private_self.html',
        created_at: '2026-07-24T04:59:45Z',
        state: 'SUPERSEDED',
      },
    ],
    lineage: {
      ...asset.lineage,
      change_kind: 'CORRECTION',
      change_reason: '用户修正了 M1 中的一处事实，导致下游产物失效。',
    },
  };
}

/** Paused (safe stop): asset intact at last durable version. */
export function pausedAsset(): ExperienceAssetV1 {
  return { ...baseAsset(), lifecycle: 'PAUSED' };
}

const TERMINAL_PAUSED: TerminalResultV1 = {
  run_id: RUN_ID,
  state: 'PAUSED',
  retryable: true,
  safe_user_message: '已在安全点暂停，最后一次有效版本已保留。',
  recovery_action: '点击“继续”以从暂停处恢复当前里程碑。',
  last_durable_version_id: V_CURRENT,
  internal_error_class: null,
  elapsed_ms: 8400,
  model_call_count: 1,
  finished_at: '2026-07-24T05:00:04Z',
  schema_version: '1.0.0',
};

/* ------------------------------------------------------------------ */
/* Cross-asset relation discovery: assets + retrieval-phase traces.     */
/* Traces are validated against the vendored retrieval-phase schema by   */
/* contracts.contract.test.ts.                                          */
/* ------------------------------------------------------------------ */

const MILESTONES_READY: Record<Milestone, MilestoneStateValue> = {
  M1: 'CONFIRMED',
  M2: 'CONFIRMED',
  M3: 'CONFIRMED',
  M4: 'CONFIRMED',
  M5: 'NOT_STARTED',
};

const KNOWLEDGE_CARD_HASH = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

/*
 * Relation fixtures use the frozen six-label vocabulary. The pre-E5 mock labels
 * `SIMILAR_SITUATION` and `SHARED_METHOD` are migrated to `SAME_THEME` and
 * `METHOD_REUSE`: two live vocabularies would let a fixture-only label reach a
 * user-visible surface with no admissibility rule behind it, so the UI would
 * show a relation whose meaning nothing defines.
 *
 * There is no `reason` field. The relation reason is rendered by the Runtime
 * from validated canonical content — model prose promoted into a durable
 * candidate would become a claim the user attributes to their own evidence.
 */

const CURRENT_PROJECTION = '00000000-0000-4000-8000-000000000e01';
const HISTORICAL_PROJECTION_A = '00000000-0000-4000-8000-000000000e02';
const HISTORICAL_PROJECTION_B = '00000000-0000-4000-8000-000000000e03';
const DISCOVERY_FINGERPRINT =
  'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

export const CANDIDATE_SAME_THEME: RelationCandidateV1 = {
  candidate_id: '00000000-0000-4000-8000-000000000601',
  discovery_fingerprint: DISCOVERY_FINGERPRINT,
  current_asset_id: ASSET_ID,
  current_projection_id: CURRENT_PROJECTION,
  related_asset_id: '00000000-0000-4000-8000-000000000701',
  historical_projection_id: HISTORICAL_PROJECTION_A,
  relation_type: 'SAME_THEME',
  title: '另一次缓存迁移的复盘',
  summary: '一次在高并发服务中调整缓存策略并复盘迁移成本的经历。',
  // SAME_THEME is a root-to-root claim about subject matter, so both roles are
  // null. A role-level mapping here would be rejected by the backend, and the
  // fixture would be teaching a shape the product refuses.
  node_mappings: [
    {
      current_node_id: 'INSIGHT_RECORD:cur-cache',
      historical_node_id: 'INSIGHT_RECORD:hist-cache',
      current_role: null,
      historical_role: null,
    },
  ],
  current_boundary_node_ids: ['cur:insight:applicability'],
  historical_boundary_node_ids: ['hist:insight:limitation'],
  provenance: [
    {
      side: 'CURRENT',
      node_id: 'cur:decision:cache-switch',
      statement_ids: ['00000000-0000-4000-8000-0000000006a1'],
      source_refs: ['stmt:cache-switch'],
    },
    {
      side: 'HISTORICAL',
      node_id: 'hist:decision:cache-migration',
      statement_ids: ['00000000-0000-4000-8000-0000000006b1'],
      source_refs: ['stmt:tail-latency'],
    },
  ],
  validation_contract_version: 'e5-relation/v1',
  lifecycle: 'PROPOSED',
  detail_included: false,
  created_at: '2026-07-24T05:02:30Z',
};

export const CANDIDATE_METHOD_REUSE: RelationCandidateV1 = {
  candidate_id: '00000000-0000-4000-8000-000000000602',
  discovery_fingerprint: DISCOVERY_FINGERPRINT,
  current_asset_id: ASSET_ID,
  current_projection_id: CURRENT_PROJECTION,
  related_asset_id: '00000000-0000-4000-8000-000000000702',
  historical_projection_id: HISTORICAL_PROJECTION_B,
  relation_type: 'METHOD_REUSE',
  title: '一次限流阈值调参经历',
  summary: '一次依据 P99 目标调整限流阈值的经历。',
  node_mappings: [
    {
      current_node_id: 'cur:decision:p99-target',
      historical_node_id: 'hist:insight:p99-applicability',
      current_role: 'HAS_REASON',
      historical_role: 'HAS_APPLICABILITY',
    },
  ],
  current_boundary_node_ids: ['cur:insight:limitation'],
  provenance: [
    {
      side: 'CURRENT',
      node_id: 'cur:decision:p99-target',
      statement_ids: ['00000000-0000-4000-8000-0000000006a2'],
      source_refs: ['stmt:p99-method'],
    },
    {
      side: 'HISTORICAL',
      node_id: 'hist:insight:p99-applicability',
      statement_ids: ['00000000-0000-4000-8000-0000000006b2'],
    },
  ],
  validation_contract_version: 'e5-relation/v1',
  lifecycle: 'PROPOSED',
  detail_included: false,
  created_at: '2026-07-24T05:02:30Z',
};

function decisionFor(
  candidate: RelationCandidateV1,
  action: 'CONFIRM' | 'DECLINE',
  decidedAt: string,
): RelationCandidateDecisionV1 {
  return {
    decision_id: `00000000-0000-4000-8000-00000000090${action === 'CONFIRM' ? '1' : '2'}`,
    candidate_id: candidate.candidate_id,
    current_asset_id: ASSET_ID,
    current_version_id: V_CURRENT,
    current_knowledge_card_hash: KNOWLEDGE_CARD_HASH,
    related_asset_id: candidate.related_asset_id,
    user_action: action,
    decided_at: decidedAt,
  };
}

function confirmedRelationFor(candidate: RelationCandidateV1): ConfirmedAssetRelationV1 {
  return {
    // A confirmed relation carries its own identifier plus the candidate it
    // came from: reusing one as the other would hide which object a binding
    // refers to.
    relation_id: '00000000-0000-4000-8000-000000000a01',
    source_candidate_id: candidate.candidate_id,
    relation_type: candidate.relation_type,
    current_asset_id: ASSET_ID,
    current_version_id: V_CURRENT,
    current_projection_id: CURRENT_PROJECTION,
    current_knowledge_card_hash: KNOWLEDGE_CARD_HASH,
    related_asset_id: candidate.related_asset_id,
    related_version_id: '00000000-0000-4000-8000-000000000b01',
    historical_projection_id: candidate.historical_projection_id,
    lifecycle: 'CONFIRMED',
    confirmed_at: '2026-07-24T05:03:00Z',
  };
}

/** M1–M4 refined; the knowledge card is ready for cross-asset discovery. */
function readyAsset(): ExperienceAssetV1 {
  return {
    ...baseAsset(),
    current_milestone: 'M4',
    milestone_states: MILESTONES_READY,
  };
}

/**
 * Relation state served alongside the asset, never inside it.
 *
 * At most one candidate: the MVP cap is one, because showing a weak second
 * relation spends the user's attention and can redirect later reasoning toward
 * an experience that was never relevant, while a missed relation leaves the
 * current asset intact.
 */
function readyWorkspace({
  candidate = CANDIDATE_SAME_THEME,
  decision = null,
  confirmedRelation = null,
  outcome = 'CANDIDATE',
}: {
  candidate?: RelationCandidateV1 | null;
  decision?: RelationCandidateDecisionV1 | null;
  confirmedRelation?: ConfirmedAssetRelationV1 | null;
  outcome?: RelationWorkspaceV1['discovery_outcome'];
} = {}): RelationWorkspaceV1 {
  return {
    asset_id: ASSET_ID,
    canonical_version_id: V_CURRENT,
    readiness: {
      readiness_id: '00000000-0000-4000-8000-000000000c01',
      asset_id: ASSET_ID,
      version_id: V_CURRENT,
      m4_artifact_id: '00000000-0000-4000-8000-000000000d01',
      knowledge_card_hash: KNOWLEDGE_CARD_HASH,
      milestone_state: 'CONFIRMED',
      explicit_user_acceptance: true,
      accepted_gap_statement_ids: [],
      accepted_at: '2026-07-24T05:02:00Z',
      lifecycle: 'ACTIVE',
    },
    discovery_outcome: outcome,
    candidates: candidate ? [candidate] : [],
    decisions: decision ? [decision] : [],
    confirmed_relations: confirmedRelation ? [confirmedRelation] : [],
  };
}

/** Readiness and everything it unlocked are gone after an M1–M4 correction. */
function invalidatedWorkspace(): RelationWorkspaceV1 {
  return {
    asset_id: ASSET_ID,
    canonical_version_id: V_CURRENT,
    readiness: null,
    discovery_outcome: 'STALE',
    candidates: [],
    decisions: [],
    confirmed_relations: [],
  };
}

function invalidatedRelationAsset(): ExperienceAssetV1 {
  const asset = readyAsset();
  return {
    ...asset,
    milestone_states: { ...MILESTONES_READY, M4: 'IN_PROGRESS' },
    lineage: {
      ...asset.lineage,
      change_kind: 'CORRECTION',
      change_reason: 'M1–M4 当前经验被编辑，关联状态按最终后端合同失效。',
    },
  };
}

// The trace JSON files are the single source of truth and are each verified
// against the public AC-30 checker (see the E1-B evidence packet), so these are
// traces the backend would actually emit — not shapes invented by the UI.
const TRACE_RELATION_READY = traceReady as RetrievalPhaseTraceV1;
const TRACE_RELATION_NO_MATCH = traceNoMatch as RetrievalPhaseTraceV1;
const TRACE_RELATION_CONFIRMED = traceConfirmed as RetrievalPhaseTraceV1;
const TRACE_RELATION_DETAIL_DENIED = traceDetailDenied as RetrievalPhaseTraceV1;
const TRACE_RELATION_INVALIDATED = traceInvalidated as RetrievalPhaseTraceV1;

type ScenarioSnapshot = Omit<StatusSnapshot, 'source' | 'fetchedAt'>;

const FROZEN_TERMINAL_STATES: readonly string[] = [
  'SUCCEEDED',
  'NEEDS_USER_INPUT',
  'PAUSED',
  'CANCELLED',
  'TIMED_OUT',
  'MODEL_UNAVAILABLE',
  'MODEL_OOM',
  'INVALID_MODEL_OUTPUT',
  'STORAGE_ERROR',
  'POLICY_BLOCKED',
  'DELETION_FAILED',
  'INTERNAL_ERROR',
];

/** All mock scenarios keyed by id. `failure` and `loading` are handled in the provider. */
export const MOCK_SCENARIOS: Record<string, ScenarioSnapshot> = {
  healthy: {
    scenario: 'healthy',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'present',
    asset: healthyAsset(),
    activeRun: { kind: 'progress', event: PROGRESS_RUNNING, state: AGENT_RUN_STATE },
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: null,
    relationWorkspace: null,
  },
  empty: {
    scenario: 'empty',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'none',
    asset: null,
    activeRun: null,
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: null,
    relationWorkspace: null,
  },
  'safe-stop': {
    scenario: 'safe-stop',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'present',
    asset: pausedAsset(),
    activeRun: { kind: 'terminal', result: TERMINAL_PAUSED },
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: null,
    relationWorkspace: null,
  },
  stale: {
    scenario: 'stale',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'present',
    asset: staleAsset(),
    activeRun: null,
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: null,
    relationWorkspace: null,
  },
  'terminal-failure': {
    scenario: 'terminal-failure',
    health: HEALTH_DEGRADED,
    healthError: null,
    assetAvailability: 'present',
    asset: healthyAsset(),
    activeRun: { kind: 'terminal', result: TERMINAL_MODEL_UNAVAILABLE },
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: null,
    relationWorkspace: null,
  },
  'relation-ready': {
    scenario: 'relation-ready',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'present',
    asset: readyAsset(),
    activeRun: null,
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: TRACE_RELATION_READY,
    relationWorkspace: readyWorkspace(),
  },
  'relation-no-match': {
    scenario: 'relation-no-match',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'present',
    asset: readyAsset(),
    activeRun: null,
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: TRACE_RELATION_NO_MATCH,
    relationWorkspace: readyWorkspace({ candidate: null, outcome: 'NO_MATCH' }),
  },
  'relation-confirmed': {
    scenario: 'relation-confirmed',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'present',
    asset: readyAsset(),
    activeRun: null,
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: TRACE_RELATION_CONFIRMED,
    relationWorkspace: readyWorkspace({
      decision: decisionFor(CANDIDATE_SAME_THEME, 'CONFIRM', '2026-07-24T05:03:00Z'),
      confirmedRelation: confirmedRelationFor(CANDIDATE_SAME_THEME),
    }),
  },
  'relation-detail-denied': {
    scenario: 'relation-detail-denied',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'present',
    asset: readyAsset(),
    activeRun: null,
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: TRACE_RELATION_DETAIL_DENIED,
    relationWorkspace: readyWorkspace({
      decision: decisionFor(CANDIDATE_SAME_THEME, 'DECLINE', '2026-07-24T05:03:30Z'),
    }),
  },
  'relation-invalidated': {
    scenario: 'relation-invalidated',
    health: HEALTH_OK,
    healthError: null,
    assetAvailability: 'present',
    asset: invalidatedRelationAsset(),
    activeRun: null,
    terminalStates: FROZEN_TERMINAL_STATES,
    retrievalTrace: TRACE_RELATION_INVALIDATED,
    relationWorkspace: invalidatedWorkspace(),
  },
};

export const DEFAULT_MOCK_SCENARIO = 'healthy';
export const SCENARIO_IDS = Object.keys(MOCK_SCENARIOS);

/** Every retrieval-phase trace fixture, for contract-conformance validation. */
export const RETRIEVAL_TRACES: RetrievalPhaseTraceV1[] = [
  TRACE_RELATION_READY,
  TRACE_RELATION_NO_MATCH,
  TRACE_RELATION_CONFIRMED,
  TRACE_RELATION_DETAIL_DENIED,
  TRACE_RELATION_INVALIDATED,
];
