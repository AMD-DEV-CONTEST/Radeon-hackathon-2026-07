import type { RouteDecision } from '../../contracts/types';
import type { RouteType } from '../../contracts/types';
import type {
  M5ApprovalAction,
  M5PrivacyAction,
  M5PrivacyFindingView,
  M5WorkspaceView,
} from './types';

export interface M5DraftContent {
  title: string;
  summary: { text: string; statement_ids: string[] };
  sections: Array<{
    heading: string;
    claims: Array<{ text: string; statement_ids: string[] }>;
  }>;
  notices: string[];
}

export interface StoredRouteDraftResponse {
  renderer_input_identity: string;
  draft: {
    route_draft_id: string;
    route: RouteType;
    language: 'zh-CN' | 'en';
    content_hash: string;
  };
  content: M5DraftContent;
}

export interface DeliveryPreviewResponse {
  identity: {
    route_draft_id: string;
    asset_id: string;
    version_id: string;
    asset_version_hash: string;
    lineage_parent_version_id: string | null;
    relation_projection_hash: string;
    route: RouteType;
    language: 'zh-CN' | 'en';
    renderer_input_identity: string;
    route_draft_hash: string;
    privacy_state_hash: string;
    draft_state: 'CURRENT' | 'SUPERSEDED';
  };
  operation: 'IN_APP_PREVIEW';
  html: string;
  markdown: string;
  json: string;
}

export interface ApprovalResponse {
  approval_id: string;
}

/** Wire shape of `/api/v1/m5/assets/{id}/workspace`. */
export interface M5WorkspaceResponse {
  asset_id: string;
  version_id: string;
  content_hash: string;
  stale_reason: string | null;
  matrix: {
    asset_id: string;
    version_id: string;
    content_hash: string;
    relation_projection_hash: string;
    policy_version: string;
    decisions: RouteDecision[];
  } | null;
  matrix_hash: string | null;
  privacy_review: {
    review_hash: string;
    status: 'COMPLETE' | 'FAILED';
    failure_code: string | null;
    proposal_sources: string[];
    detector_version: string | null;
    findings: {
      finding_id: string;
      category: string;
      severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
      explanation: string;
      affected_statement_ids: string[];
      affected_source_ids: string[];
      proposed_actions: string[];
      resolution: string;
    }[];
  } | null;
  evidence_statements: Record<string, string>;
}

export class M5ApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    readonly code = '',
  ) {
    super(message);
  }
}

async function readError(response: Response): Promise<M5ApiError> {
  let code = '';
  let message = `M5 请求失败（${response.status}）。`;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (detail && typeof detail === 'object') {
      code = String(detail.code ?? '');
      message = String(detail.message ?? message);
    } else if (typeof detail === 'string') {
      message = detail;
    }
  } catch {
    // A body that is not JSON tells us nothing extra; the status still does.
  }
  return new M5ApiError(message, response.status, code);
}

export interface M5Api {
  get(assetId: string): Promise<M5WorkspaceResponse>;
  evaluate(assetId: string): Promise<M5WorkspaceResponse>;
  resolveFinding(
    assetId: string,
    findingId: string,
    action: M5PrivacyAction,
  ): Promise<M5WorkspaceResponse>;
  approve(assetId: string, binding: M5ApprovalAction): Promise<ApprovalResponse>;
  createDraft(
    assetId: string,
    input: {
      create_request_id: string;
      route: string;
      language: 'zh-CN' | 'en';
      content: M5DraftContent;
    },
  ): Promise<StoredRouteDraftResponse>;
  previewDraft(draftId: string): Promise<DeliveryPreviewResponse>;
  exportDraft(draftId: string, approvalId?: string): Promise<unknown>;
}

export function createM5Api(baseUrl: string): M5Api {
  const root = baseUrl.replace(/\/$/, '');
  const send = async (path: string, init?: RequestInit): Promise<M5WorkspaceResponse> => {
    const response = await fetch(`${root}${path}`, {
      ...init,
      headers: init?.body ? { 'content-type': 'application/json' } : undefined,
    });
    if (!response.ok) throw await readError(response);
    return (await response.json()) as M5WorkspaceResponse;
  };

  return {
    get: (assetId) => send(`/api/v1/m5/assets/${assetId}/workspace`),
    evaluate: (assetId) => send(`/api/v1/m5/assets/${assetId}/evaluate`, { method: 'POST' }),
    resolveFinding: (assetId, findingId, action) =>
      send(`/api/v1/m5/assets/${assetId}/privacy/findings/${findingId}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      }),
    approve: async (assetId, binding) => {
      const response = await fetch(`${root}/api/v1/m5/assets/${assetId}/approvals`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(binding),
      });
      if (!response.ok) throw await readError(response);
      return response.json();
    },
    createDraft: async (assetId, input) => {
      const response = await fetch(`${root}/api/v1/delivery/assets/${assetId}/drafts`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(input),
      });
      if (!response.ok) throw await readError(response);
      return response.json();
    },
    previewDraft: async (draftId) => {
      const response = await fetch(`${root}/api/v1/delivery/drafts/${draftId}/preview`);
      if (!response.ok) throw await readError(response);
      return response.json();
    },
    exportDraft: async (draftId, approvalId) => {
      const response = await fetch(`${root}/api/v1/delivery/drafts/${draftId}/exports`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          operation: approvalId ? 'SHAREABLE_EXTERNAL_EXPORT' : 'PRIVATE_DOWNLOAD',
          ...(approvalId ? {approval_id: approvalId} : {}),
        }),
      });
      if (!response.ok) throw await readError(response);
      return response.json();
    },
  };
}

const ALLOWED_ACTIONS = new Set<M5PrivacyAction>(['KEEP', 'ACKNOWLEDGE', 'GENERALIZE', 'REMOVE']);

function toAction(value: string): M5PrivacyAction | null {
  return ALLOWED_ACTIONS.has(value as M5PrivacyAction) ? (value as M5PrivacyAction) : null;
}

/**
 * Map the API response onto the panel's view model.
 *
 * The panel never sees a route it can act on that policy did not mark
 * actionable: `allowed_actions` comes from the server's `proposed_actions`, so a
 * severe finding the user is not permitted to simply keep cannot grow a Keep
 * button on the client.
 */
export function toWorkspaceView(
  response: M5WorkspaceResponse,
  selectedRoute: M5WorkspaceView['approval']['route'] = 'PRIVATE_SELF',
  selectedLanguage: M5WorkspaceView['approval']['language'] = 'zh-CN',
): M5WorkspaceView {
  const review = response.privacy_review;
  const findings: M5PrivacyFindingView[] = (review?.findings ?? []).map((finding) => ({
    finding_id: finding.finding_id,
    category: finding.category,
    severity: finding.severity,
    explanation: finding.explanation,
    affected_reference_ids: [...finding.affected_statement_ids, ...finding.affected_source_ids],
    allowed_actions: finding.proposed_actions
      .map(toAction)
      .filter((action): action is M5PrivacyAction => action !== null),
    resolution: finding.resolution as M5PrivacyFindingView['resolution'],
  }));

  const openFindings = findings.some((finding) => finding.resolution === 'OPEN');
  const selectedDecision = response.matrix?.decisions.find(
    (decision) => decision.route === selectedRoute,
  );

  return {
    asset_id: response.asset_id,
    version_id: response.version_id,
    content_hash: response.content_hash,
    autosave_state: 'saved',
    run_id: response.matrix_hash ?? '',
    decisions: response.matrix?.decisions ?? [],
    findings,
    privacy_review_state: review?.status ?? 'FAILED',
    privacy_failure_code: review?.failure_code ?? response.stale_reason ?? undefined,
    approval: {
      // READY means "the gate would let an approval through", not "approved".
      state:
        selectedDecision?.eligibility === 'ELIGIBLE' && !openFindings ? 'READY' : 'NOT_READY',
      route: selectedRoute,
      language: selectedLanguage,
      version_id: response.version_id,
      privacy_review_hash: review?.review_hash,
      stale_reason: response.stale_reason ?? undefined,
    },
  };
}
