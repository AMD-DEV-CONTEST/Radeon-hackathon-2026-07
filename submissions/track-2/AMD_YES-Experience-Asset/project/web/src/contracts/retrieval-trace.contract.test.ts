/**
 * Contract conformance for the cross-asset relation-discovery fixtures: every
 * retrieval-phase trace the UI renders must validate against the vendored
 * public RAG contract (retrieval-phase-trace-v1.schema.json, draft-07). This is
 * what keeps the trace TS types honest against the reviewed schema.
 */
import { describe, expect, it } from 'vitest';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';

import traceSchema from '../../contracts/json-schema/retrieval-phase-trace-v1.schema.json';
import { RETRIEVAL_TRACES } from '../data/fixtures';

describe('retrieval-phase trace fixtures conform to the vendored RAG contract', () => {
  const ajv = new Ajv({ allErrors: true, strict: false });
  addFormats(ajv);
  const validate = ajv.compile(traceSchema);

  it('has fixtures to validate', () => {
    expect(RETRIEVAL_TRACES.length).toBeGreaterThan(0);
  });

  it.each(RETRIEVAL_TRACES.map((t, i) => [i, t] as const))(
    'trace #%i validates against retrieval-phase-trace-v1',
    (_i, trace) => {
      const ok = validate(trace);
      expect(ok, JSON.stringify(validate.errors)).toBe(true);
    },
  );

  it('every event_type is in the contract enum', () => {
    const allowed = new Set([
      'current_source_retrieval',
      'current_card_changed',
      'knowledge_card_ready',
      'relation_candidate_search',
      'relation_confirmation',
      'relation_detail_retrieval',
      'relation_no_match',
    ]);
    for (const t of RETRIEVAL_TRACES) {
      for (const e of t.events) {
        expect(allowed.has(e.event_type)).toBe(true);
      }
    }
  });
});
