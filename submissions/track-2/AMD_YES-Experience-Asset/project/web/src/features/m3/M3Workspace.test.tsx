import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { M3ApiError, type M3Api } from './api';
import { M3_SCENARIOS } from './fixtures';
import { M3Workspace } from './M3Workspace';

function api(): M3Api {
  return {
    getCurrentUpstream: vi.fn().mockResolvedValue({
      m2_artifact_id: 'm2-current',
      canonical_version_id: 'version-current',
      m2_state: 'CONFIRMED',
    }),
    get: vi.fn().mockResolvedValue(M3_SCENARIOS.complete),
    create: vi.fn().mockResolvedValue(M3_SCENARIOS.complete),
    edit: vi.fn().mockResolvedValue(M3_SCENARIOS.complete),
    confirm: vi.fn().mockResolvedValue(M3_SCENARIOS.complete),
    regenerate: vi.fn().mockResolvedValue(M3_SCENARIOS.complete),
  };
}

describe('M3 workspace explicit review controls', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/?asset=asset-1');
    window.localStorage.clear();
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
    window.localStorage.clear();
  });

  it('keeps text as a draft until CONFIRM or MARK_UNRESOLVED is selected', async () => {
    const client = api();
    const user = userEvent.setup();
    render(<M3Workspace api={client} />);
    const textbox = await screen.findByRole('textbox', {name: '替代方案'});
    await user.type(textbox, ' draft');
    expect(client.edit).not.toHaveBeenCalled();
    await user.click(screen.getAllByRole('button', {name: 'CONFIRM'})[0]);
    expect(client.edit).toHaveBeenCalledWith(
      'asset-1',
      M3_SCENARIOS.complete.artifact.artifact_id,
      [expect.objectContaining({user_action: 'CONFIRM'})],
    );
  });

  it('preserves a draft when a stale save returns 409', async () => {
    const client = api();
    client.edit = vi.fn().mockRejectedValue(Object.assign(new Error('stale'), {status: 409}));
    const user = userEvent.setup();
    render(<M3Workspace api={client} />);
    const textbox = await screen.findByRole('textbox', {name: '替代方案'});
    await user.type(textbox, ' draft');
    await user.click(screen.getAllByRole('button', {name: 'CONFIRM'})[0]);
    expect((textbox as HTMLTextAreaElement).value).toContain('draft');
    expect(screen.getByRole('alert')).toHaveTextContent('stale');
  });

  it('offers ledger confirmation and explicit regeneration', async () => {
    const client = api();
    const user = userEvent.setup();
    render(<M3Workspace api={client} />);
    await screen.findByRole('textbox', {name: '替代方案'});
    await user.click(screen.getByRole('button', {name: '确认账本'}));
    expect(client.confirm).toHaveBeenCalled();
    expect(screen.getByRole('button', {name: '重新生成'})).toBeDisabled();
  });

  it('explicit reload clears drafts', async () => {
    const client = api(); const user = userEvent.setup();
    render(<M3Workspace api={client} />);
    const textbox = await screen.findByRole('textbox', {name: '替代方案'});
    await user.type(textbox, ' draft');
    await user.click(screen.getByRole('button', {name: '重新载入'}));
    expect(screen.getByRole('textbox', {name: '替代方案'})).not.toHaveValue(expect.stringContaining('draft'));
  });

  it('refreshes upstream identities and creates without UUID entry', async () => {
    const client = api();
    const onStatusChange = vi.fn();
    client.get = vi.fn().mockRejectedValue(new M3ApiError('not found', 404));
    const user = userEvent.setup();
    render(<M3Workspace api={client} onStatusChange={onStatusChange} />);
    await screen.findByText('m2-current');
    await user.click(screen.getByRole('button', {name: '从当前 M2 生成'}));
    expect(client.create).toHaveBeenCalledWith(
      'asset-1',
      'm2-current',
      'version-current',
    );
    expect(screen.queryByLabelText('M2 Artifact ID')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Canonical Version ID')).not.toBeInTheDocument();
    expect(onStatusChange).toHaveBeenCalledTimes(1);
  });
});
