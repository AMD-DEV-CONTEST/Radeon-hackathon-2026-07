import { describe, expect, it, vi } from 'vitest';
import { LiveM4Api, M4ApiError, validateM4Workspace } from './api';
import { M4_SCENARIOS } from './fixtures';

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe('M4 API contract conformance', () => {
  it('accepts every fixture scenario against the frozen workspace schema', () => {
    for (const [name, workspace] of Object.entries(M4_SCENARIOS)) {
      expect(() => validateM4Workspace(workspace), name).not.toThrow();
    }
  });

  it('rejects a response that does not satisfy the schema', () => {
    // Accepting an off-contract body would let a backend change reach the UI as
    // a rendering bug instead of a contract failure.
    expect(() => validateM4Workspace({ asset_id: 'not-a-uuid' })).toThrow(M4ApiError);
    expect(() =>
      validateM4Workspace({ ...M4_SCENARIOS.confirmed, canonical_content_hash: 'short' }),
    ).toThrow(M4ApiError);
  });

  it('sends the identities the create contract requires', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(M4_SCENARIOS.review_ready));
    vi.stubGlobal('fetch', fetchMock);
    await new LiveM4Api().create('asset-1', 'm3-1', 'version-1');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/m4/assets/asset-1');
    expect(JSON.parse(init.body)).toEqual({
      asset_id: 'asset-1',
      expected_m3_artifact_id: 'm3-1',
      expected_canonical_version_id: 'version-1',
    });
    vi.unstubAllGlobals();
  });

  it('reports the run failure message rather than the bare HTTP status', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response(
          {
            detail: {
              run_id: 'run-1',
              status_url: '/api/v1/m4/assets/asset-1/runs/run-1',
              message: 'M4 stopped safely',
            },
          },
          422,
        ),
      )
      .mockResolvedValueOnce(
        response({ failure: { safe_user_message: '本地推理服务不可用，未保存任何洞察。' } }),
      );
    vi.stubGlobal('fetch', fetchMock);
    // "HTTP 422" would tell the user the request broke. What happened is that
    // generation stopped deliberately and named a reason.
    await expect(new LiveM4Api().create('asset-1', 'm3-1', 'version-1')).rejects.toThrow(
      '本地推理服务不可用',
    );
    vi.unstubAllGlobals();
  });

  it('surfaces a conflict status so the caller can keep the draft', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ detail: 'current M4 changed' }, 409));
    vi.stubGlobal('fetch', fetchMock);
    await expect(
      new LiveM4Api().edit('asset-1', 'artifact-1', [{ statement_id: 's-1', text: 'x' }]),
    ).rejects.toMatchObject({ status: 409 });
    vi.unstubAllGlobals();
  });
});
