import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { M3Workspace } from './M3Workspace';
import type { M3Api } from './api';

const ASSET = '11111111-1111-4111-8111-111111111111';

const storage = () =>
  ({
    getItem: () => ASSET,
    setItem: () => {},
    removeItem: () => {},
    clear: () => {},
    key: () => null,
    length: 0,
  }) as unknown as Storage;

describe('generation is visibly in flight', () => {
  it('reports the wait while the local model runs, and clears it after', async () => {
    let stop: (reason: unknown) => void = () => {};
    const api = {
      getCurrentUpstream: vi.fn().mockResolvedValue({
        m2_artifact_id: 'a',
        canonical_version_id: 'b',
        m2_state: 'CONFIRMED',
      }),
      get: vi.fn().mockRejectedValue(Object.assign(new Error('not found'), { status: 404 })),
      create: vi.fn(
        () =>
          new Promise((_resolve, reject) => {
            stop = reject;
          }),
      ),
    } as unknown as M3Api;

    render(<M3Workspace api={api} storage={storage()} />);

    await userEvent.click(await screen.findByRole('button', { name: '从当前 M2 生成' }));

    // The local operation remains visibly active without inventing timing.
    expect(await screen.findByTestId('m3-working')).toBeVisible();
    expect(screen.getByRole('button', { name: '处理中…' })).toBeDisabled();

    // However the call settles, the wait state must not outlive it.
    stop(new Error('MODEL_CALL_BUDGET_EXHAUSTED'));

    await screen.findByRole('button', { name: '从当前 M2 生成' });
    expect(screen.queryByTestId('m3-working')).not.toBeInTheDocument();
  });

  it('never states a percentage or an estimate the backend did not publish', async () => {
    const api = {
      getCurrentUpstream: vi.fn().mockResolvedValue({
        m2_artifact_id: 'a',
        canonical_version_id: 'b',
        m2_state: 'CONFIRMED',
      }),
      get: vi.fn().mockRejectedValue(Object.assign(new Error('not found'), { status: 404 })),
      create: vi.fn(() => new Promise(() => {})),
    } as unknown as M3Api;

    render(<M3Workspace api={api} storage={storage()} />);
    await userEvent.click(await screen.findByRole('button', { name: '从当前 M2 生成' }));

    const text = (await screen.findByTestId('m3-working')).textContent ?? '';
    expect(text).not.toMatch(/\d+\s*%/);
    expect(text).not.toMatch(/剩余|还需|预计完成|数十秒|分钟|小时/);
  });
});
