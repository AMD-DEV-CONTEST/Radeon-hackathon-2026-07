import type {
  ConfirmedAssetRelationV1,
  DiscoveryFailureClass,
  DiscoveryOutcome,
  RelationCandidateV1,
  RelationWorkspaceV1,
} from './types';

/**
 * The four states a search can be in, plus the two that mean it has not run.
 *
 * Every one is read from the backend's own `discovery_outcome`. Deriving them
 * locally — for instance treating "no candidates" as no-match — would collapse
 * a technical failure into a semantic answer, and the user would read a stalled
 * search as a proven absence of any relation.
 */
export type DiscoveryViewState =
  | 'LOCKED'
  | 'IDLE'
  | 'RUNNING'
  | 'CANDIDATE'
  | 'NO_MATCH'
  | 'TECHNICAL_FAILURE'
  | 'STALE';

export type DecisionState = 'UNDECIDED' | 'CONFIRMED' | 'DECLINED';

export interface DiscoveryView {
  state: DiscoveryViewState;
  candidate: RelationCandidateV1 | null;
  failureClass: DiscoveryFailureClass | null;
  /** True only where a retry can change the answer. */
  retryable: boolean;
  canSearch: boolean;
  /**
   * Read from the backend's decision record, never from a local filter. A
   * filter would hide the candidate while leaving the permission behind it in
   * place, so the screen would disagree with what the system actually allows.
   */
  decision: DecisionState;
  confirmedRelation: ConfirmedAssetRelationV1 | null;
  canDecide: boolean;
  /**
   * True when a bound asset changed under an answer already on screen.
   *
   * Read from the records' own lifecycle, not inferred from the outcome: the
   * backend may have marked a candidate stale while the last completed search
   * still reports `CANDIDATE`, and the screen has to follow the record.
   */
  stale: boolean;
  /**
   * Whether the confirmed detail is still readable.
   *
   * Separate from `confirmedRelation !== null` because hiding the relation
   * while leaving the permission is exactly the failure ticket 09 is about; the
   * backend revokes first, and this only reports what it revoked.
   */
  canReadDetail: boolean;
}

const RETRYABLE: ReadonlySet<DiscoveryFailureClass> = new Set([
  'MODEL_UNAVAILABLE',
  'MODEL_TIMED_OUT',
  'MALFORMED_MODEL_OUTPUT',
  'STORAGE_CONFLICT',
  // Nothing is known about whether the model was ever asked, so the question is
  // genuinely unanswered and a retry can settle it.
  'LEASE_EXPIRED',
]);

export function deriveDiscoveryView(
  workspace: RelationWorkspaceV1 | null,
): DiscoveryView {
  if (workspace === null) {
    return {
      state: 'LOCKED',
      candidate: null,
      failureClass: null,
      retryable: false,
      canSearch: false,
      decision: 'UNDECIDED',
      confirmedRelation: null,
      canDecide: false,
      stale: false,
      canReadDetail: false,
    };
  }
  const outcome: DiscoveryOutcome = workspace.discovery_outcome;
  const ready = workspace.readiness !== null;
  const failureClass = workspace.failure_class ?? null;

  // NOT_READY carries two different meanings on the wire: the card is locked,
  // or it is ready and nobody has searched yet. The readiness record is what
  // separates them, and conflating them would either hide the search button
  // from a ready card or offer it on a locked one.
  const state: DiscoveryViewState =
    outcome === 'NOT_READY' ? (ready ? 'IDLE' : 'LOCKED') : outcome;

  const candidate = workspace.candidates[0] ?? null;
  const decisionRecord =
    candidate === null
      ? null
      : workspace.decisions.find((item) => item.candidate_id === candidate.candidate_id) ??
        null;
  const confirmedRelation =
    candidate === null
      ? null
      : workspace.confirmed_relations.find(
          (item) => item.source_candidate_id === candidate.candidate_id,
        ) ?? null;
  const decision: DecisionState =
    decisionRecord?.user_action === 'CONFIRM' || confirmedRelation !== null
      ? 'CONFIRMED'
      : decisionRecord?.user_action === 'DECLINE'
        ? 'DECLINED'
        : 'UNDECIDED';

  // A record whose subject moved is stale whatever the last search reported.
  const staleCandidate =
    candidate !== null &&
    (candidate.lifecycle === 'STALE' || candidate.lifecycle === 'INVALIDATED');
  const staleRelation =
    confirmedRelation !== null && confirmedRelation.lifecycle !== 'CONFIRMED';
  const stale = state === 'STALE' || staleCandidate || staleRelation;

  return {
    state: stale && state !== 'RUNNING' ? 'STALE' : state,
    candidate,
    failureClass,
    retryable: failureClass !== null && RETRYABLE.has(failureClass),
    // Repeating a search is safe: the same fingerprint returns the cached
    // answer without another model call, so the only state that withholds the
    // action is one already in flight.
    canSearch: ready && state !== 'RUNNING',
    decision,
    confirmedRelation,
    // Deciding on a stale candidate would mint a permission against a
    // comparison whose basis no longer exists, and the decision would look, on
    // the record, exactly like one the user made with the evidence in front of
    // them.
    canDecide: candidate !== null && decision === 'UNDECIDED' && !stale,
    stale,
    canReadDetail: confirmedRelation !== null && !staleRelation,
  };
}

export const STATE_LABELS: Record<DiscoveryViewState, string> = {
  LOCKED: '未就绪',
  IDLE: '尚未查找',
  RUNNING: '查找中',
  CANDIDATE: '找到一条可辩护的关系',
  NO_MATCH: '已查找，没有可辩护的关系',
  TECHNICAL_FAILURE: '查找中断',
  STALE: '卡片已变更',
};

export const RELATION_TYPE_LABELS: Record<string, string> = {
  SAME_THEME: '同一主题',
  METHOD_REUSE: '方法复用',
  COUNTEREXAMPLE: '反例',
  SUPPLEMENT: '补充',
  PREREQUISITE: '前置条件',
  FOLLOW_UP: '后续',
};

export const FAILURE_LABELS: Record<DiscoveryFailureClass, string> = {
  MODEL_UNAVAILABLE: '本地推理服务不可用',
  MODEL_TIMED_OUT: '本地推理超时',
  MALFORMED_MODEL_OUTPUT: '模型输出不符合结构合同',
  RUNTIME_VALIDATION_REJECTED: '提案未通过 Runtime 校验',
  STORAGE_CONFLICT: '存储冲突',
  STALE_BINDING: '绑定已过期',
  LEASE_EXPIRED: '上一次查找中断，没有回报结果',
};
