import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useStatus } from './useStatus';
import { StatusFetchError, type StatusProvider, type StatusSnapshot } from '../data/provider';
import { MOCK_SCENARIOS } from '../data/fixtures';

const EMPTY_ENV = {} as ImportMetaEnv;

function healthySnapshot(): StatusSnapshot {
  return { ...MOCK_SCENARIOS.healthy, source: 'mock', fetchedAt: new Date().toISOString() };
}

describe('useStatus', () => {
  it('transitions loading -> ready and exposes a derived view', async () => {
    const provider: StatusProvider = {
      source: 'mock',
      fetchStatus: vi.fn().mockResolvedValue(healthySnapshot()),
    };
    const factory = () => provider;
    const { result } = renderHook(() => useStatus('', EMPTY_ENV, factory));

    expect(result.current.phase).toBe('loading');
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(result.current.view?.health.available).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('enters a recoverable error state and recovers on retry', async () => {
    const fetchStatus = vi
      .fn<StatusProvider['fetchStatus']>()
      .mockRejectedValueOnce(new StatusFetchError('boom', { retryable: true }))
      .mockResolvedValueOnce(healthySnapshot());
    const provider: StatusProvider = { source: 'mock', fetchStatus };
    const factory = () => provider;

    const { result } = renderHook(() => useStatus('', EMPTY_ENV, factory));

    await waitFor(() => expect(result.current.phase).toBe('error'));
    expect(result.current.error?.retryable).toBe(true);
    expect(result.current.error?.message).toBe('boom');

    act(() => result.current.refresh());

    await waitFor(() => expect(result.current.phase).toBe('ready'));
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    expect(result.current.view).not.toBeNull();
  });
});
