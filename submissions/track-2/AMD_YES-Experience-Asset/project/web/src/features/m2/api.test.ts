import { afterEach, describe, expect, it, vi } from 'vitest';
import { LiveM2Api } from './api';
import { M2_SCENARIOS } from './fixtures';

afterEach(() => vi.unstubAllGlobals());

describe('LiveM2Api', () => {
  it('reads the latest canonical M1 identity from the same-origin M1 route', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      asset: {
        version_id: '00000000-0000-4000-8000-000000000780',
        milestone_states: {M1: 'CONFIRMED'},
      },
    }), {status: 200}));
    vi.stubGlobal('fetch', fetch);

    await expect(new LiveM2Api().getCurrentM1Version('asset')).resolves.toEqual({
      version_id: '00000000-0000-4000-8000-000000000780',
      milestone_state: 'CONFIRMED',
    });
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/m1/assets/asset',
      {headers: {Accept: 'application/json'}},
    );
  });

  it('uses the same-origin M2 route and sends optimistic artifact identity', async () => {
    const workspace = {
      artifact: M2_SCENARIOS.complete,
      is_current: true,
      history_artifact_ids: [M2_SCENARIOS.complete.artifact_id],
      allowed_actions: ['EDIT', 'CONFIRM', 'REGENERATE'],
    };
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(workspace), {status: 200}));
    vi.stubGlobal('fetch', fetch);
    await new LiveM2Api().edit(M2_SCENARIOS.complete.asset_id, M2_SCENARIOS.complete.artifact_id, M2_SCENARIOS.complete.moments.map(({moment_id, title}) => ({moment_id, title})));
    expect(fetch).toHaveBeenCalledWith(
      `/api/v1/m2/assets/${M2_SCENARIOS.complete.asset_id}`,
      expect.objectContaining({method: 'PATCH'}),
    );
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({
      expected_artifact_id: M2_SCENARIOS.complete.artifact_id,
    });
  });

  it('preserves 409 so the workspace can offer reload', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({detail: 'stale'}), {status: 409}),
    ));
    await expect(new LiveM2Api().get('asset')).rejects.toEqual(
      expect.objectContaining({status: 409}),
    );
  });

  it('preserves caller headers while enforcing JSON response and request headers', async () => {
    const workspace = {
      artifact: M2_SCENARIOS.complete,
      is_current: true,
      history_artifact_ids: [M2_SCENARIOS.complete.artifact_id],
      allowed_actions: ['EDIT', 'CONFIRM', 'REGENERATE'],
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(workspace), {status: 200}),
    );
    vi.stubGlobal('fetch', fetch);
    const api = new LiveM2Api() as unknown as {
      request(path: string, init?: RequestInit): Promise<unknown>;
    };

    await api.request('/api/v1/m2/assets/asset', {
      method: 'POST',
      headers: {'X-Trace-Id': 'trace-1', Accept: 'text/plain'},
      body: '{}',
    });

    const headers = fetch.mock.calls[0][1].headers as Headers;
    expect(headers.get('X-Trace-Id')).toBe('trace-1');
    expect(headers.get('Accept')).toBe('application/json');
    expect(headers.get('Content-Type')).toBe('application/json');
  });
});
