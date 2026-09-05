import type { M3WorkspaceV1 } from './types';
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import workspaceSchema from '../../../../contracts/json-schema/m3-workspace-v1.schema.json';

const ajv = new Ajv2020({allErrors: true, strict: false});
addFormats(ajv);
const validateWorkspaceSchema = ajv.compile(workspaceSchema);

export interface M3Api {
  getCurrentUpstream(assetId: string): Promise<M3UpstreamIdentity>;
  get(assetId: string): Promise<M3WorkspaceV1>;
  create(assetId: string, m2ArtifactId: string, canonicalVersionId: string): Promise<M3WorkspaceV1>;
  regenerate(assetId: string, m2ArtifactId: string, canonicalVersionId: string, invalidatedArtifactId: string): Promise<M3WorkspaceV1>;
  edit(assetId: string, artifactId: string, statements: Array<{statement_id: string; text: string; user_action: 'CONFIRM' | 'MARK_UNRESOLVED'; unresolved_reason?: string}>): Promise<M3WorkspaceV1>;
  confirm(assetId: string, artifactId: string, completeWithGaps: boolean): Promise<M3WorkspaceV1>;
}

export interface M3UpstreamIdentity {
  m2_artifact_id: string;
  canonical_version_id: string;
  m2_state: string;
}

export class M3ApiError extends Error {
  constructor(message: string, readonly status = 0, readonly recoveryAction = '', readonly statusUrl = '') { super(message); }
}

export function validateM3Workspace(value: unknown): M3WorkspaceV1 {
  if (!validateWorkspaceSchema(value)) throw new M3ApiError('M3 响应不符合合同。');
  return value as unknown as M3WorkspaceV1;
}

export class LiveM3Api implements M3Api {
  constructor(private readonly baseUrl = '') {}
  async getCurrentUpstream(assetId: string): Promise<M3UpstreamIdentity> {
    let responses: Response[];
    try {
      responses = await Promise.all([
        fetch(`${this.baseUrl}/api/v1/m2/assets/${assetId}`, {
          headers: {'Accept': 'application/json'},
        }),
        fetch(`${this.baseUrl}/api/v1/m1/assets/${assetId}`, {
          headers: {'Accept': 'application/json'},
        }),
      ]);
    } catch {
      throw new M3ApiError('无法连接本地 FastAPI。');
    }
    const [m2Response, canonicalResponse] = responses;
    const [m2Body, canonicalBody] = await Promise.all([
      m2Response.json() as Promise<unknown>,
      canonicalResponse.json() as Promise<unknown>,
    ]);
    if (!m2Response.ok) throw new M3ApiError(errorMessage(m2Body, m2Response.status), m2Response.status);
    if (!canonicalResponse.ok) throw new M3ApiError(errorMessage(canonicalBody, canonicalResponse.status), canonicalResponse.status);
    const m2Artifact = record(record(m2Body)?.artifact);
    const canonicalAsset = record(record(canonicalBody)?.asset);
    if (
      typeof m2Artifact?.artifact_id !== 'string'
      || typeof m2Artifact.state !== 'string'
      || typeof canonicalAsset?.version_id !== 'string'
    ) {
      throw new M3ApiError('M2/M1 上游身份响应不符合合同。');
    }
    return {
      m2_artifact_id: m2Artifact.artifact_id,
      canonical_version_id: canonicalAsset.version_id,
      m2_state: m2Artifact.state,
    };
  }
  private async request(path: string, init?: RequestInit) {
    let response: Response;
    try { response = await fetch(`${this.baseUrl}${path}`, { ...init, headers: {'Accept': 'application/json', ...(init?.body ? {'Content-Type': 'application/json'} : {})} }); }
    catch { throw new M3ApiError('无法连接本地 FastAPI。'); }
    const body: unknown = await response.json();
    if (!response.ok) {
      const detail = (body as {detail?: unknown}).detail;
      if (typeof detail === 'string') throw new M3ApiError(detail, response.status);
      if (detail && typeof detail === 'object') {
        const value = detail as {message?: string; safe_user_message?: string; recovery_action?: string; status_url?: string};
        if (value.status_url) {
          const status = await fetch(`${this.baseUrl}${value.status_url}`, {headers: {'Accept': 'application/json'}});
          if (status.ok) {
            const outcome = await status.json() as {safe_user_message?: string; recovery_action?: string};
            throw new M3ApiError(outcome.safe_user_message ?? value.message ?? `HTTP ${response.status}`, response.status, outcome.recovery_action ?? '', value.status_url);
          }
        }
        throw new M3ApiError(value.safe_user_message ?? value.message ?? `HTTP ${response.status}`, response.status, value.recovery_action ?? '', value.status_url ?? '');
      }
      throw new M3ApiError(`HTTP ${response.status}`, response.status);
    }
    return validateM3Workspace(body);
  }
  get(assetId: string) { return this.request(`/api/v1/m3/assets/${assetId}`); }
  create(assetId: string, m2ArtifactId: string, canonicalVersionId: string) { return this.request(`/api/v1/m3/assets/${assetId}`, {method: 'POST', body: JSON.stringify({expected_m2_artifact_id: m2ArtifactId, expected_canonical_version_id: canonicalVersionId})}); }
  regenerate(assetId: string, m2ArtifactId: string, canonicalVersionId: string, invalidatedArtifactId: string) { return this.request(`/api/v1/m3/assets/${assetId}/regenerate`, {method: 'POST', body: JSON.stringify({expected_m2_artifact_id: m2ArtifactId, expected_canonical_version_id: canonicalVersionId, expected_invalidated_artifact_id: invalidatedArtifactId})}); }
  edit(assetId: string, artifactId: string, statements: Array<{statement_id: string; text: string; user_action: 'CONFIRM' | 'MARK_UNRESOLVED'; unresolved_reason?: string}>) { return this.request(`/api/v1/m3/assets/${assetId}`, {method: 'PATCH', body: JSON.stringify({expected_artifact_id: artifactId, statements})}); }
  confirm(assetId: string, artifactId: string, completeWithGaps: boolean) { return this.request(`/api/v1/m3/assets/${assetId}/confirm`, {method: 'POST', body: JSON.stringify({expected_artifact_id: artifactId, complete_with_gaps: completeWithGaps})}); }
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function errorMessage(value: unknown, status: number): string {
  const detail = record(value)?.detail;
  return typeof detail === 'string' ? detail : `HTTP ${status}`;
}
