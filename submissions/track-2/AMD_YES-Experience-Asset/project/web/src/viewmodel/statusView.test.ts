import { describe, expect, it } from 'vitest';
import { deriveStatusView } from './statusView';
import { MOCK_SCENARIOS } from '../data/fixtures';
import type { StatusSnapshot } from '../data/provider';

function snap(scenario: keyof typeof MOCK_SCENARIOS): StatusSnapshot {
  return { ...MOCK_SCENARIOS[scenario], source: 'mock', fetchedAt: '2026-07-24T05:00:05Z' };
}

describe('deriveStatusView', () => {
  it('reports health from the contract fields', () => {
    const view = deriveStatusView(snap('healthy'));
    expect(view.health.available).toBe(true);
    expect(view.health.status).toBe('ok');
    expect(view.health.inferenceMode).toBe('local_only');
    expect(view.health.modelProfile).toContain('Qwen');
  });

  it('lists all five milestones with real states and marks the current one', () => {
    const view = deriveStatusView(snap('healthy'));
    expect(view.milestones.map((m) => m.milestone)).toEqual(['M1', 'M2', 'M3', 'M4', 'M5']);
    expect(view.milestones.find((m) => m.milestone === 'M1')?.state).toBe('CONFIRMED');
    expect(view.milestones.find((m) => m.milestone === 'M2')?.isCurrent).toBe(true);
  });

  it('counts confirmed statements and open questions truthfully', () => {
    const view = deriveStatusView(snap('healthy'));
    expect(view.counts).not.toBeNull();
    expect(view.counts?.totalStatements).toBe(4);
    expect(view.counts?.confirmedStatements).toBe(2);
    expect(view.counts?.unresolvedStatements).toBe(1);
    expect(view.counts?.openQuestions).toBe(1);
  });

  it('uses the final public milestone basis and exposes canonical run state', () => {
    const view = deriveStatusView(snap('healthy'));
    expect(view.run?.kind).toBe('progress');
    if (view.run?.kind === 'progress') {
      expect(view.run.percent).toBe(40);
      expect(view.run.percentBasis).toBe('milestones_done/milestones_total');
      expect(view.run.milestonesDone).toBe(2);
      expect(view.run.milestonesTotal).toBe(5);
      expect(view.run.etaSeconds).toBeNull();
      expect(view.run.retrievalScope).toBe('CURRENT_SOURCE');
      expect(view.run.latestPolicyOutcome).toBe('ALLOW');
      expect(view.run.latestToolExecutionStatus).toBe('SUCCEEDED');
      expect(view.run.verificationOutcome).toBe('VERIFIED');
    }
  });

  it('does not turn internal work units into a public percentage', () => {
    const snapshot = snap('healthy');
    if (snapshot.activeRun?.kind !== 'progress') throw new Error('fixture must be progress');
    const view = deriveStatusView({
      ...snapshot,
      activeRun: {
        ...snapshot.activeRun,
        event: {
          ...snapshot.activeRun.event,
          percent: null,
          percent_basis: null,
          milestones_done: null,
          milestones_total: null,
          internal_completed_units: 9,
          internal_total_units: 10,
        },
      },
    });
    expect(view.run?.kind).toBe('progress');
    if (view.run?.kind === 'progress') expect(view.run.percent).toBeNull();
  });

  it('marks a terminal PAUSED run as a safe stop', () => {
    const view = deriveStatusView(snap('safe-stop'));
    expect(view.run?.kind).toBe('terminal');
    if (view.run?.kind === 'terminal') {
      expect(view.run.state).toBe('PAUSED');
      expect(view.run.isSafeStop).toBe(true);
      expect(view.run.retryable).toBe(true);
      expect(view.run.lastDurableVersionId).toBeTruthy();
    }
  });

  it('surfaces a model-unavailable terminal failure with recovery', () => {
    const view = deriveStatusView(snap('terminal-failure'));
    expect(view.run?.kind).toBe('terminal');
    if (view.run?.kind === 'terminal') {
      expect(view.run.state).toBe('MODEL_UNAVAILABLE');
      expect(view.run.isSuccess).toBe(false);
      expect(view.run.recoveryAction).toBeTruthy();
      expect(view.run.internalErrorClass).toBe('LocalModelConnectionError');
    }
  });

  it('detects stale/invalidated content', () => {
    const view = deriveStatusView(snap('stale'));
    expect(view.stale.isStale).toBe(true);
    expect(view.stale.reasons.length).toBeGreaterThan(0);
    expect(view.milestones.find((m) => m.milestone === 'M2')?.isInvalidated).toBe(true);
  });

  it('reports no stale content for a healthy asset', () => {
    const view = deriveStatusView(snap('healthy'));
    expect(view.stale.isStale).toBe(false);
  });

  it('maps every route to an eligibility, filling UNKNOWN when absent', () => {
    const view = deriveStatusView(snap('healthy'));
    expect(view.routes.map((r) => r.route)).toEqual([
      'PRIVATE_SELF',
      'BEGINNER',
      'PEER',
      'CUSTOMER_EVALUATOR',
      'PUBLIC',
    ]);
    expect(view.routes.find((r) => r.route === 'PRIVATE_SELF')?.eligibility).toBe('ELIGIBLE');
    expect(view.routes.find((r) => r.route === 'PUBLIC')?.eligibility).toBe(
      'ELIGIBLE_AFTER_PRIVACY_APPROVAL',
    );
  });

  it('represents the empty (no-instance) state without inventing an asset', () => {
    const view = deriveStatusView(snap('empty'));
    expect(view.version.present).toBe(false);
    expect(view.version.availability).toBe('none');
    expect(view.counts).toBeNull();
    expect(view.milestones).toEqual([]);
    expect(view.run).toBeNull();
  });

  it('reports unavailable health when the snapshot has none', () => {
    const view = deriveStatusView({
      source: 'live',
      scenario: null,
      fetchedAt: '2026-07-24T05:00:05Z',
      health: null,
      healthError: 'connection refused',
      assetAvailability: 'not_served',
      asset: null,
      activeRun: null,
      terminalStates: null,
      retrievalTrace: null,
      relationWorkspace: null,
    });
    expect(view.health.available).toBe(false);
    expect(view.health.status).toBe('unavailable');
    expect(view.health.error).toBe('connection refused');
    expect(view.version.availability).toBe('not_served');
  });
});
