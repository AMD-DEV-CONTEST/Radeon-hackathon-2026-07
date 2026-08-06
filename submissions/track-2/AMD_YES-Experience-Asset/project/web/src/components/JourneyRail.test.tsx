import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { JourneyRail } from './JourneyRail';

describe('JourneyRail', () => {
  it('exposes the current step and keeps all five product stages navigable', () => {
    const onSelect = vi.fn();
    render(<JourneyRail active="m2" onSelect={onSelect} />);

    expect(screen.getAllByRole('button')).toHaveLength(5);
    expect(screen.getByTestId('view-m2')).toHaveAttribute('aria-current', 'step');

    fireEvent.click(screen.getByTestId('view-m4'));
    expect(onSelect).toHaveBeenCalledWith('m4');
  });
});
