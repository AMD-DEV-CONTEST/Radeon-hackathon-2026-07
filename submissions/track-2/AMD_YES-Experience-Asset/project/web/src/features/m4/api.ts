import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import workspaceSchema from '../../../../contracts/json-schema/m4-workspace-v1.schema.json';
import type { M4WorkspaceV1 } from './types';

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validateWorkspaceSchema = ajv.compile(workspaceSchema);

export interface M4StatementEdit {
  statement_id: string;
  text?: string;
  source_statement_ids?: string[];
  source_decision_ids?: string[];
  is_visible_gap?: boolean;
  gap_reason?: string;
}

export interface M4UpstreamIdentity {
  m3_artifact_id: string;
  canonical_version_id: string;
  m3_state: string;
}

export interface M4Api {
  getCurrentUpstream(assetId: string): Promise<M4UpstreamIdentity>;
  get(assetId: string): Promise<M4WorkspaceV1>;
  create(assetId: string, m3ArtifactId: string, canonicalVersionId: string): Promise<M4WorkspaceV1>;
  regenerate(
    assetId: string,
    m3ArtifactId: string,
    canonicalVersionId: string,
    invalidatedArtifactId: string,
  ): Promise<M4WorkspaceV1>;
  edit(assetId: string, artifactId: string, edits: M4StatementEdit[]): Promise<M4WorkspaceV1>;
}

export class M4ApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    readonly statusUrl = '',
  ) {
    super(message);
  }
}

export function validateM4Workspace(value: unknown): M4WorkspaceV1 {
  if (!validateWorkspaceSchema(value)) throw new M4ApiError('M4 响应不符合合同。');
  return value as unknown as M4WorkspaceV1;
}

export class LiveM4Api implements M4Api {
  constructor(private readonly baseUrl = '') {}

  async getCurrentUpstream(assetId: string): Promise<M4UpstreamIdentity> {
    let responses: Response[];
    try {
      responses = await Promise.all([
        fetch(`${this.baseUrl}/api/v1/m3/assets/${assetId}`, {
          headers: { Accept: 'application/json' },
        }),
        fetch(`${this.baseUrl}/api/v1/m1/assets/${assetId}`, {
          headers: { Accept: 'application/json' },
        }),
      ]);
    } catch {
      throw new M4ApiError('无法连接本地 FastAPI。');
    }
    const [m3Response, canonicalResponse] = responses;
    const [m3Body, canonicalBody] = await Promise.all([
      m3Response.json() as Promise<unknown>,
      canonicalResponse.json() as Promise<unknown>,
    ]);
    if (!m3Response.ok) throw new M4ApiError(errorMessage(m3Body, m3Response.status), m3Response.status);
    if (!canonicalResponse.ok) {
      throw new M4ApiError(errorMessage(canonicalBody, canonicalResponse.status), canonicalResponse.status);
    }
    const m3Artifact = record(record(m3Body)?.artifact);
    const canonicalAsset = record(record(canonicalBody)?.asset);
    if (
      typeof m3Artifact?.artifact_id !== 'string'
      || typeof m3Artifact.state !== 'string'
      || typeof canonicalAsset?.version_id !== 'string'
    ) {
      throw new M4ApiError('M3/M1 上游身份响应不符合合同。');
    }
    return {
      m3_artifact_id: m3Artifact.artifact_id,
      canonical_version_id: canonicalAsset.version_id,
      m3_state: m3Artifact.state,
    };
  }

  private async request(path: string, init?: RequestInit) {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          Accept: 'application/json',
          ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        },
      });
    } catch {
      throw new M4ApiError('无法连接本地 FastAPI。');
    }
    const body: unknown = await response.json();
    if (!response.ok) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === 'string') throw new M4ApiError(detail, response.status);
      if (detail && typeof detail === 'object') {
        const value = detail as { message?: string; status_url?: string };
        // A stopped run reports its safe message on the run resource. Showing
        // the generic HTTP failure instead would tell the user the request
        // broke, when what actually happened is that generation stopped
        // deliberately and named a reason.
        if (value.status_url) {
          const status = await fetch(`${this.baseUrl}${value.status_url}`, {
            headers: { Accept: 'application/json' },
          });
          if (status.ok) {
            const outcome = (await status.json()) as { failure?: { safe_user_message?: string } };
            throw new M4ApiError(
              outcome.failure?.safe_user_message ?? value.message ?? `HTTP ${response.status}`,
              response.status,
              value.status_url,
            );
          }
        }
        throw new M4ApiError(value.message ?? `HTTP ${response.status}`, response.status, value.status_url ?? '');
      }
      throw new M4ApiError(`HTTP ${response.status}`, response.status);
    }
    return validateM4Workspace(body);
  }

  get(assetId: string) {
    return this.request(`/api/v1/m4/assets/${assetId}`);
  }

  create(assetId: string, m3ArtifactId: string, canonicalVersionId: string) {
    return this.request(`/api/v1/m4/assets/${assetId}`, {
      method: 'POST',
      body: JSON.stringify({
        asset_id: assetId,
        expected_m3_artifact_id: m3ArtifactId,
        expected_canonical_version_id: canonicalVersionId,
      }),
    });
  }

  regenerate(
    assetId: string,
    m3ArtifactId: string,
    canonicalVersionId: string,
    invalidatedArtifactId: string,
  ) {
    return this.request(`/api/v1/m4/assets/${assetId}/regenerate`, {
      method: 'POST',
      body: JSON.stringify({
        asset_id: assetId,
        expected_m3_artifact_id: m3ArtifactId,
        expected_canonical_version_id: canonicalVersionId,
        expected_invalidated_artifact_id: invalidatedArtifactId,
      }),
    });
  }

  edit(assetId: string, artifactId: string, edits: M4StatementEdit[]) {
    return this.request(`/api/v1/m4/assets/${assetId}`, {
      method: 'PATCH',
      body: JSON.stringify({ asset_id: assetId, expected_artifact_id: artifactId, edits }),
    });
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function errorMessage(value: unknown, status: number): string {
  const detail = record(value)?.detail;
  return typeof detail === 'string' ? detail : `HTTP ${status}`;
}
