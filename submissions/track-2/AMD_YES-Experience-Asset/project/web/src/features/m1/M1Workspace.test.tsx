import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { M1ExperienceWorkspace } from './M1Workspace';
import type { M1Api } from './api';
import type { M1Workspace } from './types';

function workspace(overrides: Partial<M1Workspace> = {}): M1Workspace {
  return {
    asset: {
      asset_id: '00000000-0000-4000-8000-000000000101',
      version_id: '00000000-0000-4000-8000-000000000201',
      lifecycle: 'ACTIVE',
      current_milestone: 'M1',
      milestone_states: { M1: 'NEEDS_INPUT' },
      derivation_metadata: {
        retrieval_scope: 'CURRENT_SOURCE',
        source_content_trusted_as_policy: false,
      },
    },
    brief: {
      schema_version: '0.1.0',
      context: '我第一次购买办公椅，试坐后发现腰部支撑不合适。',
      goal: '',
      constraints: [],
      user_intent: '',
      source_boundary: '我的经历 · PASTED_TEXT · 25 characters',
      source_ids: ['00000000-0000-4000-8000-000000000301'],
      statement_ids: ['00000000-0000-4000-8000-000000000401'],
      confirmed_statement_count: 0,
      unresolved_question_count: 1,
    },
    questions: [
      {
        question_id: '00000000-0000-4000-8000-000000000501',
        question: '你希望这段经历用于什么场景？',
        why_it_matters: '用途会决定 Experience Brief 的目标边界。',
        state: 'OPEN',
      },
    ],
    progress: {
      artifact_state: 'NEEDS_INPUT',
      confirmed_statement_count: 0,
      unresolved_question_count: 1,
      saved_version_id: '00000000-0000-4000-8000-000000000201',
      autosave_state: 'SAVED',
      last_saved_at: '2026-07-28T08:00:00Z',
    },
    progress_event: {
      stage: 'M1_EXPERIENCE_BRIEF',
      state: 'WAITING_FOR_USER',
      message: 'Experience Brief 已保存；1 个问题仍可处理。',
    },
    terminal_state: 'NEEDS_USER_INPUT',
    latest_agent_run: null,
    allowed_actions: ['EDIT', 'ANSWER', 'SKIP', 'DEFER', 'PAUSE', 'CONFIRM'],
    ...overrides,
  };
}

function apiMock(): M1Api {
  return {
    ingest: vi.fn().mockResolvedValue(workspace()),
    get: vi.fn().mockResolvedValue(workspace()),
    edit: vi.fn().mockImplementation(async (_assetId, _versionId, draft) =>
      workspace({
        asset: {
          ...workspace().asset,
          version_id: '00000000-0000-4000-8000-000000000202',
        },
        brief: {
          ...workspace().brief,
          goal: draft.goal,
          constraints: draft.constraints
            .split('\n')
            .map((item: string) => item.trim())
            .filter(Boolean),
        },
      }),
    ),
    question: vi.fn().mockResolvedValue(
      workspace({
        questions: [],
        brief: {
          ...workspace().brief,
          confirmed_statement_count: 1,
          unresolved_question_count: 0,
        },
        progress: {
          ...workspace().progress,
          confirmed_statement_count: 1,
          unresolved_question_count: 0,
        },
      }),
    ),
    pause: vi.fn().mockResolvedValue(
      workspace({
        asset: { ...workspace().asset, lifecycle: 'PAUSED' },
        terminal_state: 'PAUSED',
        allowed_actions: ['RESUME'],
      }),
    ),
    resume: vi.fn().mockResolvedValue(workspace()),
    confirm: vi.fn().mockResolvedValue(
      workspace({
        asset: {
          ...workspace().asset,
          current_milestone: 'M2',
          milestone_states: { M1: 'COMPLETE_WITH_GAPS', M2: 'NOT_STARTED' },
        },
        terminal_state: 'SUCCEEDED',
        allowed_actions: ['EDIT', 'PAUSE'],
      }),
    ),
    runAgent: vi.fn().mockResolvedValue(workspace()),
  };
}

afterEach(() => {
  window.localStorage.clear();
});

describe('M1ExperienceWorkspace', () => {
  it('ingests pasted experience and shows the persisted Brief with explained questions', async () => {
    const api = apiMock();
    const user = userEvent.setup();
    render(<M1ExperienceWorkspace api={api} storage={window.localStorage} />);

    await user.click(screen.getByRole('button', { name: '对话式讲述' }));
    await user.type(screen.getByTestId('m1-source-text'), '一次真实的购买经历。');
    await user.click(screen.getByTestId('m1-start-submit'));

    await waitFor(() => expect(api.ingest).toHaveBeenCalledTimes(1));
    expect(api.ingest).toHaveBeenCalledWith(
      expect.objectContaining({ source_kind: 'CONVERSATION' }),
    );
    expect(screen.getByTestId('m1-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('m1-context')).toHaveValue(
      '我第一次购买办公椅，试坐后发现腰部支撑不合适。',
    );
    expect(screen.getByText('用途会决定 Experience Brief 的目标边界。')).toBeVisible();
    expect(window.localStorage.getItem('experience-asset.m1.active-asset-id')).toBe(
      workspace().asset.asset_id,
    );
  });

  it('autosaves edits against the current version and supports explicit question actions', async () => {
    const api = apiMock();
    const user = userEvent.setup();
    window.localStorage.setItem(
      'experience-asset.m1.active-asset-id',
      workspace().asset.asset_id,
    );
    render(
      <M1ExperienceWorkspace
        api={api}
        storage={window.localStorage}
        autosaveDelayMs={0}
      />,
    );

    await screen.findByTestId('m1-workspace');
    const goal = screen.getByTestId('m1-goal');
    fireEvent.change(goal, { target: { value: '用于以后复用' } });

    await waitFor(() => expect(api.edit).toHaveBeenCalledTimes(1));
    expect(api.edit).toHaveBeenCalledWith(
      workspace().asset.asset_id,
      workspace().asset.version_id,
      expect.objectContaining({ goal: '用于以后复用' }),
    );

    const answer = screen.getByPlaceholderText('输入答案，或选择跳过 / 稍后处理');
    await user.type(answer, '用于个人复盘');
    await user.click(screen.getByRole('button', { name: '回答' }));
    await waitFor(() => expect(api.question).toHaveBeenCalledTimes(1));
    expect(api.question).toHaveBeenCalledWith(
      workspace().asset.asset_id,
      '00000000-0000-4000-8000-000000000202',
      workspace().questions[0].question_id,
      'ANSWER',
      '用于个人复盘',
    );
  });

  it('restores a paused durable version and only exposes resume', async () => {
    const api = apiMock();
    vi.mocked(api.get).mockResolvedValue(
      workspace({
        asset: { ...workspace().asset, lifecycle: 'PAUSED' },
        terminal_state: 'PAUSED',
        allowed_actions: ['RESUME'],
      }),
    );
    window.localStorage.setItem(
      'experience-asset.m1.active-asset-id',
      workspace().asset.asset_id,
    );
    render(<M1ExperienceWorkspace api={api} storage={window.localStorage} />);

    await screen.findByTestId('m1-resume');
    expect(screen.queryByTestId('m1-pause')).toBeNull();
    expect(screen.getByTestId('m1-context')).toBeDisabled();
  });

  it('shows the actual plan, Runtime decision, effect, verification and terminal state', async () => {
    const api = apiMock();
    vi.mocked(api.runAgent).mockResolvedValue(
      workspace({
        latest_agent_run: {
          run_id: '00000000-0000-4000-8000-000000000601',
          model_id: 'Qwen/Qwen2.5-14B-Instruct',
          server_base_url: 'http://127.0.0.1:8000/v1',
          retrieval_scope: 'CURRENT_SOURCE',
          work_plan: {
            goal: '按当前证据检查来源边界',
            revision: 1,
            steps: [
              {
                step_id: '00000000-0000-4000-8000-000000000701',
                step_kind: 'RETRIEVE',
                reason: '只检索当前资产。',
                status: 'SUCCEEDED',
                stop_condition: '获得来源引用。',
              },
              {
                step_id: '00000000-0000-4000-8000-000000000702',
                step_kind: 'VERIFY',
                reason: '验证真实效果。',
                status: 'SUCCEEDED',
                stop_condition: '效果已验证。',
              },
            ],
          },
          retrieved_evidence: [
            {
              retrieval_id: '00000000-0000-4000-8000-000000000801',
              provenance_ref: 'asset:current/statement:source',
              content_hash: 'c'.repeat(64),
              no_match: false,
            },
          ],
          tool_proposals: [
            {
              name: 'search_current_experience',
              permission_granted: false,
            },
          ],
          policy_decisions: [
            {
              outcome: 'ALLOW',
              reason_codes: ['ALLOWLIST_AND_SCOPE_VALID'],
            },
          ],
          tool_executions: [
            {
              tool_name: 'search_current_experience',
              status: 'SUCCEEDED',
              observation_refs: ['asset:current/statement:source'],
            },
          ],
          verification_report: {
            outcome: 'VERIFIED',
            checks: { effect_matches_policy: true },
            finding_codes: [],
            safe_summary: 'Current-source retrieval effect verified.',
          },
          terminal_state: 'SUCCEEDED',
        },
      }),
    );
    window.localStorage.setItem(
      'experience-asset.m1.active-asset-id',
      workspace().asset.asset_id,
    );
    const user = userEvent.setup();
    render(<M1ExperienceWorkspace api={api} storage={window.localStorage} />);

    await screen.findByTestId('m1-run-agent');
    await user.click(screen.getByTestId('m1-agent-permission'));
    await user.click(screen.getByTestId('m1-run-agent'));

    const trace = await screen.findByTestId('m1-agent-trace');
    expect(trace).toHaveTextContent('search_current_experience');
    expect(trace).toHaveTextContent('Current-source retrieval effect verified.');
    expect(api.runAgent).toHaveBeenCalledWith(
      workspace().asset.asset_id,
      workspace().asset.version_id,
      '按当前证据检查这份 Brief 的来源边界',
      true,
    );
  });
});
