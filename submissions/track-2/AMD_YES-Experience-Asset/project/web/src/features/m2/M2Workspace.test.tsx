import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { M2ApiError, type M2Api, type M2Workspace as Workspace } from './api';
import { M2_SCENARIOS } from './fixtures';
import { M2Workspace } from './M2Workspace';

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

const assetId = M2_SCENARIOS.complete.asset_id;
const currentM1 = {
  version_id: '00000000-0000-4000-8000-000000000780',
  milestone_state: 'CONFIRMED',
};
const regeneratedM1 = {
  version_id: '00000000-0000-4000-8000-000000000781',
  milestone_state: 'CONFIRMED',
};

function workspace(artifact = M2_SCENARIOS.complete): Workspace {
  return {artifact, is_current: true, history_artifact_ids: [artifact.artifact_id], allowed_actions: ['EDIT', 'CONFIRM', 'REGENERATE']};
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return {promise, resolve, reject};
}

describe('M2Workspace autosave', () => {
  it('reads the current M1 version and creates M2 without a hand-entered UUID', async () => {
    const api: M2Api = {
      getCurrentM1Version: vi.fn().mockResolvedValue(currentM1),
      get: vi.fn().mockRejectedValue(new M2ApiError('not found', 404)),
      create: vi.fn().mockResolvedValue(workspace()),
      edit: vi.fn(),
      confirm: vi.fn(),
    };
    localStorage.setItem('experience-asset.m1.active-asset-id', assetId);
    render(<M2Workspace api={api} autosaveDelayMs={0} storage={localStorage} />);

    expect(await screen.findByTestId('m2-current-m1-version')).toHaveTextContent(
      currentM1.version_id,
    );
    expect(screen.queryByText('已接受的 M1 Version ID')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: '从 M1 生成'}));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(
      assetId,
      currentM1.version_id,
    ));
    expect(api.getCurrentM1Version).toHaveBeenCalledTimes(2);
  });

  it('refreshes the canonical M1 version before regenerating invalidated M2', async () => {
    const invalidated = workspace({
      ...M2_SCENARIOS.correction_invalidation,
      asset_id: assetId,
    });
    invalidated.is_current = false;
    const api: M2Api = {
      getCurrentM1Version: vi.fn()
        .mockResolvedValueOnce(currentM1)
        .mockResolvedValueOnce(regeneratedM1),
      get: vi.fn().mockResolvedValue(invalidated),
      create: vi.fn().mockResolvedValue(workspace()),
      edit: vi.fn(),
      confirm: vi.fn(),
    };
    localStorage.setItem('experience-asset.m1.active-asset-id', assetId);
    render(<M2Workspace api={api} autosaveDelayMs={0} storage={localStorage} />);

    await screen.findByText(/依赖的 M1 更正而失效/);
    fireEvent.click(screen.getByRole('button', {name: '按最新 M1 重新生成'}));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(
      assetId,
      regeneratedM1.version_id,
    ));
  });

  it('does not replay an old criticality confirmation during a title-only edit', async () => {
    const confirmedArtifact = {
      ...M2_SCENARIOS.complete,
      state: 'CONFIRMED' as const,
      moments: M2_SCENARIOS.complete.moments.map(moment => ({
        ...moment,
        criticality_status: 'USER_CONFIRMED' as const,
        criticality_confirmed_at: '2026-07-29T07:00:00Z',
      })),
    };
    const api: M2Api = {
      getCurrentM1Version: vi.fn().mockResolvedValue(currentM1),
      get: vi.fn().mockResolvedValue(workspace(confirmedArtifact)),
      create: vi.fn(),
      confirm: vi.fn(),
      edit: vi.fn().mockResolvedValue(workspace({
        ...confirmedArtifact,
        artifact_id: '00000000-0000-4000-8000-000000000795',
        state: 'REVIEW_READY',
        moments: confirmedArtifact.moments.map((moment, index) => index === 0 ? {
          ...moment,
          title: '重新修订的标题',
          criticality_status: 'AGENT_PROPOSED',
          criticality_confirmed_at: null,
        } : moment),
      })),
    };
    localStorage.setItem('experience-asset.m1.active-asset-id', assetId);
    render(<M2Workspace api={api} autosaveDelayMs={0} storage={localStorage} />);

    fireEvent.change(await screen.findByDisplayValue('开始试用网面椅'), {
      target: {value: '重新修订的标题'},
    });
    await waitFor(() => expect(api.edit).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.edit).mock.calls[0][2][0]).not.toHaveProperty(
      'criticality_status',
    );
  });

  it('requires an explicit trusted decision before confirming the map', async () => {
    const proposed = M2_SCENARIOS.incomplete;
    const confirmed = {
      ...proposed,
      artifact_id: '00000000-0000-4000-8000-000000000796',
      moments: proposed.moments.map(moment => ({
        ...moment,
        criticality_status: 'USER_CONFIRMED' as const,
        criticality_confirmed_at: '2026-07-29T07:00:00Z',
      })),
    };
    const api: M2Api = {
      getCurrentM1Version: vi.fn().mockResolvedValue(currentM1),
      get: vi.fn().mockResolvedValue(workspace(proposed)),
      create: vi.fn(),
      edit: vi.fn().mockResolvedValue(workspace(confirmed)),
      confirm: vi.fn().mockResolvedValue(workspace({...confirmed, state: 'COMPLETE_WITH_GAPS'})),
    };
    localStorage.setItem('experience-asset.m1.active-asset-id', assetId);
    render(<M2Workspace api={api} autosaveDelayMs={0} storage={localStorage} />);

    const confirmButton = await screen.findByRole('button', {name: '确认 Critical Moment Map'});
    expect(confirmButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText('关键性 #1'), {
      target: {value: 'USER_CONFIRMED'},
    });
    await waitFor(() => expect(api.edit).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.edit).mock.calls[0][2][0]).toMatchObject({
      criticality_status: 'USER_CONFIRMED',
    });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    fireEvent.click(confirmButton);
    await waitFor(() => expect(api.confirm).toHaveBeenCalledWith(
      proposed.asset_id,
      confirmed.artifact_id,
      true,
    ));
  });

  it('serializes saves and persists typing that occurs during an in-flight save', async () => {
    const first = deferred<Workspace>();
    const secondArtifact = {
      ...M2_SCENARIOS.complete,
      artifact_id: '00000000-0000-4000-8000-000000000799',
      moments: M2_SCENARIOS.complete.moments.map((m, i) => i ? m : {...m, title: '最终标题'}),
    };
    const api: M2Api = {
      getCurrentM1Version: vi.fn().mockResolvedValue(currentM1),
      get: vi.fn().mockResolvedValue(workspace()),
      create: vi.fn(), confirm: vi.fn(),
      edit: vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(workspace(secondArtifact)),
    };
    localStorage.setItem('experience-asset.m1.active-asset-id', assetId);
    render(<M2Workspace api={api} autosaveDelayMs={0} storage={localStorage} />);
    const input = await screen.findByDisplayValue('开始试用网面椅');
    fireEvent.change(input, {target: {value: '第一稿'}});
    await waitFor(() => expect(api.edit).toHaveBeenCalledTimes(1));
    fireEvent.change(input, {target: {value: '最终标题'}});
    first.resolve(workspace({...M2_SCENARIOS.complete, moments: M2_SCENARIOS.complete.moments.map((m, i) => i ? m : {...m, title: '第一稿'})}));
    await waitFor(() => expect(api.edit).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.edit).mock.calls[1][2][0].title).toBe('最终标题');
    expect(input).toHaveValue('最终标题');
  });

  it('rebases a dirty title after 409 and retries without discarding it', async () => {
    const latest = {
      ...M2_SCENARIOS.complete,
      artifact_id: '00000000-0000-4000-8000-000000000798',
      moments: M2_SCENARIOS.complete.moments.map((moment, index) =>
        index === 1 ? {...moment, title: '远端修改的第二个标题'} : moment,
      ),
    };
    const saved = {
      ...latest,
      artifact_id: '00000000-0000-4000-8000-000000000797',
      moments: latest.moments.map((moment, index) =>
        index ? moment : {...moment, title: '保留的本地标题'},
      ),
    };
    const api: M2Api = {
      getCurrentM1Version: vi.fn().mockResolvedValue(currentM1),
      get: vi.fn().mockResolvedValueOnce(workspace()).mockResolvedValueOnce(workspace(latest)),
      create: vi.fn(),
      confirm: vi.fn(),
      edit: vi.fn()
        .mockRejectedValueOnce(new M2ApiError('stale', 409))
        .mockResolvedValueOnce(workspace(saved)),
    };
    localStorage.setItem('experience-asset.m1.active-asset-id', assetId);
    render(<M2Workspace api={api} autosaveDelayMs={0} storage={localStorage} />);
    const input = await screen.findByDisplayValue('开始试用网面椅');
    fireEvent.change(input, {target: {value: '保留的本地标题'}});
    await waitFor(() => expect(api.edit).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.edit).mock.calls[1][1]).toBe(latest.artifact_id);
    expect(vi.mocked(api.edit).mock.calls[1][2][0].title).toBe('保留的本地标题');
    expect(vi.mocked(api.edit).mock.calls[1][2][1].title).toBe('远端修改的第二个标题');
    await waitFor(() => expect(input).toHaveValue('保留的本地标题'));
  });

  it('keeps a local draft visible when a 409 reveals M1 invalidation', async () => {
    const pending = deferred<Workspace>();
    const invalidated = workspace({...M2_SCENARIOS.complete, state: 'INVALIDATED' as const});
    invalidated.is_current = false;
    const api: M2Api = {
      getCurrentM1Version: vi.fn().mockResolvedValue(currentM1),
      get: vi.fn().mockResolvedValueOnce(workspace()).mockResolvedValueOnce(invalidated),
      create: vi.fn(), confirm: vi.fn(),
      edit: vi.fn().mockReturnValueOnce(pending.promise),
    };
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    localStorage.setItem('experience-asset.m1.active-asset-id', assetId);
    render(<M2Workspace api={api} autosaveDelayMs={0} storage={localStorage} />);
    const input = await screen.findByDisplayValue('开始试用网面椅');
    fireEvent.change(input, {target: {value: '待复制的本地标题'}});
    await waitFor(() => expect(api.edit).toHaveBeenCalledTimes(1));
    fireEvent.change(input, {target: {value: '请求期间继续输入的标题'}});
    pending.reject(new M2ApiError('stale', 409));
    await screen.findByText(/本地编辑仍保留/);
    expect(input).toHaveValue('请求期间继续输入的标题');
    await new Promise(resolve => window.setTimeout(resolve, 10));
    expect(api.edit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', {name: '重新载入'}));
    expect(window.confirm).toHaveBeenCalled();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(input).toHaveValue('请求期间继续输入的标题');
  });
});
