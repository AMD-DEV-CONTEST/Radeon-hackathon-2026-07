import { afterEach, describe, expect, it, vi } from 'vitest';
import { LiveM1Api, M1ApiError } from './api';

function validWorkspace() {
  return {
    asset: {
      asset_id: '00000000-0000-4000-8000-000000000101',
      version_id: '00000000-0000-4000-8000-000000000201',
      lifecycle: 'ACTIVE',
      current_milestone: 'M1',
      milestone_states: { M1: 'NEEDS_INPUT' },
      derivation_metadata: { retrieval_scope: 'CURRENT_SOURCE' },
    },
    brief: {
      schema_version: '0.1.0',
      context: 'One source-linked event.',
      goal: '',
      constraints: [],
      user_intent: '',
      source_boundary: 'fixture',
      source_ids: ['00000000-0000-4000-8000-000000000301'],
      statement_ids: ['00000000-0000-4000-8000-000000000401'],
      confirmed_statement_count: 0,
      unresolved_question_count: 0,
    },
    questions: [],
    progress: {
      artifact_state: 'REVIEW_READY',
      confirmed_statement_count: 0,
      unresolved_question_count: 0,
      saved_version_id: '00000000-0000-4000-8000-000000000201',
      autosave_state: 'SAVED',
      last_saved_at: '2026-07-28T08:00:00Z',
    },
    progress_event: {
      stage: 'M1_EXPERIENCE_BRIEF',
      state: 'TERMINAL',
      message: 'Saved.',
    },
    terminal_state: 'SUCCEEDED',
    latest_agent_run: null,
    allowed_actions: ['EDIT', 'PAUSE', 'RUN_AGENT_CURRENT', 'CONFIRM'],
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('LiveM1Api', () => {
  it('uses the same-origin typed route and accepts the frozen workspace projection', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(validWorkspace()), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await new LiveM1Api('').get(
      '00000000-0000-4000-8000-000000000101',
    );

    expect(result.brief.schema_version).toBe('0.1.0');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/m1/assets/00000000-0000-4000-8000-000000000101',
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: 'application/json' }),
      }),
    );
  });

  it('fails visibly when a successful response violates M1WorkspaceV1', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ terminal_state: 'SUCCEEDED' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    await expect(new LiveM1Api('').get('broken')).rejects.toEqual(
      expect.objectContaining<M1ApiError>({
        name: 'M1ApiError',
        message: '本地后端响应不符合 M1WorkspaceV1 合同。',
        status: 0,
      }),
    );
  });
});
