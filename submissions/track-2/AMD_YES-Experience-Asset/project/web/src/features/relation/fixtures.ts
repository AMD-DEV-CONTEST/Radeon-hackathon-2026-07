import type {EvidenceCardRefusalV1, EvidenceCardV1, RelationWorkspaceV1} from './types';

const READY = {version_id: 'version-accepted', knowledge_card_hash: 'f'.repeat(64)};

function workspace(overrides: Partial<RelationWorkspaceV1>): RelationWorkspaceV1 {
  return {
    schema_version: '1.0.0',
    asset_id: 'asset-1',
    canonical_version_id: 'version-accepted',
    readiness: READY,
    discovery_outcome: 'NOT_READY',
    failure_class: null,
    candidates: [],
    decisions: [],
    confirmed_relations: [],
    evidence_card: null,
    ...overrides,
  };
}

const CANDIDATE: RelationWorkspaceV1['candidates'][number] = {
  schema_version: '1.0.0',
  candidate_id: '3f1b0a12-5c6d-4e7f-8a90-1b2c3d4e5f60',
  discovery_fingerprint: 'a'.repeat(64),
  current_asset_id: 'asset-1',
  current_projection_id: 'projection-current',
  related_asset_id: 'asset-2',
  historical_projection_id: 'projection-historical',
  relation_type: 'METHOD_REUSE',
  title: '先量基线再改缓存',
  summary: '另一段经历里也是先建立基线再动手。',
  node_mappings: [
    {
      current_node_id: 'DECISION_RECORD:1:HAS_ACTION:0',
      historical_node_id: 'DECISION_RECORD:2:HAS_ACTION:0',
      current_role: 'HAS_ACTION',
      historical_role: 'HAS_ACTION',
    },
  ],
  current_boundary_node_ids: ['INSIGHT_RECORD:1:HAS_LIMITATION:0'],
  historical_boundary_node_ids: [],
  provenance: [
    {side: 'CURRENT', node_id: 'DECISION_RECORD:1:HAS_ACTION:0', statement_ids: ['s1'], evidence_refs: [], source_refs: []},
    {side: 'HISTORICAL', node_id: 'DECISION_RECORD:2:HAS_ACTION:0', statement_ids: ['s2'], evidence_refs: [], source_refs: []},
  ],
  validation_contract_version: 'e5-relation/v1',
  lifecycle: 'PROPOSED',
  detail_included: false,
  created_at: '2026-08-05T00:00:00+00:00',
};

const DECISION = {
  schema_version: '1.0.0' as const,
  decision_id: '7c1e5a90-2b3c-4d5e-8f01-2a3b4c5d6e7f',
  candidate_id: CANDIDATE.candidate_id,
  current_asset_id: 'asset-1',
  current_version_id: 'version-accepted',
  current_knowledge_card_hash: 'f'.repeat(64),
  related_asset_id: 'asset-2',
  decided_at: '2026-08-05T01:00:00+00:00',
};

export const DISCOVERY_SCENARIOS: Record<string, RelationWorkspaceV1> = {
  locked: workspace({readiness: null, discovery_outcome: 'NOT_READY'}),
  idle: workspace({discovery_outcome: 'NOT_READY'}),
  running: workspace({discovery_outcome: 'RUNNING'}),
  candidate: workspace({discovery_outcome: 'CANDIDATE', candidates: [CANDIDATE]}),
  no_match: workspace({discovery_outcome: 'NO_MATCH'}),
  technical_failure: workspace({
    discovery_outcome: 'TECHNICAL_FAILURE',
    failure_class: 'MODEL_UNAVAILABLE',
  }),
  validation_rejected: workspace({
    discovery_outcome: 'TECHNICAL_FAILURE',
    failure_class: 'RUNTIME_VALIDATION_REJECTED',
  }),
  stale: workspace({discovery_outcome: 'STALE'}),
  confirmed: workspace({
    discovery_outcome: 'CANDIDATE',
    candidates: [{...CANDIDATE, lifecycle: 'CONFIRMED'}],
    decisions: [{...DECISION, user_action: 'CONFIRM'}],
    confirmed_relations: [
      {
        schema_version: '1.0.0',
        relation_id: '5d6e7f80-1a2b-4c3d-9e0f-1a2b3c4d5e6f',
        source_candidate_id: CANDIDATE.candidate_id,
        relation_type: 'METHOD_REUSE',
        current_asset_id: 'asset-1',
        related_asset_id: 'asset-2',
        lifecycle: 'CONFIRMED',
        confirmed_at: '2026-08-05T01:00:00+00:00',
      },
    ],
  }),
  declined: workspace({
    discovery_outcome: 'CANDIDATE',
    candidates: [{...CANDIDATE, lifecycle: 'DECLINED'}],
    decisions: [{...DECISION, user_action: 'DECLINE'}],
  }),
  // Ticket 09. The last completed search still reports CANDIDATE — nothing
  // re-ran it — while the record itself has been marked stale. The screen has
  // to follow the record, or it keeps offering a decision on a comparison whose
  // basis is gone.
  stale_candidate: workspace({
    discovery_outcome: 'CANDIDATE',
    candidates: [{...CANDIDATE, lifecycle: 'STALE'}],
  }),
  // A confirmation that happened, and access that has since been revoked.
  stale_confirmation: workspace({
    discovery_outcome: 'CANDIDATE',
    candidates: [{...CANDIDATE, lifecycle: 'STALE'}],
    decisions: [{...DECISION, user_action: 'CONFIRM'}],
    confirmed_relations: [
      {
        schema_version: '1.0.0',
        relation_id: '6e7f8091-2b3c-4d5e-af10-2b3c4d5e6f70',
        source_candidate_id: CANDIDATE.candidate_id,
        relation_type: 'METHOD_REUSE',
        current_asset_id: 'asset-1',
        related_asset_id: 'asset-2',
        lifecycle: 'STALE',
        confirmed_at: '2026-08-05T01:00:00+00:00',
      },
    ],
  }),
};

export const EVIDENCE_CARD: EvidenceCardV1 = {
  schema_version: '1.0.0',
  card_schema_version: 'e5-evidence-card/v1',
  outcome: 'RENDERED',
  relation_id: '5d6e7f80-1a2b-4c3d-9e0f-1a2b3c4d5e6f',
  relation_type: 'METHOD_REUSE',
  current_asset_id: 'asset-1',
  current_version_id: 'version-accepted',
  current_knowledge_card_hash: 'f'.repeat(64),
  related_asset_id: 'asset-2',
  related_version_id: 'version-historical',
  mapped_roles: [
    {
      current_node_id: 'DECISION_RECORD:1:HAS_ACTION:0',
      historical_node_id: 'DECISION_RECORD:2:HAS_ACTION:0',
      current_role: 'HAS_ACTION',
      historical_role: 'HAS_ACTION',
      current_label: '先补一条基线测量再改缓存策略。',
      historical_label: '先跑一轮压测拿到基线，再动索引。',
      current_label_hash: 'a'.repeat(64),
      historical_label_hash: 'b'.repeat(64),
    },
  ],
  boundaries: [
    {
      side: 'CURRENT',
      node_id: 'INSIGHT_RECORD:1:HAS_LIMITATION:0',
      role: 'HAS_LIMITATION',
      content: '只在读多写少的负载上成立。',
      content_hash: 'c'.repeat(64),
    },
  ],
  provenance: [
    {
      side: 'CURRENT',
      asset_id: 'asset-1',
      projection_id: 'projection-current',
      node_ids: ['DECISION_RECORD:1:HAS_ACTION:0'],
      statement_ids: ['11111111-1111-4111-8111-111111111111'],
      evidence_refs: [],
      source_refs: [],
      span_refs: [],
    },
    {
      side: 'HISTORICAL',
      asset_id: 'asset-2',
      projection_id: 'projection-historical',
      node_ids: ['DECISION_RECORD:2:HAS_ACTION:0'],
      statement_ids: ['22222222-2222-4222-8222-222222222222'],
      evidence_refs: [],
      source_refs: [],
      span_refs: [],
    },
  ],
  card_hash: 'd'.repeat(64),
};

const EVIDENCE_REFUSAL: EvidenceCardRefusalV1 = {
  schema_version: '1.0.0',
  outcome: 'REFUSED',
  reason: 'PARTIAL_PROVENANCE',
  detail: '历史一侧的溯源只解析出一半。',
  unresolved_node_ids: ['DECISION_RECORD:2:HAS_RESULT:0'],
  unresolved_refs: ['source:9f3c'],
};

export const EVIDENCE_SCENARIOS = {
  rendered: EVIDENCE_CARD,
  refused: EVIDENCE_REFUSAL,
  // The binding moved after the card was built: the user corrected the card
  // between confirming and reading.
  staleBinding: {...EVIDENCE_CARD, current_knowledge_card_hash: 'e'.repeat(64)},
} as const;
