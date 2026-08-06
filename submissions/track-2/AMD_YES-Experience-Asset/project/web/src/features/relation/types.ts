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
  | 'STALE_BINDING'
  | 'LEASE_EXPIRED';

export type RelationType =
  | 'SAME_THEME'
  | 'METHOD_REUSE'
  | 'COUNTEREXAMPLE'
  | 'SUPPLEMENT'
  | 'PREREQUISITE'
  | 'FOLLOW_UP';

export interface RelationNodeMappingV1 {
  current_node_id: string;
  historical_node_id: string;
  current_role: string | null;
  historical_role: string | null;
}

export interface RelationProvenanceRefV1 {
  side: 'CURRENT' | 'HISTORICAL';
  node_id: string;
  statement_ids: string[];
  evidence_refs: string[];
  source_refs: string[];
}

export interface RelationCandidateV1 {
  schema_version: '1.0.0';
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
  historical_boundary_node_ids: string[];
  provenance: RelationProvenanceRefV1[];
  validation_contract_version: string;
  lifecycle: 'PROPOSED' | 'CONFIRMED' | 'DECLINED' | 'STALE' | 'INVALIDATED';
  /** Always false before confirmation: the candidate view carries no history. */
  detail_included: false;
  created_at: string;
}

export interface RelationCandidateDecisionV1 {
  schema_version: '1.0.0';
  decision_id: string;
  candidate_id: string;
  current_asset_id: string;
  current_version_id: string;
  current_knowledge_card_hash: string;
  related_asset_id: string;
  user_action: 'CONFIRM' | 'DECLINE';
  decided_at: string;
}

export interface ConfirmedAssetRelationV1 {
  schema_version: '1.0.0';
  relation_id: string;
  source_candidate_id: string;
  relation_type: RelationType;
  current_asset_id: string;
  related_asset_id: string;
  lifecycle: 'CONFIRMED' | 'STALE' | 'INVALIDATED';
  confirmed_at: string;
}

/** One bilateral correspondence, labelled with both sides' canonical text. */
export interface MappedRoleEvidenceV1 {
  current_node_id: string;
  historical_node_id: string;
  current_role: string | null;
  historical_role: string | null;
  current_label: string;
  historical_label: string;
  current_label_hash: string;
  historical_label_hash: string;
}

/** The transfer condition, quoted from its source rather than paraphrased. */
export interface TransferBoundaryV1 {
  side: 'CURRENT' | 'HISTORICAL';
  node_id: string;
  role: string | null;
  content: string;
  content_hash: string;
}

export interface SideProvenanceV1 {
  side: 'CURRENT' | 'HISTORICAL';
  asset_id: string;
  projection_id: string;
  node_ids: string[];
  statement_ids: string[];
  evidence_refs: string[];
  source_refs: string[];
  span_refs: string[];
}

export interface EvidenceCardV1 {
  schema_version: '1.0.0';
  card_schema_version: 'e5-evidence-card/v1';
  outcome: 'RENDERED';
  relation_id: string;
  relation_type: RelationType;
  current_asset_id: string;
  current_version_id: string;
  current_knowledge_card_hash: string;
  related_asset_id: string;
  related_version_id: string;
  mapped_roles: MappedRoleEvidenceV1[];
  boundaries: TransferBoundaryV1[];
  provenance: SideProvenanceV1[];
  card_hash: string;
}

export type EvidenceCardRefusalReason =
  | 'RELATION_NOT_LIVE'
  | 'BINDING_MISMATCH'
  | 'PERMISSION_REVOKED'
  | 'CONTENT_UNAVAILABLE'
  | 'PARTIAL_PROVENANCE'
  | 'MISSING_REFERENCES';

/**
 * Discriminated from the card by `outcome`.
 *
 * A refusal must never be renderable as an empty card: a card missing half its
 * provenance still looks authoritative, and the user has no way to see what was
 * dropped.
 */
export interface EvidenceCardRefusalV1 {
  schema_version: '1.0.0';
  outcome: 'REFUSED';
  reason: EvidenceCardRefusalReason;
  detail: string;
  unresolved_node_ids: string[];
  unresolved_refs: string[];
}

export interface RelationWorkspaceV1 {
  schema_version: '1.0.0';
  asset_id: string;
  canonical_version_id: string;
  readiness: {version_id: string; knowledge_card_hash: string} | null;
  discovery_outcome: DiscoveryOutcome;
  failure_class: DiscoveryFailureClass | null;
  candidates: RelationCandidateV1[];
  decisions: RelationCandidateDecisionV1[];
  confirmed_relations: ConfirmedAssetRelationV1[];
  /** Null on the four operations that produce no card. */
  evidence_card: EvidenceCardV1 | EvidenceCardRefusalV1 | null;
}
