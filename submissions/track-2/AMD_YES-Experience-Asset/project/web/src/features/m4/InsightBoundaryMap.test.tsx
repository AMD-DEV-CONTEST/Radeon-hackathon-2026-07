import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { InsightBoundaryMap } from './InsightBoundaryMap';
import { deriveM4View } from './m4View';
import { M4_SCENARIOS } from './fixtures';
import type { M4WorkspaceV1 } from './types';

function renderMap(workspace: M4WorkspaceV1, handlers = {}) {
  return render(
    <InsightBoundaryMap workspace={workspace} view={deriveM4View(workspace)} {...handlers} />,
  );
}

describe('Insight and Boundary Map rendering', () => {
  it('renders every role, so a lesson never appears without its boundary', () => {
    renderMap(M4_SCENARIOS.confirmed);
    for (const role of [
      'lesson',
      'support',
      'counterfactual',
      'limitation',
      'counterexample',
      'applicability',
    ]) {
      expect(screen.getByTestId(`m4-statement-${role}`)).toBeInTheDocument();
    }
  });

  it('renders a visible gap distinguishably from a supported statement', () => {
    renderMap(M4_SCENARIOS.needs_input);
    const gap = screen.getByTestId('m4-statement-counterexample');
    const supported = screen.getByTestId('m4-statement-support');

    // A gap that renders like a finished lesson leaves the user no signal to
    // go looking for what is absent.
    expect(gap).toHaveAttribute('data-gap', 'true');
    expect(supported).toHaveAttribute('data-gap', 'false');
    expect(within(gap).getByTestId('m4-gap-badge')).toBeInTheDocument();
    expect(within(gap).getByTestId('m4-gap-reason')).toHaveTextContent('来源里没有出现反例');
    expect(within(supported).queryByTestId('m4-gap-badge')).not.toBeInTheDocument();
    expect(screen.getByTestId('m4-gap-summary')).toHaveTextContent('1');
  });

  it('opens the evidence a lesson rests on', async () => {
    const user = userEvent.setup();
    renderMap(M4_SCENARIOS.confirmed);
    const lesson = screen.getByTestId('m4-statement-lesson');
    const details = within(lesson).getByTestId('m4-evidence-details');
    await user.click(within(details).getByText('查看这条依据的原始证据'));
    // Without the drill-down the user can only accept or reject a lesson on
    // its plausibility, which is the judgement the evidence exists to replace.
    expect(within(details).getAllByText(/原始证据/).length).toBeGreaterThan(0);
  });

  it('a gap exposes its reason instead of an empty evidence list', () => {
    renderMap(M4_SCENARIOS.needs_input);
    const gap = screen.getByTestId('m4-statement-counterexample');
    expect(within(gap).queryByTestId('m4-evidence-details')).not.toBeInTheDocument();
    expect(within(gap).getByTestId('m4-gap-reason')).toBeInTheDocument();
  });

  it('states the invalidation reason and refuses editing controls', () => {
    renderMap(M4_SCENARIOS.invalidated, { onStatementTextChange: vi.fn() });
    expect(screen.getByTestId('m4-invalidated')).toHaveTextContent('这张图已失效');
    expect(screen.getByTestId('m4-state-badge')).toHaveTextContent('已失效');
    expect(screen.queryByRole('button', { name: '保存修改' })).not.toBeInTheDocument();
  });

  it('shows a stopped run without pretending a map exists', () => {
    renderMap(M4_SCENARIOS.failed);
    expect(screen.getByTestId('m4-failure')).toHaveTextContent('MODEL_UNAVAILABLE');
    expect(screen.getByTestId('m4-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('m4-insight-list')).not.toBeInTheDocument();
  });

  it('shows generation progress from the run contract', () => {
    renderMap(M4_SCENARIOS.in_progress);
    expect(screen.getByTestId('m4-progress')).toHaveTextContent('正在从已接受的决策账本推导教训');
    expect(screen.getByTestId('m4-state-badge')).toHaveTextContent('生成中');
  });

  it('offers editing only where the state allows it', () => {
    renderMap(M4_SCENARIOS.review_ready, { onStatementTextChange: vi.fn() });
    expect(screen.getAllByRole('button', { name: '保存修改' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: '标为缺口' }).length).toBeGreaterThan(0);
  });
});
