import { describe, expect, it } from 'vitest';
import { deriveM4View, STATE_LABELS, type M4ViewState } from './m4View';
import { M4_SCENARIOS } from './fixtures';

const EVERY_STATE: M4ViewState[] = [
  'NOT_STARTED',
  'IN_PROGRESS',
  'NEEDS_INPUT',
  'REVIEW_READY',
  'CONFIRMED',
  'COMPLETE_WITH_GAPS',
  'INVALIDATED',
  'FAILED',
];

describe('M4 view state derivation', () => {
  it('derives each of the eight states from a backend-shaped workspace', () => {
    const derived = Object.fromEntries(
      Object.entries(M4_SCENARIOS).map(([name, workspace]) => [name, deriveM4View(workspace).state]),
    );
    expect(derived).toEqual({
      not_started: 'NOT_STARTED',
      in_progress: 'IN_PROGRESS',
      needs_input: 'NEEDS_INPUT',
      review_ready: 'REVIEW_READY',
      confirmed: 'CONFIRMED',
      complete_with_gaps: 'COMPLETE_WITH_GAPS',
      invalidated: 'INVALIDATED',
      failed: 'FAILED',
    });
  });

  it('labels every state, so no state can render as a blank badge', () => {
    for (const state of EVERY_STATE) {
      expect(STATE_LABELS[state]).toBeTruthy();
    }
  });

  it('prefers the artifact state but keeps a failure visible alongside it', () => {
    // A regeneration that stops over an invalidated map has two things to
    // report. Collapsing them would force a choice between telling the user why
    // the map is stale and telling them why the rebuild stopped.
    const workspace = {
      ...M4_SCENARIOS.invalidated,
      run_status: M4_SCENARIOS.failed.run_status,
    };
    const view = deriveM4View(workspace);
    expect(view.state).toBe('INVALIDATED');
    expect(view.failure?.failure_code).toBe('MODEL_UNAVAILABLE');
  });

  it('reports the actions each state allows', () => {
    expect(deriveM4View(M4_SCENARIOS.not_started)).toMatchObject({
      canCreate: true,
      canEdit: false,
      canRegenerate: false,
    });
    expect(deriveM4View(M4_SCENARIOS.review_ready)).toMatchObject({
      canCreate: false,
      canEdit: true,
      canRegenerate: false,
    });
    // An invalidated map cannot be edited: an edit would build a new version on
    // evidence the user has already corrected.
    expect(deriveM4View(M4_SCENARIOS.invalidated)).toMatchObject({
      canCreate: false,
      canEdit: false,
      canRegenerate: true,
    });
  });

  it('collects visible gaps and indexes evidence for drill-down', () => {
    const view = deriveM4View(M4_SCENARIOS.needs_input);
    expect(view.visibleGaps.map((statement) => statement.role)).toEqual(['COUNTEREXAMPLE']);
    expect(view.visibleGaps[0].gap_reason).toBeTruthy();

    const confirmed = deriveM4View(M4_SCENARIOS.confirmed);
    const cited = M4_SCENARIOS.confirmed.map!.dependency_statement_ids;
    for (const id of cited) {
      expect(confirmed.evidenceById.get(id)?.text).toBeTruthy();
    }
  });
});
