import type { M4ViewState } from './m4View';

export type ReadinessMilestoneState = 'CONFIRMED' | 'COMPLETE_WITH_GAPS';

export interface KnowledgeCardReadinessV1 {
  schema_version: '1.0.0';
  readiness_id: string;
  asset_id: string;
  version_id: string;
  m4_artifact_id: string;
  knowledge_card_hash: string;
  milestone_state: ReadinessMilestoneState;
  explicit_user_acceptance: true;
  accepted_gap_statement_ids: string[];
  accepted_at: string;
  lifecycle: 'ACTIVE' | 'STALE' | 'INVALIDATED';
}

/** Frozen `DiscoveryOutcome` members the lock can report. */
export type DiscoveryOutcome =
  | 'NOT_READY'
  | 'RUNNING'
  | 'CANDIDATE'
  | 'NO_MATCH'
  | 'TECHNICAL_FAILURE'
  | 'STALE';

export interface DiscoveryLock {
  locked: boolean;
  /**
   * The backend's own outcome value, never a locally computed one. A lock
   * derived in the browser would disagree with the server the moment the card
   * changes in another tab, and the user would be shown an action that fails
   * when clicked.
   */
  outcome: DiscoveryOutcome | null;
  reason: string;
}

export type ReadinessRefusalReason =
  | 'NOT_READY'
  | 'STALE_VERSION'
  | 'CARD_HASH_MISMATCH'
  | 'ALREADY_ACCEPTED'
  | 'STORAGE_CONFLICT';

export class ReadinessApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    readonly reason: ReadinessRefusalReason | null = null,
  ) {
    super(message);
  }
}

export interface AcceptRequest {
  asset_id: string;
  expected_artifact_id: string;
  expected_canonical_version_id: string;
  user_action: 'CONFIRM' | 'ACCEPT_WITH_GAPS';
  accepted_gap_statement_ids?: string[];
}

export interface ReadinessApi {
  read(assetId: string): Promise<KnowledgeCardReadinessV1 | null>;
  readDiscoveryLock(assetId: string): Promise<DiscoveryLock>;
  accept(assetId: string, request: AcceptRequest): Promise<KnowledgeCardReadinessV1>;
}

export class LiveReadinessApi implements ReadinessApi {
  constructor(private readonly baseUrl = '') {}

  async read(assetId: string): Promise<KnowledgeCardReadinessV1 | null> {
    const response = await this.request(`/api/v1/m4/assets/${assetId}/readiness`);
    // 404 is the not-ready state, not an error: the card simply has no active
    // record yet, and treating it as a failure would surface a scary message
    // for the ordinary case of unfinished work.
    if (response.status === 404) return null;
    return (await this.body(response)) as KnowledgeCardReadinessV1;
  }

  async readDiscoveryLock(assetId: string): Promise<DiscoveryLock> {
    const response = await this.request(
      `/api/v1/relations/assets/${assetId}/discovery`,
    );
    if (response.ok) {
      const workspace = (await response.json()) as {
        discovery_outcome?: DiscoveryOutcome;
        readiness?: unknown;
      };
      const outcome = workspace.discovery_outcome ?? null;
      return {
        locked: outcome === 'NOT_READY',
        outcome,
        reason:
          outcome === 'NOT_READY'
            ? '先接受洞察与边界图，才能与其他经历比较。'
            : '',
      };
    }
    // 501 means the card is past the gate and the search itself is not built
    // yet. Reporting that as locked would be wrong — nothing is withholding it.
    if (response.status === 501) {
      return {locked: false, outcome: null, reason: ''};
    }
    const detail = await this.detail(response);
    return {
      locked: true,
      outcome: (detail.reason as DiscoveryOutcome) ?? null,
      reason: detail.message ?? `HTTP ${response.status}`,
    };
  }

  async accept(
    assetId: string,
    request: AcceptRequest,
  ): Promise<KnowledgeCardReadinessV1> {
    const response = await this.request(`/api/v1/m4/assets/${assetId}/accept`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      const detail = await this.detail(response);
      throw new ReadinessApiError(
        detail.message ?? `HTTP ${response.status}`,
        response.status,
        (detail.reason as ReadinessRefusalReason) ?? null,
      );
    }
    return (await response.json()) as KnowledgeCardReadinessV1;
  }

  private async request(path: string, init?: RequestInit): Promise<Response> {
    try {
      return await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          Accept: 'application/json',
          ...(init?.body ? {'Content-Type': 'application/json'} : {}),
        },
      });
    } catch {
      throw new ReadinessApiError('无法连接本地 FastAPI。');
    }
  }

  private async body(response: Response): Promise<unknown> {
    if (!response.ok) {
      const detail = await this.detail(response);
      throw new ReadinessApiError(
        detail.message ?? `HTTP ${response.status}`,
        response.status,
        (detail.reason as ReadinessRefusalReason) ?? null,
      );
    }
    return response.json();
  }

  private async detail(
    response: Response,
  ): Promise<{reason?: string; message?: string}> {
    try {
      const body = (await response.json()) as {detail?: unknown};
      const detail = body.detail;
      if (typeof detail === 'string') return {message: detail};
      if (detail && typeof detail === 'object') {
        return detail as {reason?: string; message?: string};
      }
    } catch {
      /* fall through to the status-only message */
    }
    return {};
  }
}

/** States in which acceptance is a meaningful action to offer at all. */
export const ACCEPTABLE_STATES: M4ViewState[] = [
  'NEEDS_INPUT',
  'REVIEW_READY',
];
