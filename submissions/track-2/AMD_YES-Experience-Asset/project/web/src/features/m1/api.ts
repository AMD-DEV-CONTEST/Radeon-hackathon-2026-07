import type { M1Draft, M1IngestRequest, M1Workspace } from './types';

export class M1ApiError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = 'M1ApiError';
    this.status = status;
  }
}

export interface M1Api {
  ingest(request: M1IngestRequest): Promise<M1Workspace>;
  get(assetId: string): Promise<M1Workspace>;
  edit(assetId: string, versionId: string, draft: M1Draft): Promise<M1Workspace>;
  question(
    assetId: string,
    versionId: string,
    questionId: string,
    action: 'ANSWER' | 'SKIP' | 'DEFER',
    answer?: string,
  ): Promise<M1Workspace>;
  pause(assetId: string, versionId: string): Promise<M1Workspace>;
  resume(assetId: string, versionId: string): Promise<M1Workspace>;
  confirm(assetId: string, versionId: string, completeWithGaps: boolean): Promise<M1Workspace>;
  runAgent(
    assetId: string,
    versionId: string,
    userGoal: string,
    allowCurrentSourceSearch: boolean,
  ): Promise<M1Workspace>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function parseWorkspace(value: unknown): M1Workspace {
  if (
    !isRecord(value) ||
    !isRecord(value.asset) ||
    typeof value.asset.asset_id !== 'string' ||
    typeof value.asset.version_id !== 'string' ||
    (value.asset.lifecycle !== 'ACTIVE' && value.asset.lifecycle !== 'PAUSED') ||
    typeof value.asset.current_milestone !== 'string' ||
    !isRecord(value.asset.milestone_states) ||
    !isRecord(value.asset.derivation_metadata) ||
    !isRecord(value.brief) ||
    value.brief.schema_version !== '0.1.0' ||
    typeof value.brief.context !== 'string' ||
    typeof value.brief.goal !== 'string' ||
    !isStringArray(value.brief.constraints) ||
    typeof value.brief.user_intent !== 'string' ||
    typeof value.brief.source_boundary !== 'string' ||
    !isStringArray(value.brief.source_ids) ||
    !isStringArray(value.brief.statement_ids) ||
    typeof value.brief.confirmed_statement_count !== 'number' ||
    typeof value.brief.unresolved_question_count !== 'number' ||
    !Array.isArray(value.questions) ||
    !value.questions.every(
      (question) =>
        isRecord(question) &&
        typeof question.question_id === 'string' &&
        typeof question.question === 'string' &&
        typeof question.why_it_matters === 'string' &&
        (question.state === 'OPEN' || question.state === 'DEFERRED'),
    ) ||
    !isRecord(value.progress) ||
    typeof value.progress.artifact_state !== 'string' ||
    typeof value.progress.confirmed_statement_count !== 'number' ||
    typeof value.progress.unresolved_question_count !== 'number' ||
    typeof value.progress.saved_version_id !== 'string' ||
    value.progress.autosave_state !== 'SAVED' ||
    typeof value.progress.last_saved_at !== 'string' ||
    !isRecord(value.progress_event) ||
    typeof value.progress_event.stage !== 'string' ||
    typeof value.progress_event.state !== 'string' ||
    typeof value.progress_event.message !== 'string' ||
    !Array.isArray(value.allowed_actions) ||
    !isStringArray(value.allowed_actions) ||
    (value.latest_agent_run !== null &&
      value.latest_agent_run !== undefined &&
      !isRecord(value.latest_agent_run)) ||
    typeof value.terminal_state !== 'string'
  ) {
    throw new M1ApiError('本地后端响应不符合 M1WorkspaceV1 合同。');
  }
  return value as unknown as M1Workspace;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as unknown;
    if (isRecord(body) && typeof body.detail === 'string') return body.detail;
  } catch {
    // Fall through to the stable HTTP error below.
  }
  return `本地后端返回 HTTP ${response.status}。`;
}

export class LiveM1Api implements M1Api {
  private readonly baseUrl: string;

  constructor(baseUrl = '') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  private async request(path: string, init?: RequestInit): Promise<M1Workspace> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          Accept: 'application/json',
          ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
          ...init?.headers,
        },
      });
    } catch {
      throw new M1ApiError(
        '无法连接本地 FastAPI。请确认后端已在 127.0.0.1 运行。',
        0,
      );
    }
    if (!response.ok) throw new M1ApiError(await readError(response), response.status);
    return parseWorkspace((await response.json()) as unknown);
  }

  ingest(request: M1IngestRequest): Promise<M1Workspace> {
    return this.request('/api/v1/m1/assets', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  get(assetId: string): Promise<M1Workspace> {
    return this.request(`/api/v1/m1/assets/${assetId}`);
  }

  edit(assetId: string, versionId: string, draft: M1Draft): Promise<M1Workspace> {
    return this.request(`/api/v1/m1/assets/${assetId}/brief`, {
      method: 'PATCH',
      body: JSON.stringify({
        expected_version_id: versionId,
        context: draft.context,
        goal: draft.goal,
        constraints: draft.constraints
          .split('\n')
          .map((item) => item.trim())
          .filter(Boolean),
        user_intent: draft.userIntent,
        change_reason: 'Autosave from the local M1 workspace.',
      }),
    });
  }

  question(
    assetId: string,
    versionId: string,
    questionId: string,
    action: 'ANSWER' | 'SKIP' | 'DEFER',
    answer?: string,
  ): Promise<M1Workspace> {
    return this.request(`/api/v1/m1/assets/${assetId}/questions/${questionId}`, {
      method: 'POST',
      body: JSON.stringify({
        expected_version_id: versionId,
        action,
        ...(action === 'ANSWER' ? { answer } : {}),
      }),
    });
  }

  pause(assetId: string, versionId: string): Promise<M1Workspace> {
    return this.versionAction(assetId, versionId, 'pause');
  }

  resume(assetId: string, versionId: string): Promise<M1Workspace> {
    return this.versionAction(assetId, versionId, 'resume');
  }

  confirm(
    assetId: string,
    versionId: string,
    completeWithGaps: boolean,
  ): Promise<M1Workspace> {
    return this.request(`/api/v1/m1/assets/${assetId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({
        expected_version_id: versionId,
        complete_with_gaps: completeWithGaps,
      }),
    });
  }

  runAgent(
    assetId: string,
    versionId: string,
    userGoal: string,
    allowCurrentSourceSearch: boolean,
  ): Promise<M1Workspace> {
    return this.request(`/api/v1/m1/assets/${assetId}/agent-runs`, {
      method: 'POST',
      body: JSON.stringify({
        expected_version_id: versionId,
        user_goal: userGoal,
        allow_current_source_search: allowCurrentSourceSearch,
      }),
    });
  }

  private versionAction(
    assetId: string,
    versionId: string,
    action: 'pause' | 'resume',
  ): Promise<M1Workspace> {
    return this.request(`/api/v1/m1/assets/${assetId}/${action}`, {
      method: 'POST',
      body: JSON.stringify({ expected_version_id: versionId }),
    });
  }
}
