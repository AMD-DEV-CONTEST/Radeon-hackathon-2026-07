import { afterEach, describe, expect, it, vi } from 'vitest';
import { LiveM3Api, M3ApiError, validateM3Workspace } from './api';
import { M3_SCENARIOS } from './fixtures';

afterEach(() => vi.unstubAllGlobals());

describe('M3 API contract client', () => {
  it('performs full AJV validation rather than a shallow cast', () => {
    const invalid = structuredClone(M3_SCENARIOS.complete) as unknown as Record<string, unknown>;
    (invalid.artifact as Record<string, unknown>).entries = [];
    expect(() => validateM3Workspace(invalid)).toThrow(M3ApiError);
    expect(validateM3Workspace(M3_SCENARIOS.complete)).toEqual(M3_SCENARIOS.complete);
  });

  it('serializes create, edit, confirm and regeneration CAS identities', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify(M3_SCENARIOS.complete), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ));
    vi.stubGlobal('fetch', fetch);
    const api = new LiveM3Api();
    await api.create('asset', 'm2', 'version');
    await api.edit('asset', 'artifact', [{statement_id: 'statement', text: 'draft', user_action: 'CONFIRM'}]);
    await api.confirm('asset', 'artifact', true);
    await api.regenerate('asset', 'm2-new', 'version-new', 'invalidated');
    expect(fetch.mock.calls.map((call) => JSON.parse(call[1].body))).toEqual([
      {expected_m2_artifact_id: 'm2', expected_canonical_version_id: 'version'},
      {expected_artifact_id: 'artifact', statements: [{statement_id: 'statement', text: 'draft', user_action: 'CONFIRM'}]},
      {expected_artifact_id: 'artifact', complete_with_gaps: true},
      {expected_m2_artifact_id: 'm2-new', expected_canonical_version_id: 'version-new', expected_invalidated_artifact_id: 'invalidated'},
    ]);
  });

  it('resolves the current M2 and canonical identities for the UI', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        artifact: {artifact_id: 'm2-current', state: 'CONFIRMED'},
      }), {status: 200}))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        asset: {version_id: 'version-current'},
      }), {status: 200}));
    vi.stubGlobal('fetch', fetch);

    await expect(new LiveM3Api().getCurrentUpstream('asset')).resolves.toEqual({
      m2_artifact_id: 'm2-current',
      canonical_version_id: 'version-current',
      m2_state: 'CONFIRMED',
    });
    expect(fetch.mock.calls.map(call => call[0])).toEqual([
      '/api/v1/m2/assets/asset',
      '/api/v1/m1/assets/asset',
    ]);
  });

  it('preserves structured stale and policy failure status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({detail: 'stale'}), {status: 409})));
    await expect(new LiveM3Api().get('asset')).rejects.toMatchObject({status: 409});
  });

  it('follows object detail status_url and exposes the safe denial recovery', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({detail: {message: 'blocked', status_url: '/status'}}), {status: 422}))
      .mockResolvedValueOnce(new Response(JSON.stringify({safe_user_message: 'Permission denied safely.', recovery_action: 'Remove the tool request.'}), {status: 200}));
    vi.stubGlobal('fetch', fetch);
    await expect(new LiveM3Api().create('a', 'm', 'v')).rejects.toMatchObject({
      message: 'Permission denied safely.', recoveryAction: 'Remove the tool request.', statusUrl: '/status',
    });
  });
});
