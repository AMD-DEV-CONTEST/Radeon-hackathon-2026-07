import type {RelationWorkspaceV1} from './types';

export class DiscoveryApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    readonly reason: string | null = null,
  ) {
    super(message);
  }
}

export interface DiscoveryRequest {
  asset_id: string;
  current_version_id: string;
  knowledge_card_version_id: string;
  knowledge_card_hash: string;
  scope: 'CROSS_ASSET_SUMMARY';
}

export interface DecisionRequest {
  decision_id: string;
  candidate_id: string;
  current_asset_id: string;
  current_version_id: string;
  current_knowledge_card_hash: string;
  related_asset_id: string;
  user_action: 'CONFIRM' | 'DECLINE';
  decided_at: string;
}

export interface DiscoveryApi {
  read(assetId: string): Promise<RelationWorkspaceV1>;
  start(assetId: string, request: DiscoveryRequest): Promise<RelationWorkspaceV1>;
  decide(
    assetId: string,
    candidateId: string,
    request: DecisionRequest,
  ): Promise<RelationWorkspaceV1>;
}

export class LiveDiscoveryApi implements DiscoveryApi {
  constructor(private readonly baseUrl = '') {}

  read(assetId: string) {
    return this.request(`/api/v1/relations/assets/${assetId}/discovery`);
  }

  start(assetId: string, request: DiscoveryRequest) {
    return this.request(`/api/v1/relations/assets/${assetId}/discovery`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  decide(assetId: string, candidateId: string, request: DecisionRequest) {
    return this.request(
      `/api/v1/relations/assets/${assetId}/candidates/${candidateId}/decision`,
      {method: 'POST', body: JSON.stringify(request)},
    );
  }

  private async request(path: string, init?: RequestInit): Promise<RelationWorkspaceV1> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          Accept: 'application/json',
          ...(init?.body ? {'Content-Type': 'application/json'} : {}),
        },
      });
    } catch {
      throw new DiscoveryApiError('无法连接本地 FastAPI。');
    }
    const body: unknown = await response.json();
    if (!response.ok) {
      const detail = (body as {detail?: unknown}).detail;
      if (detail && typeof detail === 'object') {
        const value = detail as {reason?: string; message?: string};
        // The reason is a frozen DiscoveryOutcome member, so a caller can tell
        // "not ready" from "your card moved" without parsing prose.
        throw new DiscoveryApiError(
          value.message ?? `HTTP ${response.status}`,
          response.status,
          value.reason ?? null,
        );
      }
      throw new DiscoveryApiError(
        typeof detail === 'string' ? detail : `HTTP ${response.status}`,
        response.status,
      );
    }
    return body as RelationWorkspaceV1;
  }
}
