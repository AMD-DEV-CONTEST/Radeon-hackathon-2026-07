/**
 * The public proof of the two RAG gates. These tests are the "publicly prove
 * that cross-asset retrieval cannot run before Knowledge Card readiness and that
 * detailed historical retrieval cannot run before explicit relation
 * confirmation" requirement, expressed as executable assertions.
 */
import { describe, expect, it } from 'vitest';
import { deriveRelationDiscovery } from './relationView';
import {
  CANDIDATE_METHOD_REUSE,
  CANDIDATE_SAME_THEME,
  MOCK_SCENARIOS,
} from '../data/fixtures';
import type { RetrievalPhaseTraceV1 } from '../contracts/types';

const ASSET = '00000000-0000-4000-8000-000000000013';

function trace(events: RetrievalPhaseTraceV1['events']): RetrievalPhaseTraceV1 {
  return { schema_version: '0.1.0', asset_id: ASSET, events };
}

describe('deriveRelationDiscovery — gate 1: readiness before candidates', () => {
  it('is NO_TRACE / unavailable when the source serves no trace', () => {
    const v = deriveRelationDiscovery(null, null, null);
    expect(v.available).toBe(false);
    expect(v.gate).toBe('NO_TRACE');
    expect(v.candidates).toEqual([]);
  });

  it('is LOCKED with no candidates before an accepted KnowledgeCardReady', () => {
    const v = deriveRelationDiscovery(
      MOCK_SCENARIOS.healthy.asset,
      null,
      trace([{ sequence: 0, event_type: 'current_source_retrieval', scope: 'current_asset' }]),
    );
    expect(v.gate).toBe('LOCKED');
    expect(v.candidates).toEqual([]);
  });

  it('stays LOCKED when readiness was not explicitly accepted', () => {
    const v = deriveRelationDiscovery(
      MOCK_SCENARIOS.healthy.asset,
      null,
      trace([
        {
          sequence: 0,
          event_type: 'knowledge_card_ready',
          knowledge_card_version: 'kc-1',
          explicit_user_acceptance: false,
        },
      ]),
    );
    expect(v.gate).toBe('LOCKED');
  });

  it('REFUSES to surface a candidate that searched before readiness', () => {
    const v = deriveRelationDiscovery(
      MOCK_SCENARIOS['relation-ready'].asset,
      MOCK_SCENARIOS['relation-ready'].relationWorkspace,
      trace([
        {
          sequence: 0,
          event_type: 'relation_candidate_search',
          scope: 'cross_asset_summary',
          relation_id: 'r-early',
          related_asset_id: 'a-early',
        },
        {
          sequence: 1,
          event_type: 'knowledge_card_ready',
          milestone_state: 'CONFIRMED',
          knowledge_card_version: '00000000-0000-4000-8000-000000000014',
          knowledge_card_hash: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
          explicit_user_acceptance: true,
        },
      ]),
    );
    // The out-of-order candidate is dropped; only readiness remains.
    expect(v.gate).toBe('READY');
    expect(v.candidates.find((c) => c.relationId === 'r-early')).toBeUndefined();
    expect(v.gateViolations.length).toBeGreaterThan(0);
  });

  it('fails closed when readiness is not bound to the canonical version/hash', () => {
    const scenario = MOCK_SCENARIOS['relation-ready'];
    if (!scenario.retrievalTrace) throw new Error('fixture must provide a trace');
    const mismatchedTrace: RetrievalPhaseTraceV1 = {
      ...scenario.retrievalTrace,
      events: scenario.retrievalTrace.events.map((event) =>
        event.event_type === 'knowledge_card_ready'
          ? {
              ...event,
              knowledge_card_hash:
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
            }
          : event,
      ),
    };
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, mismatchedTrace);
    expect(v.gate).toBe('LOCKED');
    expect(v.candidates).toEqual([]);
    expect(v.gateViolations).toContain('检索轨迹绑定的知识卡版本/哈希与规范资产不一致。');
  });

  it('drops a candidate trace that claims historical detail was included', () => {
    const scenario = MOCK_SCENARIOS['relation-ready'];
    if (!scenario.retrievalTrace) throw new Error('fixture must provide a trace');
    const leakingTrace: RetrievalPhaseTraceV1 = {
      ...scenario.retrievalTrace,
      events: scenario.retrievalTrace.events.map((event) =>
        event.relation_id === '00000000-0000-4000-8000-000000000601'
          ? { ...event, detail_included: true }
          : event,
      ),
    };
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, leakingTrace);
    // The MVP exposes at most one candidate, so a leaking search leaves none.
    // Rendering it anyway would show the user a relation whose own trace says
    // historical detail was already read — the gate would have failed silently.
    expect(v.candidates).toEqual([]);
    expect(v.gateViolations).toContain('候选检索(seq 2)不得包含历史详情。');
  });
});

describe('deriveRelationDiscovery — gate 2: confirmation before detail', () => {
  it('exposes at most one candidate, pending and with detail DENIED', () => {
    // The cap is one. Showing a weaker second relation spends the user's
    // attention and can redirect later reasoning toward an experience that was
    // never relevant, while a missed relation leaves the current asset intact.
    const scenario = MOCK_SCENARIOS['relation-ready'];
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, scenario.retrievalTrace);
    expect(v.gate).toBe('READY');
    expect(v.candidates.length).toBe(1);
    expect(v.candidates[0]?.confirmation).toBe('PENDING');
    expect(v.candidates[0]?.detailAccess).toBe('DENIED_UNTIL_CONFIRMED');
  });

  it('unlocks detail only after the candidate is explicitly confirmed', () => {
    const scenario = MOCK_SCENARIOS['relation-confirmed'];
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, scenario.retrievalTrace);
    expect(v.candidates.length).toBe(1);
    expect(v.candidates[0]?.confirmation).toBe('CONFIRMED');
    expect(v.candidates[0]?.detailAccess).toBe('AVAILABLE');
    expect(v.candidates[0]?.detailRetrieved).toBe(true);
    expect(v.gateViolations).toEqual([]);
  });

  it('carries provenance attributed to both sides', () => {
    // A candidate explained from only one side cannot be checked against the
    // other, so a merged count could look complete while one asset contributed
    // nothing.
    const scenario = MOCK_SCENARIOS['relation-ready'];
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, scenario.retrievalTrace);
    expect(v.candidates[0]?.currentProvenanceRefs.length).toBeGreaterThan(0);
    expect(v.candidates[0]?.historicalProvenanceRefs.length).toBeGreaterThan(0);
  });

  it('uses only the frozen relation vocabulary', () => {
    // A fixture-only label would reach a user-visible surface with no
    // admissibility rule behind it, so its meaning would be undefined.
    const frozen = [
      'SAME_THEME',
      'METHOD_REUSE',
      'COUNTEREXAMPLE',
      'SUPPLEMENT',
      'PREREQUISITE',
      'FOLLOW_UP',
    ];
    for (const id of ['relation-ready', 'relation-confirmed', 'relation-detail-denied'] as const) {
      const scenario = MOCK_SCENARIOS[id];
      const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, scenario.retrievalTrace);
      for (const candidate of v.candidates) {
        expect(frozen).toContain(candidate.relationType);
      }
    }
  });

  it('REFUSES detail retrieval attempted before confirmation (gate violation)', () => {
    const v = deriveRelationDiscovery(
      MOCK_SCENARIOS['relation-ready'].asset,
      MOCK_SCENARIOS['relation-ready'].relationWorkspace,
      trace([
        {
          sequence: 0,
          event_type: 'knowledge_card_ready',
          milestone_state: 'CONFIRMED',
          knowledge_card_version: '00000000-0000-4000-8000-000000000014',
          knowledge_card_hash: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
          explicit_user_acceptance: true,
        },
        {
          sequence: 1,
          event_type: 'relation_candidate_search',
          scope: 'cross_asset_summary',
          detail_included: false,
          relation_id: '00000000-0000-4000-8000-000000000601',
          related_asset_id: '00000000-0000-4000-8000-000000000701',
        },
        {
          sequence: 2,
          event_type: 'relation_detail_retrieval',
          scope: 'cross_asset_detail',
          relation_id: '00000000-0000-4000-8000-000000000601',
          related_asset_id: '00000000-0000-4000-8000-000000000701',
          detail_included: true,
        },
      ]),
    );
    expect(v.candidates.find((x) => x.detailRetrieved)).toBeUndefined();
    expect(v.candidates[0]?.detailAccess).toBe('DENIED_UNTIL_CONFIRMED');
    expect(v.gateViolations.length).toBeGreaterThan(0);
  });

  it('closes detail when a candidate is explicitly declined (denied-detail state)', () => {
    const scenario = MOCK_SCENARIOS['relation-detail-denied'];
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, scenario.retrievalTrace);
    expect(v.gate).toBe('READY');
    expect(v.candidates.length).toBe(1);
    expect(v.candidates[0]?.confirmation).toBe('DECLINED');
    expect(v.candidates[0]?.detailAccess).toBe('DECLINED');
    expect(v.gateViolations).toEqual([]);
  });

  it('does not mark malformed or mutating historical detail as retrieved', () => {
    const scenario = MOCK_SCENARIOS['relation-confirmed'];
    if (!scenario.retrievalTrace) throw new Error('fixture must provide a trace');
    const mutatingTrace: RetrievalPhaseTraceV1 = {
      ...scenario.retrievalTrace,
      events: scenario.retrievalTrace.events.map((event) =>
        event.event_type === 'relation_detail_retrieval'
          ? {
              ...event,
              current_statements_hash_after:
                'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
            }
          : event,
      ),
    };
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, mutatingTrace);
    const confirmed = v.candidates.find(
      (candidate) => candidate.relationId === '00000000-0000-4000-8000-000000000601',
    );
    expect(confirmed?.detailAccess).toBe('AVAILABLE');
    expect(confirmed?.detailRetrieved).toBe(false);
    expect(
      v.gateViolations.some((violation) =>
        violation.includes('违反 bounded-detail 不变量'),
      ),
    ).toBe(true);
  });
});

describe('deriveRelationDiscovery — no-match and invalidation', () => {
  it('reports a valid no-match state with no candidates', () => {
    const scenario = MOCK_SCENARIOS['relation-no-match'];
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, scenario.retrievalTrace);
    expect(v.gate).toBe('READY');
    expect(v.noMatch).toBe(true);
    expect(v.candidates).toEqual([]);
  });

  it('invalidates readiness, candidates and detail when M1–M4 is edited', () => {
    const scenario = MOCK_SCENARIOS['relation-invalidated'];
    const v = deriveRelationDiscovery(scenario.asset, scenario.relationWorkspace, scenario.retrievalTrace);
    expect(v.gate).toBe('INVALIDATED');
    expect(v.invalidated).toBe(true);
    expect(v.candidates).toEqual([]);
    expect(v.noMatch).toBe(false);
    expect(v.invalidationReason).toBeTruthy();
  });
});

describe('relation vocabulary migration', () => {
  it('replaces the pre-E5 mock labels with the frozen vocabulary', () => {
    // `SIMILAR_SITUATION` and `SHARED_METHOD` were fixture-only labels. Leaving
    // either alive would put a relation on a user-visible surface with no
    // admissibility rule behind it, so nothing would define what it claims.
    const migrated = [CANDIDATE_SAME_THEME, CANDIDATE_METHOD_REUSE];
    const labels = migrated.map((candidate) => candidate.relation_type);
    expect(labels).toEqual(['SAME_THEME', 'METHOD_REUSE']);
    expect(JSON.stringify(migrated)).not.toContain('SIMILAR_SITUATION');
    expect(JSON.stringify(migrated)).not.toContain('SHARED_METHOD');
  });

  it('keeps every candidate free of model-written prose', () => {
    // The relation reason is rendered by the Runtime from validated canonical
    // content. Model prose promoted into a durable candidate would become a
    // claim the user attributes to their own evidence.
    for (const candidate of [CANDIDATE_SAME_THEME, CANDIDATE_METHOD_REUSE]) {
      expect(candidate).not.toHaveProperty('reason');
      expect(candidate).not.toHaveProperty('proposed_relation');
      expect(candidate.detail_included).toBe(false);
    }
  });
});
