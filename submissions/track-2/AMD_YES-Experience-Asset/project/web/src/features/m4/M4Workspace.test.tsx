import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { M4ApiError, type M4Api } from './api';
import { M4_SCENARIOS } from './fixtures';
import { M4Workspace } from './M4Workspace';

function api(overrides: Partial<M4Api> = {}): M4Api {
  return {
    getCurrentUpstream: vi.fn().mockResolvedValue({
      m3_artifact_id: 'm3-current',
      canonical_version_id: 'version-current',
      m3_state: 'CONFIRMED',
    }),
    get: vi.fn().mockResolvedValue(M4_SCENARIOS.review_ready),
    create: vi.fn().mockResolvedValue(M4_SCENARIOS.review_ready),
    regenerate: vi.fn().mockResolvedValue(M4_SCENARIOS.review_ready),
    edit: vi.fn().mockResolvedValue(M4_SCENARIOS.review_ready),
    ...overrides,
  };
}

describe('M4 workspace', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/?asset=asset-1');
    window.localStorage.clear();
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
    window.localStorage.clear();
  });

  it('reads upstream identity itself instead of asking for UUIDs', async () => {
    const client = api({ get: vi.fn().mockRejectedValue(new M4ApiError('not found', 404)) });
    const user = userEvent.setup();
    render(<M4Workspace api={client} />);
    await screen.findByText('m3-current');
    await user.click(screen.getByRole('button', { name: '从当前 M3 生成' }));
    expect(client.create).toHaveBeenCalledWith('asset-1', 'm3-current', 'version-current');
    expect(screen.queryByLabelText('M3 Artifact ID')).not.toBeInTheDocument();
  });

  it('keeps an edit as a draft until it is explicitly saved', async () => {
    const client = api();
    const user = userEvent.setup();
    render(<M4Workspace api={client} />);
    const textbox = await screen.findByRole('textbox', { name: '迁移条件' });
    await user.type(textbox, ' 补充');
    expect(client.edit).not.toHaveBeenCalled();
    await user.click(screen.getAllByRole('button', { name: '保存修改' }).at(-1)!);
    expect(client.edit).toHaveBeenCalledWith(
      'asset-1',
      M4_SCENARIOS.review_ready.map!.artifact_id,
      [expect.objectContaining({ text: expect.stringContaining('补充') })],
    );
  });

  it('marking a gap sends the flag and a reason together', async () => {
    const client = api();
    const user = userEvent.setup();
    render(<M4Workspace api={client} />);
    await screen.findByRole('textbox', { name: '教训' });
    await user.click(screen.getAllByRole('button', { name: '标为缺口' })[0]);
    // The contract rejects a gap without a reason, so the UI must never send
    // the flag on its own.
    expect(client.edit).toHaveBeenCalledWith(
      'asset-1',
      M4_SCENARIOS.review_ready.map!.artifact_id,
      [expect.objectContaining({ is_visible_gap: true, gap_reason: expect.any(String) })],
    );
  });

  it('preserves the draft when a stale save is rejected', async () => {
    const client = api({
      edit: vi.fn().mockRejectedValue(new M4ApiError('current M4 changed', 409)),
    });
    const user = userEvent.setup();
    render(<M4Workspace api={client} />);
    const textbox = await screen.findByRole('textbox', { name: '迁移条件' });
    await user.type(textbox, ' 补充');
    await user.click(screen.getAllByRole('button', { name: '保存修改' }).at(-1)!);
    expect((textbox as HTMLTextAreaElement).value).toContain('补充');
    expect(screen.getByTestId('m4-error')).toHaveTextContent('current M4 changed');
  });

  it('offers regeneration only once the map is invalidated', async () => {
    const invalidated = api({ get: vi.fn().mockResolvedValue(M4_SCENARIOS.invalidated) });
    const user = userEvent.setup();
    const { unmount } = render(<M4Workspace api={invalidated} />);
    await screen.findByTestId('m4-invalidated');
    await user.click(screen.getByRole('button', { name: '重新生成' }));
    expect(invalidated.regenerate).toHaveBeenCalledWith(
      'asset-1',
      'm3-current',
      'version-current',
      M4_SCENARIOS.invalidated.map!.artifact_id,
    );
    unmount();

    const live = api();
    render(<M4Workspace api={live} />);
    await screen.findByRole('textbox', { name: '教训' });
    expect(screen.getByRole('button', { name: '重新生成' })).toBeDisabled();
  });

  it('reloads after a stopped run so the terminal state replaces the pre-run view', async () => {
    const get = vi
      .fn()
      .mockResolvedValueOnce(M4_SCENARIOS.not_started)
      .mockResolvedValue(M4_SCENARIOS.failed);
    const client = api({
      get,
      create: vi.fn().mockRejectedValue(new M4ApiError('M4 stopped safely', 422)),
    });
    const user = userEvent.setup();
    render(<M4Workspace api={client} />);
    await screen.findByTestId('m4-empty');
    await user.click(screen.getByRole('button', { name: '从当前 M3 生成' }));
    expect(await screen.findByTestId('m4-failure')).toHaveTextContent('MODEL_UNAVAILABLE');
  });
});
