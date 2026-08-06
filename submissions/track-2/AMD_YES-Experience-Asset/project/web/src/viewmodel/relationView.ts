/**
 * Pure derivation from the final E1-A canonical asset plus the public
 * retrieval-phase trace to a render-ready cross-asset relation-discovery view.
 *
 * The RAG order contract (spec/README.md, AGENT_ARCHITECTURE.md) requires two
 * gates, and this derivation is where the UI *proves* them rather than trusting
 * upstream ordering:
 *
 *   Gate 1 — canonical `knowledge_card_readiness` must be accepted for the
 *            current M4 version before canonical summary candidates can render.
 *   Gate 2 — bounded detailed evidence cannot be requested before an explicit
 *            relation confirmation. Detail stays DENIED until the relation is
 *            CONFIRMED; a `relation_detail_retrieval` on an unconfirmed relation
 *            is refused and recorded as a gate violation.
 *
 * Editing/reopening M1–M4 (`current_card_changed` with mutated statements after
 * readiness) invalidates readiness, candidates, confirmations and detail.
 *
 * Relation state comes from `RelationWorkspaceV1`, the read-only composition
 * the API serves from the sidecar relation ledger — not from the Experience
 * Asset snapshot. Persisting relation state in the snapshot would append a
 * content version on every confirmation and change the content hash, while the
 * non-contamination invariant requires that hash identical across a relation
 * read. The asset is still needed for canonical identity and the M4 milestone
 * state; the trace remains independent ordering and
 * no-match/detail/invalidation evidence. React does not create canonical state.
 */
import type {
  ExperienceAssetV1,
  RelationType,
  RelationWorkspaceV1,
  RetrievalPhaseTraceV1,
} from '../contracts/types';

export type RelationGate = 'NO_TRACE' | 'LOCKED' | 'READY' | 'INVALIDATED';
export type RelationConfirmation = 'PENDING' | 'CONFIRMED' | 'DECLINED';
export type DetailAccess = 'DENIED_UNTIL_CONFIRMED' | 'AVAILABLE' | 'DECLINED';

export interface RelationCandidateView {
  relationId: string;
  relatedAssetId: string | null;
  /** Summary-only presentation fields; never historical detail body. */
  title: string | null;
  summary: string | null;
  /** One of six frozen labels, never free text: a closed vocabulary is what
   *  lets a relation mean the same thing in a later session. */
  relationType: RelationType | null;
  /** Provenance from both sides. A candidate explained from only one side
   *  cannot be checked against the other, so the sides stay attributed. */
  currentProvenanceRefs: string[];
  historicalProvenanceRefs: string[];
  /** Current-side nodes carrying the transfer boundary. Similarity without a
   *  boundary invites transferring a lesson into a situation the original
   *  experience never covered. */
  boundaryNodeIds: string[];
  confirmation: RelationConfirmation;
  detailAccess: DetailAccess;
  detailRetrieved: boolean;
}

export interface RelationDiscoveryView {
  /** false when the source does not serve a trace (e.g. live/not_served). */
  available: boolean;
  gate: RelationGate;
  knowledgeCardVersion: string | null;
  knowledgeCardHash: string | null;
  candidates: RelationCandidateView[];
  noMatch: boolean;
  invalidated: boolean;
  invalidationReason: string | null;
  /** Ordering violations found in the trace; MUST be empty on valid data. */
  gateViolations: string[];
}

const EMPTY: RelationDiscoveryView = {
  available: false,
  gate: 'NO_TRACE',
  knowledgeCardVersion: null,
  knowledgeCardHash: null,
  candidates: [],
  noMatch: false,
  invalidated: false,
  invalidationReason: null,
  gateViolations: [],
};

export function deriveRelationDiscovery(
  asset: ExperienceAssetV1 | null,
  workspace: RelationWorkspaceV1 | null,
  trace: RetrievalPhaseTraceV1 | null,
): RelationDiscoveryView {
  if (!asset && !trace) return { ...EMPTY };

  const events = [...(trace?.events ?? [])].sort((a, b) => a.sequence - b.sequence);

  let traceReady = false;
  let traceKnowledgeCardVersion: string | null = null;
  let traceKnowledgeCardHash: string | null = null;
  let traceMilestoneState: string | null = null;
  let invalidated = false;
  let invalidationReason: string | null = null;
  let noMatch = false;
  const traceCandidateIds = new Set<string>();
  const traceCandidateAssetIds = new Map<string, string>();
  const traceConfirmations = new Map<string, boolean>();
  const detailRetrievedIds = new Set<string>();
  const gateViolations: string[] = [];

  for (const e of events) {
    switch (e.event_type) {
      case 'knowledge_card_ready': {
        // Gate 1 opens only on an *explicit* user acceptance of the card.
        if (e.explicit_user_acceptance === true) {
          traceReady = true;
          invalidated = false;
          invalidationReason = null;
          traceKnowledgeCardVersion = e.knowledge_card_version ?? null;
          traceKnowledgeCardHash = e.knowledge_card_hash ?? null;
          traceMilestoneState = e.milestone_state ?? null;
        }
        break;
      }
      case 'current_card_changed': {
        // Editing/reopening the current experience invalidates everything the
        // readiness gate had unlocked.
        if (e.mutated_current_statements === true && (traceReady || traceCandidateIds.size > 0)) {
          invalidated = true;
          invalidationReason =
            'M1–M4 当前经验已被编辑/重开，就绪度、候选、确认、详细证据、预览与审批均已失效，需重新生成。';
          traceReady = false;
          traceCandidateIds.clear();
          traceCandidateAssetIds.clear();
          traceConfirmations.clear();
          detailRetrievedIds.clear();
          noMatch = false;
        }
        break;
      }
      case 'relation_candidate_search': {
        if (!traceReady) {
          gateViolations.push(
            `候选检索(seq ${e.sequence})出现在 KnowledgeCardReady 之前——已按门控丢弃。`,
          );
          break;
        }
        let validCandidate = true;
        if (e.scope !== 'cross_asset_summary') {
          gateViolations.push(
            `候选检索(seq ${e.sequence})scope 应为 cross_asset_summary，实为 ${e.scope}。`,
          );
          validCandidate = false;
        }
        if (e.detail_included !== false) {
          gateViolations.push(`候选检索(seq ${e.sequence})不得包含历史详情。`);
          validCandidate = false;
        }
        if (!e.relation_id || !e.related_asset_id || e.related_asset_id === trace?.asset_id) {
          gateViolations.push(`候选检索(seq ${e.sequence})未绑定合法的跨资产关系。`);
          validCandidate = false;
        }
        if (validCandidate && e.relation_id && e.related_asset_id) {
          traceCandidateIds.add(e.relation_id);
          traceCandidateAssetIds.set(e.relation_id, e.related_asset_id);
        }
        break;
      }
      case 'relation_no_match': {
        if (!traceReady) {
          gateViolations.push(
            `no-match(seq ${e.sequence})出现在 KnowledgeCardReady 之前——已按门控忽略。`,
          );
          break;
        }
        if (e.scope !== 'cross_asset_summary' || e.detail_included !== false) {
          gateViolations.push(`no-match(seq ${e.sequence})不是合法的 summary-only 结果。`);
          break;
        }
        noMatch = true;
        break;
      }
      case 'relation_confirmation': {
        if (!e.relation_id) break;
        if (!traceCandidateIds.has(e.relation_id)) {
          gateViolations.push(`确认(seq ${e.sequence})指向未知候选 ${e.relation_id}。`);
          break;
        }
        if (
          !e.related_asset_id ||
          traceCandidateAssetIds.get(e.relation_id) !== e.related_asset_id ||
          typeof e.confirmed !== 'boolean'
        ) {
          gateViolations.push(`确认(seq ${e.sequence})未绑定候选的资产或显式决定。`);
          break;
        }
        traceConfirmations.set(e.relation_id, e.confirmed === true);
        break;
      }
      case 'relation_detail_retrieval': {
        // Gate 2: detail only after explicit confirmation.
        const expectedRelatedAsset = e.relation_id
          ? traceCandidateAssetIds.get(e.relation_id)
          : undefined;
        if (
          !e.relation_id ||
          traceConfirmations.get(e.relation_id) !== true ||
          !expectedRelatedAsset ||
          e.related_asset_id !== expectedRelatedAsset
        ) {
          gateViolations.push(
            `详细证据检索(seq ${e.sequence})出现在关系确认之前——已按门控拒绝。`,
          );
          break;
        }
        if (
          e.scope !== 'cross_asset_detail' ||
          e.detail_included !== true ||
          !e.provenance_refs?.length ||
          e.mutated_current_statements !== false ||
          !e.current_statements_hash_before ||
          e.current_statements_hash_before !== e.current_statements_hash_after ||
          e.knowledge_card_version !== traceKnowledgeCardVersion
        ) {
          gateViolations.push(`详细证据检索(seq ${e.sequence})违反 bounded-detail 不变量。`);
          break;
        }
        detailRetrievedIds.add(e.relation_id);
        break;
      }
      case 'current_source_retrieval':
        // Same-asset grounding: no effect on cross-asset discovery.
        break;
    }
  }

  const readiness = workspace?.readiness ?? null;
  const canonicalReady = Boolean(
    asset &&
      readiness &&
      readiness.explicit_user_acceptance === true &&
      readiness.version_id === asset.version_id &&
      readiness.lifecycle !== 'STALE' &&
      readiness.lifecycle !== 'INVALIDATED' &&
      asset.milestone_states.M4 === readiness.milestone_state,
  );

  let readinessConsistent = true;
  if (trace && asset && trace.asset_id !== asset.asset_id) {
    gateViolations.push('检索轨迹绑定的资产与规范资产不一致。');
    readinessConsistent = false;
  }
  if (trace && canonicalReady !== traceReady) {
    gateViolations.push('规范资产的 KnowledgeCardReady 与检索轨迹状态不一致。');
    readinessConsistent = false;
  }
  if (trace && noMatch && (workspace?.candidates?.length ?? 0) > 0) {
    gateViolations.push('检索轨迹报告 no-match，但规范资产仍包含关系候选。');
    readinessConsistent = false;
  }
  if (
    traceReady &&
    readiness &&
    (traceKnowledgeCardVersion !== readiness.version_id ||
      traceKnowledgeCardHash !== readiness.knowledge_card_hash ||
      traceMilestoneState !== readiness.milestone_state)
  ) {
    gateViolations.push('检索轨迹绑定的知识卡版本/哈希与规范资产不一致。');
    readinessConsistent = false;
  }
  const gateReady = canonicalReady && readinessConsistent;

  const decisions = new Map(
    (workspace?.decisions ?? []).map((decision) => [decision.candidate_id, decision]),
  );
  const candidates: RelationCandidateView[] = [];
  if (gateReady && !invalidated) {
    for (const candidate of workspace?.candidates ?? []) {
      if (trace && !traceCandidateIds.has(candidate.candidate_id)) {
        gateViolations.push(`规范候选 ${candidate.candidate_id} 未出现在检索轨迹中。`);
        continue;
      }
      const decision = decisions.get(candidate.candidate_id);
      const decisionConfirmed = decision ? decision.user_action === 'CONFIRM' : undefined;
      const confirmation: RelationConfirmation = decision
        ? decisionConfirmed
          ? 'CONFIRMED'
          : 'DECLINED'
        : 'PENDING';
      const tracedConfirmation = traceConfirmations.get(candidate.candidate_id);
      if (tracedConfirmation !== undefined && tracedConfirmation !== decisionConfirmed) {
        gateViolations.push(`候选 ${candidate.candidate_id} 的确认状态与检索轨迹不一致。`);
      }
      const provenance = candidate.provenance ?? [];
      candidates.push({
        relationId: candidate.candidate_id,
        relatedAssetId: candidate.related_asset_id,
        title: candidate.title,
        summary: candidate.summary,
        relationType: candidate.relation_type,
        currentProvenanceRefs: provenance
          .filter((ref) => ref.side === 'CURRENT')
          .flatMap((ref) => ref.statement_ids),
        historicalProvenanceRefs: provenance
          .filter((ref) => ref.side === 'HISTORICAL')
          .flatMap((ref) => ref.statement_ids),
        boundaryNodeIds: candidate.current_boundary_node_ids ?? [],
        confirmation,
        detailAccess:
          confirmation === 'CONFIRMED'
            ? 'AVAILABLE'
            : confirmation === 'DECLINED'
              ? 'DECLINED'
              : 'DENIED_UNTIL_CONFIRMED',
        detailRetrieved: detailRetrievedIds.has(candidate.candidate_id),
      });
    }
  }

  const gate: RelationGate = invalidated
    ? 'INVALIDATED'
    : gateReady
      ? 'READY'
      : 'LOCKED';

  return {
    available: true,
    gate,
    knowledgeCardVersion: readiness?.version_id ?? null,
    knowledgeCardHash: readiness?.knowledge_card_hash ?? null,
    candidates,
    noMatch,
    invalidated,
    invalidationReason,
    gateViolations,
  };
}
