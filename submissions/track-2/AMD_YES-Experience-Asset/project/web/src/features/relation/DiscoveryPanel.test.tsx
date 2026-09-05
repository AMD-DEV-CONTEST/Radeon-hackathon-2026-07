import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {DiscoveryPanel} from './DiscoveryPanel';
import {deriveDiscoveryView} from './discoveryView';
import {DISCOVERY_SCENARIOS} from './fixtures';

function renderPanel(scenario: keyof typeof DISCOVERY_SCENARIOS, props = {}) {
  const view = deriveDiscoveryView(DISCOVERY_SCENARIOS[scenario]);
  return {view, ...render(<DiscoveryPanel view={view} {...props} />)};
}

describe('discovery states derived from backend contracts', () => {
  it('separates the two meanings NOT_READY carries on the wire', () => {
    // Locked and "ready but never searched" arrive as the same outcome value;
    // the readiness record is what tells them apart. Conflating them would
    // either hide the action from a ready card or offer it on a locked one.
    expect(deriveDiscoveryView(DISCOVERY_SCENARIOS.locked).state).toBe('LOCKED');
    expect(deriveDiscoveryView(DISCOVERY_SCENARIOS.idle).state).toBe('IDLE');
    expect(deriveDiscoveryView(DISCOVERY_SCENARIOS.locked).canSearch).toBe(false);
    expect(deriveDiscoveryView(DISCOVERY_SCENARIOS.idle).canSearch).toBe(true);
  });

  it('renders each of the four search states from the contract value', () => {
    const states = Object.fromEntries(
      Object.entries(DISCOVERY_SCENARIOS).map(([name, workspace]) => [
        name,
        deriveDiscoveryView(workspace).state,
      ]),
    );
    expect(states).toMatchObject({
      running: 'RUNNING',
      candidate: 'CANDIDATE',
      no_match: 'NO_MATCH',
      technical_failure: 'TECHNICAL_FAILURE',
      stale: 'STALE',
    });
  });

  it('keeps no-match visually distinct from a technical failure', () => {
    const {unmount} = renderPanel('no_match');
    expect(screen.getByTestId('relation-no-match')).toHaveTextContent('不是失败');
    expect(screen.queryByTestId('relation-failure')).not.toBeInTheDocument();
    unmount();

    renderPanel('technical_failure');
    // An outage says nothing about whether a relation exists; reading it as
    // "none found" would make a five-minute failure look like a conclusion.
    expect(screen.getByTestId('relation-failure')).toHaveTextContent('本地推理服务不可用');
    expect(screen.getByTestId('relation-failure')).toHaveTextContent('可以重试');
    expect(screen.queryByTestId('relation-no-match')).not.toBeInTheDocument();
  });

  it('says plainly when a retry cannot change the answer', () => {
    renderPanel('validation_rejected');
    expect(screen.getByTestId('relation-failure')).toHaveTextContent('重试不会改变结果');
  });

  it('shows the whole validated package and withholds historical detail', () => {
    renderPanel('candidate');

    expect(screen.getByTestId('relation-type')).toHaveTextContent('方法复用');
    expect(screen.getByTestId('relation-mappings')).toHaveTextContent('HAS_ACTION');
    expect(screen.getByTestId('relation-boundary')).toHaveTextContent('HAS_LIMITATION');
    const provenance = screen.getByTestId('relation-provenance');
    expect(provenance).toHaveTextContent('CURRENT');
    expect(provenance).toHaveTextContent('HISTORICAL');
    // Showing detail here would make the confirmation decision moot: the user
    // would already have read what they are deciding whether to read.
    expect(screen.getByTestId('relation-detail-withheld')).toBeInTheDocument();
  });

  it('offers no search while one is in flight', async () => {
    const onSearch = vi.fn();
    renderPanel('running', {onSearch});
    expect(screen.getByTestId('relation-search')).toBeDisabled();

    const user = userEvent.setup();
    const {unmount} = renderPanel('idle', {onSearch});
    await user.click(screen.getAllByTestId('relation-search').at(-1)!);
    expect(onSearch).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('a locked card offers nothing to click', () => {
    renderPanel('locked', {onSearch: vi.fn()});
    expect(screen.getByTestId('relation-locked')).toBeInTheDocument();
    expect(screen.getByTestId('relation-search')).toBeDisabled();
  });

  it('never shows a candidate for a state that has none', () => {
    for (const scenario of ['idle', 'running', 'no_match', 'technical_failure'] as const) {
      const {unmount} = renderPanel(scenario);
      expect(screen.queryByTestId('relation-candidate')).not.toBeInTheDocument();
      unmount();
    }
  });
});

describe('decided states come from the backend record', () => {
  it('renders a confirmation and stops offering the decision', () => {
    renderPanel('confirmed', {onDecide: vi.fn()});
    expect(screen.getByTestId('relation-decision')).toHaveAttribute(
      'data-decision',
      'CONFIRMED',
    );
    expect(screen.getByTestId('relation-confirmed')).toHaveTextContent('只解锁这一个');
    expect(screen.queryByTestId('relation-confirm')).not.toBeInTheDocument();
  });

  it('renders a decline as durable rather than hiding the card', () => {
    renderPanel('declined', {onDecide: vi.fn()});
    // A local filter would hide the candidate while leaving the permission
    // behind it in place, so the screen would disagree with the system.
    expect(screen.getByTestId('relation-candidate')).toBeInTheDocument();
    expect(screen.getByTestId('relation-declined')).toHaveTextContent('持久');
    expect(screen.queryByTestId('relation-decline')).not.toBeInTheDocument();
  });

  it('offers both decisions only while the candidate is undecided', async () => {
    const onDecide = vi.fn();
    const user = userEvent.setup();
    renderPanel('candidate', {onDecide});

    expect(screen.getByTestId('relation-decision')).toHaveAttribute(
      'data-decision',
      'UNDECIDED',
    );
    await user.click(screen.getByTestId('relation-confirm'));
    expect(onDecide).toHaveBeenCalledWith('CONFIRM');
    await user.click(screen.getByTestId('relation-decline'));
    expect(onDecide).toHaveBeenCalledWith('DECLINE');
  });

  it('a confirmed relation is recognised even from the relation record alone', () => {
    const view = deriveDiscoveryView({
      ...DISCOVERY_SCENARIOS.confirmed,
      decisions: [],
    });
    // The relation row is itself proof the confirmation committed; requiring
    // both would let a half-read workspace render an answered candidate as open.
    expect(view.decision).toBe('CONFIRMED');
    expect(view.canDecide).toBe(false);
  });
});

describe('duplicate clicks attach to the running search', () => {
  it('withholds the action while a search is in flight', async () => {
    // Ticket 06 criterion 9. The backend coalesces concurrent requests onto one
    // reservation, but a UI that keeps firing would still queue clicks the user
    // has to wait out, and each returns the same answer.
    const onSearch = vi.fn();
    const user = userEvent.setup();
    renderPanel('running', {onSearch});

    const button = screen.getByTestId('relation-search');
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onSearch).not.toHaveBeenCalled();
  });

  it('labels a retry as a retry, distinct from a first search', () => {
    const {unmount} = renderPanel('technical_failure', {onSearch: vi.fn()});
    expect(screen.getByTestId('relation-search')).toHaveTextContent('重试查找');
    expect(screen.getByTestId('relation-search')).toBeEnabled();
    unmount();

    renderPanel('no_match', {onSearch: vi.fn()});
    // No-match offers the same action without calling it a retry: nothing
    // failed, so inviting a retry would suggest the answer was provisional.
    expect(screen.getByTestId('relation-search')).toHaveTextContent('查找相关经历');
  });
});

describe('an asset changed under an answer already on screen (ticket 09)', () => {
  it('follows the record rather than the last completed search', () => {
    // The search reported CANDIDATE and nothing re-ran it; the candidate has
    // since been marked stale. Reading the outcome alone would keep the screen
    // claiming a live result.
    const view = deriveDiscoveryView(DISCOVERY_SCENARIOS.stale_candidate);
    expect(view.state).toBe('STALE');
    expect(view.stale).toBe(true);
  });

  it('withdraws the decision actions instead of merely labelling them', async () => {
    const onDecide = vi.fn();
    const user = userEvent.setup();
    renderPanel('stale_candidate', {onDecide});

    // Deciding here would mint a permission against a comparison whose basis is
    // gone, and the record would not show that it had.
    expect(screen.queryByTestId('relation-confirm')).not.toBeInTheDocument();
    expect(screen.queryByTestId('relation-decline')).not.toBeInTheDocument();
    await user.click(screen.getByTestId('relation-stale'));
    expect(onDecide).not.toHaveBeenCalled();
  });

  it('says which thing changed and that no search will run on its own', () => {
    renderPanel('stale_candidate');
    const notice = screen.getByTestId('relation-stale');
    expect(notice).toHaveTextContent('资产已变更');
    // Automatic re-running would replace an answer the user reasoned about, at
    // a moment they did not choose, with no signal that it changed.
    expect(notice).toHaveTextContent('不会自动重跑');
    expect(notice).toHaveTextContent('重新就绪');
  });

  it('keeps the confirmation on the record while reporting access as revoked', () => {
    const view = deriveDiscoveryView(DISCOVERY_SCENARIOS.stale_confirmation);
    expect(view.decision).toBe('CONFIRMED');
    expect(view.canReadDetail).toBe(false);

    renderPanel('stale_confirmation');
    // Showing it as never confirmed would misreport the user's own decision
    // back to them; showing it as still granting access would be false.
    expect(screen.getByTestId('relation-detail-revoked')).toHaveTextContent('已被撤销');
    expect(screen.queryByTestId('relation-confirmed')).not.toBeInTheDocument();
  });

  it('still allows an explicitly started new search', () => {
    // Staleness withdraws the answer, not the ability to ask again.
    const view = deriveDiscoveryView(DISCOVERY_SCENARIOS.stale_candidate);
    expect(view.canSearch).toBe(true);
  });
});
