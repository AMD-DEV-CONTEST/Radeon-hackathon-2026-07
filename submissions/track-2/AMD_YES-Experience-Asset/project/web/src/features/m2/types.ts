export type M2ArtifactState =
  | 'NEEDS_INPUT'
  | 'REVIEW_READY'
  | 'CONFIRMED'
  | 'COMPLETE_WITH_GAPS'
  | 'INVALIDATED';

export type TemporalStatus = 'KNOWN' | 'MISSING' | 'CONFLICTING';
export type CriticalityStatus = 'AGENT_PROPOSED' | 'UNRESOLVED' | 'USER_CONFIRMED';
export type OrderBasis = 'SOURCE_ASSERTED' | 'NARRATIVE_SEQUENCE' | 'PARTIAL_ORDER';

interface CriticalMomentEntryBaseV1 {
  moment_id: string;
  display_order: number;
  title: string;
  description: string;
  criticality_status: CriticalityStatus;
  criticality_reason: string;
  criticality_confirmed_at?: string | null;
  source_statement_ids: string[];
  cue_statement_ids: string[];
  change_statement_ids: string[];
  surprise_statement_ids: string[];
}

export type CriticalMomentEntryV1 = CriticalMomentEntryBaseV1 &
  (
    | {
        temporal_status: 'KNOWN';
        time_label: string;
        conflict_statement_ids: [];
        unresolved_reason: null;
      }
    | {
        temporal_status: 'MISSING';
        time_label: null;
        conflict_statement_ids: [];
        unresolved_reason: string;
      }
    | {
        temporal_status: 'CONFLICTING';
        time_label: null;
        conflict_statement_ids: [string, string, ...string[]];
        unresolved_reason: string;
      }
  );

export interface CriticalMomentMapV1 {
  schema_version: '0.1.0';
  artifact_id: string;
  asset_id: string;
  base_m1_version_id: string;
  generated_by_run_id: string;
  state: M2ArtifactState;
  order_basis: OrderBasis;
  moments: CriticalMomentEntryV1[];
  dependency_statement_ids: string[];
  unresolved_question_ids: string[];
  created_at: string;
  updated_at: string;
  invalidated_by_m1_version_id: string | null;
  invalidation_reason: string | null;
}
