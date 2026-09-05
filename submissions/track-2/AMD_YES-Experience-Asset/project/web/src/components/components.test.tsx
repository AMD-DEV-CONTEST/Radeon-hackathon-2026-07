import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { StatusDashboard } from './StatusDashboard';
import { RunActivityPanel } from './RunActivityPanel';
import { EmptyAssetScreen } from './StateScreens';
import { deriveStatusView } from '../viewmodel/statusView';
import { MOCK_SCENARIOS } from '../data/fixtures';
import type { StatusSnapshot } from '../data/provider';

function view(scenario: keyof typeof MOCK_SCENARIOS) {
  const snapshot: StatusSnapshot = {
    ...MOCK_SCENARIOS[scenario],
    source: 'mock',
    fetchedAt: '2026-07-24T05:00:05Z',
  };
  return deriveStatusView(snapshot);
}

describe('StatusDashboard (healthy)', () => {
  it('renders health, version, milestones, counts and routes', () => {
    render(<StatusDashboard view={view('healthy')} />);
    expect(screen.getByTestId('health-panel')).toBeInTheDocument();
    expect(screen.getByTestId('version-panel')).toBeInTheDocument();
    expect(screen.getByTestId('milestone-panel')).toBeInTheDocument();
    expect(screen.getByTestId('counts-panel')).toBeInTheDocument();
    expect(screen.getByTestId('route-panel')).toBeInTheDocument();
    expect(screen.getByTestId('count-confirmed')).toHaveTextContent('2');
    expect(screen.getByTestId('milestone-M1-state')).toHaveTextContent('已确认');
    expect(screen.getByTestId('stale-none')).toBeInTheDocument();
  });
});

describe('RunActivityPanel', () => {
  it('shows percent only with its public milestone basis and no invented ETA', () => {
    render(<RunActivityPanel run={view('healthy').run} />);
    const label = screen.getByTestId('run-progress-label');
    expect(label).toHaveTextContent('40%');
    expect(label).toHaveTextContent('2/5 公开里程碑');
    expect(label).toHaveTextContent('milestones_done/milestones_total');
    expect(screen.getByTestId('run-eta')).toHaveTextContent('后端尚无有依据的估算');
    expect(screen.queryByText(/预计剩余\s*\d/)).toBeNull();
    expect(screen.queryByText(/\d+\s*秒后/)).toBeNull();
    expect(screen.getByTestId('run-progress')).toHaveAttribute('aria-valuenow', '40');
    expect(screen.getByText('CURRENT_SOURCE')).toBeInTheDocument();
    expect(screen.getByText('ALLOW')).toBeInTheDocument();
    expect(screen.getByText('VERIFIED')).toBeInTheDocument();
  });

  it('renders a safe-stop terminal state with recovery action', () => {
    render(<RunActivityPanel run={view('safe-stop').run} />);
    expect(screen.getByTestId('run-terminal-state')).toHaveTextContent('PAUSED');
    expect(screen.getByTestId('run-safe-stop')).toBeInTheDocument();
    expect(screen.getByTestId('run-recovery')).toHaveTextContent('继续');
  });

  it('renders a model-unavailable failure with a safe message and retry flag', () => {
    render(<RunActivityPanel run={view('terminal-failure').run} />);
    expect(screen.getByTestId('run-terminal-state')).toHaveTextContent('MODEL_UNAVAILABLE');
    expect(screen.getByTestId('run-safe-message')).toBeInTheDocument();
    expect(screen.getByTestId('run-retryable')).toBeInTheDocument();
  });
});

describe('RelationDiscoveryPanel (cross-asset discovery states)', () => {
  it('LOCKS candidate discovery until KnowledgeCardReady (no trace on the healthy asset)', () => {
    render(<StatusDashboard view={view('healthy')} />);
    const panel = screen.getByTestId('relation-panel');
    expect(within(panel).getByTestId('relation-gate')).toHaveTextContent('未就绪');
    expect(within(panel).queryByTestId('relation-candidates')).toBeNull();
  });

  it('shows one summary-only candidate when ready, with detail DENIED until confirmed', () => {
    render(<StatusDashboard view={view('relation-ready')} />);
    const panel = screen.getByTestId('relation-panel');
    expect(within(panel).getByTestId('relation-gate')).toHaveTextContent('已就绪');
    const list = within(panel).getByTestId('relation-candidates');
    // One, not a ranked list: a weak second relation costs more attention than
    // a missed one.
    expect(within(list).getAllByRole('listitem').length).toBe(1);
    expect(within(panel).getByTestId(`relation-${'00000000-0000-4000-8000-000000000601'}-summary`)).toHaveTextContent('高并发服务');
    expect(within(panel).getByTestId(`relation-${'00000000-0000-4000-8000-000000000601'}-confirmation`)).toHaveTextContent('待确认');
    expect(within(panel).getByTestId(`relation-${'00000000-0000-4000-8000-000000000601'}-detail`)).toHaveTextContent('需先确认关系');
  });

  it('renders a valid no-match state', () => {
    render(<StatusDashboard view={view('relation-no-match')} />);
    expect(screen.getByTestId('relation-no-match')).toBeInTheDocument();
  });

  it('unlocks detail on the confirmed relation', () => {
    render(<StatusDashboard view={view('relation-confirmed')} />);
    const panel = screen.getByTestId('relation-panel');
    expect(within(panel).getByTestId(`relation-${'00000000-0000-4000-8000-000000000601'}-detail`)).toHaveTextContent('已解锁');
    expect(within(panel).getByTestId(`relation-${'00000000-0000-4000-8000-000000000601'}-confirmation`)).toHaveTextContent('已确认');
  });

  it('shows the transfer boundary alongside the candidate', () => {
    // Similarity without a boundary invites transferring a lesson into a
    // situation the original experience never covered.
    render(<StatusDashboard view={view('relation-ready')} />);
    const panel = screen.getByTestId('relation-panel');
    expect(
      within(panel).getByTestId(`relation-${'00000000-0000-4000-8000-000000000601'}-boundary`),
    ).toHaveTextContent('迁移边界');
  });

  it('closes detail on an explicitly declined relation (denied-detail state)', () => {
    render(<StatusDashboard view={view('relation-detail-denied')} />);
    const panel = screen.getByTestId('relation-panel');
    expect(within(panel).getByTestId(`relation-${'00000000-0000-4000-8000-000000000601'}-confirmation`)).toHaveTextContent('已拒绝');
    expect(within(panel).getByTestId(`relation-${'00000000-0000-4000-8000-000000000601'}-detail`)).toHaveTextContent('已随拒绝关闭');
  });

  it('shows the invalidation notice when M1–M4 is edited after readiness', () => {
    render(<StatusDashboard view={view('relation-invalidated')} />);
    const panel = screen.getByTestId('relation-panel');
    expect(within(panel).getByTestId('relation-gate')).toHaveTextContent('已失效');
    expect(within(panel).getByTestId('relation-invalidated')).toBeInTheDocument();
  });
});

describe('Stale + empty states', () => {
  it('renders a stale notice when a milestone was invalidated', () => {
    render(<StatusDashboard view={view('stale')} />);
    const notice = screen.getByTestId('stale-notice');
    expect(notice).toBeInTheDocument();
    expect(within(notice).getAllByTestId('stale-reason').length).toBeGreaterThan(0);
    expect(screen.getByTestId('milestone-M2-state')).toHaveTextContent('已失效');
  });

  it('renders the empty (no-instance) screen without fabricating an asset', () => {
    render(<StatusDashboard view={view('empty')} />);
    expect(screen.getByTestId('empty-screen')).toBeInTheDocument();
    expect(screen.queryByTestId('version-panel')).toBeNull();
  });

  it('distinguishes a not-served backend from an empty instance', () => {
    render(<EmptyAssetScreen availability="not_served" />);
    expect(screen.getByTestId('empty-message')).toHaveTextContent('后端仅提供健康与终态契约端点');
  });
});
