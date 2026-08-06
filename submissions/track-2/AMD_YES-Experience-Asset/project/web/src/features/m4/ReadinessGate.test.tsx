import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { M4Workspace } from './M4Workspace';
import { M4_SCENARIOS } from './fixtures';
import type { M4Api } from './api';
import type {
  DiscoveryLock,
  KnowledgeCardReadinessV1,
  ReadinessApi,
} from './readiness';
import { ReadinessApiError } from './readiness';

const RECORD: KnowledgeCardReadinessV1 = {
  schema_version: '1.0.0',
  readiness_id: '9a2f0f28-6a1c-4c2f-9c4f-6d1a2b3c4d5e',
  asset_id: 'asset-1',
  version_id: 'version-accepted',
  m4_artifact_id: M4_SCENARIOS.review_ready.map!.artifact_id,
  knowledge_card_hash: 'f'.repeat(64),
  milestone_state: 'CONFIRMED',
  explicit_user_acceptance: true,
  accepted_gap_statement_ids: [],
  accepted_at: '2026-08-04T00:00:00+00:00',
  lifecycle: 'ACTIVE',
};

const LOCKED: DiscoveryLock = {
  locked: true,
  outcome: 'NOT_READY',
  reason: '先接受洞察与边界图，才能与其他经历比较。',
};

const AVAILABLE: DiscoveryLock = {locked: false, outcome: null, reason: ''};

function m4Api(scenario = M4_SCENARIOS.review_ready): M4Api {
  return {
    getCurrentUpstream: vi.fn().mockResolvedValue({
      m3_artifact_id: 'm3-current',
      canonical_version_id: 'version-current',
      m3_state: 'CONFIRMED',
    }),
    get: vi.fn().mockResolvedValue(scenario),
    create: vi.fn().mockResolvedValue(scenario),
    regenerate: vi.fn().mockResolvedValue(scenario),
    edit: vi.fn().mockResolvedValue(scenario),
  };
}

function readinessApi(overrides: Partial<ReadinessApi> = {}): ReadinessApi {
  return {
    read: vi.fn().mockResolvedValue(null),
    readDiscoveryLock: vi.fn().mockResolvedValue(LOCKED),
    accept: vi.fn().mockResolvedValue(RECORD),
    ...overrides,
  };
}

describe('readiness gate and the discovery lock', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/?asset=asset-1');
    window.localStorage.clear();
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
    window.localStorage.clear();
  });

  it('locks the discovery action with the reason the backend gave', async () => {
    render(<M4Workspace api={m4Api()} readinessApi={readinessApi()} />);

    await screen.findByTestId('m4-readiness-gate');
    // The lock is the server's outcome value, not a locally computed one: a
    // browser-side lock disagrees with the backend as soon as the card changes
    // in another tab.
    expect(screen.getByTestId('m4-discovery-lock')).toHaveAttribute('data-locked', 'true');
    expect(screen.getByTestId('m4-discovery-locked')).toHaveTextContent('NOT_READY');
    expect(screen.getByTestId('m4-discovery-lock-reason')).toHaveTextContent('先接受');
    expect(screen.getByTestId('m4-readiness-absent')).toBeInTheDocument();
  });

  it('shows the exact bindings once the card is ready', async () => {
    const client = readinessApi({
      read: vi.fn().mockResolvedValue(RECORD),
      readDiscoveryLock: vi.fn().mockResolvedValue(AVAILABLE),
    });
    render(<M4Workspace api={m4Api()} readinessApi={client} />);

    await screen.findByTestId('m4-readiness-bindings');
    expect(screen.getByTestId('m4-readiness-badge')).toHaveTextContent('已确认');
    expect(screen.getByTestId('m4-readiness-bindings')).toHaveTextContent('version-accepted');
    expect(screen.getByTestId('m4-discovery-lock')).toHaveAttribute('data-locked', 'false');
    expect(screen.getByTestId('m4-discovery-available')).toBeInTheDocument();
    expect(screen.queryByTestId('m4-discovery-lock-reason')).not.toBeInTheDocument();
  });

  it('sends the exact identities the acceptance contract requires', async () => {
    const client = readinessApi();
    const user = userEvent.setup();
    render(<M4Workspace api={m4Api()} readinessApi={client} />);

    await screen.findByTestId('m4-readiness-gate');
    await user.click(screen.getByRole('button', {name: '确认这张卡'}));

    expect(client.accept).toHaveBeenCalledWith('asset-1', {
      asset_id: 'asset-1',
      expected_artifact_id: M4_SCENARIOS.review_ready.map!.artifact_id,
      expected_canonical_version_id: M4_SCENARIOS.review_ready.canonical_version_id,
      user_action: 'CONFIRM',
    });
  });

  it('a map holding gaps can only be accepted with them named', async () => {
    const client = readinessApi();
    const user = userEvent.setup();
    render(<M4Workspace api={m4Api(M4_SCENARIOS.needs_input)} readinessApi={client} />);

    await screen.findByTestId('m4-readiness-gate');
    // Confirming would bury the gaps the user was shown, so that path is closed
    // while any remain.
    expect(screen.getByRole('button', {name: '确认这张卡'})).toBeDisabled();

    await user.click(screen.getByRole('button', {name: /带缺口接受/}));
    expect(client.accept).toHaveBeenCalledWith(
      'asset-1',
      expect.objectContaining({
        user_action: 'ACCEPT_WITH_GAPS',
        accepted_gap_statement_ids: M4_SCENARIOS.needs_input
          .map!.entries.flatMap((entry) => entry.statements)
          .filter((statement) => statement.is_visible_gap)
          .map((statement) => statement.statement_id),
      }),
    );
  });

  it('surfaces a refusal and re-reads the gate rather than guessing', async () => {
    const client = readinessApi({
      accept: vi
        .fn()
        .mockRejectedValue(
          new ReadinessApiError('the canonical version changed', 422, 'STALE_VERSION'),
        ),
    });
    const user = userEvent.setup();
    render(<M4Workspace api={m4Api()} readinessApi={client} />);

    await screen.findByTestId('m4-readiness-gate');
    await user.click(screen.getByRole('button', {name: '确认这张卡'}));

    expect(await screen.findByTestId('m4-readiness-error')).toHaveTextContent(
      'the canonical version changed',
    );
    // Two refusals a user must tell apart have opposite next actions, so the
    // gate is re-read from the server instead of being assumed unchanged.
    expect(client.readDiscoveryLock).toHaveBeenCalledTimes(2);
  });

  it('offers no acceptance for a map that cannot be accepted', async () => {
    render(
      <M4Workspace api={m4Api(M4_SCENARIOS.invalidated)} readinessApi={readinessApi()} />,
    );

    await screen.findByTestId('m4-readiness-gate');
    expect(screen.queryByRole('button', {name: '确认这张卡'})).not.toBeInTheDocument();
    expect(screen.getByTestId('m4-discovery-lock')).toHaveAttribute('data-locked', 'true');
  });
});
