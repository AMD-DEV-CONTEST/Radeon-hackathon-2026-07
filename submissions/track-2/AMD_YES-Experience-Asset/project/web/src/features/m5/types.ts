import type { RouteDecision, RouteType, TerminalState } from '../../contracts/types';

/** Feature-local view models; live API types remain owned by shared contracts. */
export type M5PrivacyAction = 'KEEP' | 'ACKNOWLEDGE' | 'GENERALIZE' | 'REMOVE';
export type M5PrivacyResolution =
  | 'OPEN'
  | 'KEEP'
  | 'ACKNOWLEDGED'
  | 'GENERALIZE'
  | 'REMOVE';

export interface M5PrivacyFindingView {
  finding_id: string;
  category: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  explanation: string;
  affected_reference_ids: string[];
  allowed_actions: M5PrivacyAction[];
  resolution: M5PrivacyResolution;
}

export interface M5ApprovalView {
  state: 'NOT_READY' | 'READY' | 'STALE' | 'APPROVED';
  route: RouteType;
  language: 'zh-CN' | 'en';
  version_id: string;
  route_draft_id?: string;
  privacy_review_hash?: string;
  stale_reason?: string;
}

export interface M5WorkspaceView {
  asset_id: string;
  version_id: string;
  content_hash: string;
  autosave_state: 'saved' | 'saving' | 'save_failed';
  run_id: string;
  terminal_state?: TerminalState;
  decisions: RouteDecision[];
  findings: M5PrivacyFindingView[];
  privacy_review_state: 'COMPLETE' | 'FAILED';
  privacy_failure_code?: string;
  approval: M5ApprovalView;
}

export interface M5ApprovalAction {
  route_draft_id: string;
  user_action: 'APPROVE_SHAREABLE_EXPORT';
  idempotency_key: string;
}
