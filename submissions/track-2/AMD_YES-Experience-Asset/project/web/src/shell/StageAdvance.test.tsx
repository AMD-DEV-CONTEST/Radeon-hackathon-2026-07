import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { StageAdvance } from './StageAdvance';
import type { MilestoneView } from '../viewmodel/statusView';

const milestone = (
  name: string,
  state: MilestoneView['state'],
  isConfirmed: boolean,
): MilestoneView =>
  ({
    milestone: name,
    state,
    isConfirmed,
    isInvalidated: false,
    isCurrent: false,
  }) as MilestoneView;

describe('StageAdvance', () => {
  it('offers the next stage once the backend confirmed this one', async () => {
    const onSelect = vi.fn();
    render(
      <StageAdvance
        activeView="m2"
        milestones={[milestone('M2', 'CONFIRMED', true)]}
        onSelect={onSelect}
      />,
    );

    await userEvent.click(screen.getByTestId('shell-advance-go'));

    expect(onSelect).toHaveBeenCalledWith('m3');
  });

  it('states the gate instead of offering a step the API would reject', () => {
    render(
      <StageAdvance
        activeView="m2"
        milestones={[milestone('M2', 'IN_PROGRESS', false)]}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('shell-advance-go')).not.toBeInTheDocument();
    expect(screen.getByTestId('shell-advance')).toHaveTextContent('确认 M2 后才能生成 M3');
  });

  it('does not offer M5 until the Knowledge Card readiness gate is open', () => {
    const { rerender } = render(
      <StageAdvance
        activeView="m4"
        milestones={[milestone('M4', 'CONFIRMED', true)]}
        relation={{available: true, gate: 'LOCKED'} as never}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('shell-advance-go')).not.toBeInTheDocument();
    expect(screen.getByTestId('shell-advance')).toHaveTextContent('接受 M4 Knowledge Card');

    rerender(
      <StageAdvance
        activeView="m4"
        milestones={[milestone('M4', 'CONFIRMED', true)]}
        relation={{available: true, gate: 'READY'} as never}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByTestId('shell-advance-go')).toHaveTextContent('进入 M5');
  });

  it('renders nothing on the status view or after the last stage', () => {
    const { container, rerender } = render(
      <StageAdvance
        activeView="status"
        milestones={[milestone('M1', 'CONFIRMED', true)]}
        onSelect={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();

    rerender(
      <StageAdvance
        activeView="m5"
        milestones={[milestone('M5', 'CONFIRMED', true)]}
        onSelect={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('stays silent until the backend has actually reported the milestone', () => {
    const { container } = render(
      <StageAdvance activeView="m3" milestones={[]} onSelect={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
