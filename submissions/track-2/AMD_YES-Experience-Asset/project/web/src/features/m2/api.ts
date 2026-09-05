import type { CriticalMomentMapV1 } from './types';

export interface M2Workspace {
  artifact: CriticalMomentMapV1;
  is_current: boolean;
  history_artifact_ids: string[];
  allowed_actions: ('EDIT' | 'CONFIRM' | 'REGENERATE')[];
}

export interface CurrentM1Version {
  version_id: string;
  milestone_state: string;
}

export interface M2Api {
  getCurrentM1Version(assetId: string): Promise<CurrentM1Version>;
  get(assetId: string): Promise<M2Workspace>;
  create(assetId: string, m1VersionId: string): Promise<M2Workspace>;
  edit(
    assetId: string,
    artifactId: string,
    moments: {
      moment_id: string;
      title: string;
      criticality_status?: 'USER_CONFIRMED' | 'UNRESOLVED';
    }[],
  ): Promise<M2Workspace>;
  confirm(assetId: string, artifactId: string, completeWithGaps: boolean): Promise<M2Workspace>;
}

export class M2ApiError extends Error {
  constructor(message: string, readonly status = 0) { super(message); }
}

export class LiveM2Api {
  constructor(private readonly baseUrl = '') {}

  async getCurrentM1Version(assetId: string): Promise<CurrentM1Version> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/api/v1/m1/assets/${assetId}`, {
        headers: {Accept: 'application/json'},
      });
    } catch {
      throw new M2ApiError('无法连接本地 FastAPI。');
    }
    const body = await response.json() as unknown;
    if (!response.ok) {
      throw new M2ApiError(errorMessage(body, response.status), response.status);
    }
    if (!isRecord(body) || !isRecord(body.asset)
      || typeof body.asset.version_id !== 'string'
      || !isRecord(body.asset.milestone_states)
      || typeof body.asset.milestone_states.M1 !== 'string') {
      throw new M2ApiError('M1 当前版本响应不符合合同。');
    }
    return {
      version_id: body.asset.version_id,
      milestone_state: body.asset.milestone_states.M1,
    };
  }

  private async request(path: string, init?: RequestInit): Promise<M2Workspace> {
    let response: Response;
    try {
      const headers = new Headers(init?.headers);
      headers.set('Accept', 'application/json');
      if (init?.body) headers.set('Content-Type', 'application/json');
      response = await fetch(`${this.baseUrl}${path}`, { ...init, headers });
    } catch { throw new M2ApiError('无法连接本地 FastAPI。'); }
    const body = await response.json() as unknown;
    if (!response.ok) {
      throw new M2ApiError(errorMessage(body, response.status), response.status);
    }
    if (!isWorkspace(body)) throw new M2ApiError('M2 响应不符合合同。');
    return body;
  }

  get(assetId: string) { return this.request(`/api/v1/m2/assets/${assetId}`); }
  create(assetId: string, m1VersionId: string) {
    return this.request(`/api/v1/m2/assets/${assetId}`, {method: 'POST', body: JSON.stringify({expected_m1_version_id: m1VersionId})});
  }
  edit(
    assetId: string,
    artifactId: string,
    moments: {
      moment_id: string;
      title: string;
      criticality_status?: 'USER_CONFIRMED' | 'UNRESOLVED';
    }[],
  ) {
    return this.request(`/api/v1/m2/assets/${assetId}`, {method: 'PATCH', body: JSON.stringify({expected_artifact_id: artifactId, moments})});
  }
  confirm(assetId: string, artifactId: string, completeWithGaps: boolean) {
    return this.request(`/api/v1/m2/assets/${assetId}/confirm`, {method: 'POST', body: JSON.stringify({expected_artifact_id: artifactId, complete_with_gaps: completeWithGaps})});
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function errorMessage(value: unknown, status: number): string {
  return isRecord(value) && typeof value.detail === 'string'
    ? value.detail
    : `HTTP ${status}`;
}

function isWorkspace(value: unknown): value is M2Workspace {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  const artifact = item.artifact as Record<string, unknown> | undefined;
  return typeof item.is_current === 'boolean'
    && Array.isArray(item.history_artifact_ids)
    && item.history_artifact_ids.every(id => typeof id === 'string')
    && Array.isArray(item.allowed_actions)
    && !!artifact
    && typeof artifact.artifact_id === 'string'
    && typeof artifact.asset_id === 'string'
    && typeof artifact.base_m1_version_id === 'string'
    && typeof artifact.state === 'string'
    && Array.isArray(artifact.moments)
    && artifact.moments.every(moment => {
      if (!moment || typeof moment !== 'object') return false;
      const entry = moment as Record<string, unknown>;
      return typeof entry.moment_id === 'string'
        && typeof entry.title === 'string'
        && typeof entry.description === 'string'
        && typeof entry.temporal_status === 'string'
        && Array.isArray(entry.source_statement_ids);
    });
}
