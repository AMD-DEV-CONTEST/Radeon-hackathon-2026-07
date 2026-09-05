export type DeliveryLanguage = 'zh-CN' | 'en';
export type DraftState = 'CURRENT' | 'SUPERSEDED';
export type ApprovalStatus = 'NOT_REQUIRED' | 'MISSING' | 'INVALID' | 'VALID';

export interface DeliverySectionV1 {
  heading: string;
  claims: Array<{
    text: string;
    statement_ids: string[];
  }>;
}

export interface DeliveryPreviewV1 {
  route_draft_id: string;
  asset_id: string;
  version_id: string;
  asset_version_hash: string;
  lineage_parent_version_id: string | null;
  relation_projection_hash: string;
  route: 'PRIVATE_SELF' | 'BEGINNER' | 'PEER' | 'CUSTOMER_EVALUATOR' | 'PUBLIC';
  language: DeliveryLanguage;
  route_draft_hash: string;
  renderer_input_identity: string;
  privacy_state_hash: string;
  state: DraftState;
  approval_status: ApprovalStatus;
  title: string;
  summary: string;
  sections: DeliverySectionV1[];
}
