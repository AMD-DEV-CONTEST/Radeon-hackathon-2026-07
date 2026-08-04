export type ApiState = "checking" | "ready" | "offline";

export type DemoRole = "requester" | "policy_reviewer";

export type FileKind = "xlsx" | "docx" | "pdf";

export type RecipientProfile =
  | "internal_procurement_lead"
  | "external_financial_auditor"
  | "supplier_bidder_a"
  | "external_incident_responder"
  | "candidate_supplier"
  | "affected_customer"
  | "regulator"
  | "public_audience";

export type Purpose =
  | "procurement_decision"
  | "annual_financial_audit"
  | "security_control_audit"
  | "supplier_bid_feedback"
  | "incident_response_investigation"
  | "customer_incident_notification"
  | "regulatory_incident_report"
  | "contract_terms_preview"
  | "legal_review";

export type Channel =
  | "corporate_email"
  | "secure_file_exchange"
  | "collaboration_platform"
  | "personal_email"
  | "public_release";

export type Classification =
  | "public"
  | "internal"
  | "confidential"
  | "strictly_confidential";

export type RevisionStatus =
  | "draft"
  | "analyzing"
  | "awaiting_confirmation"
  | "exportable"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "blocked"
  | "processing_failed";

export type Action =
  | "keep"
  | "mask"
  | "remove"
  | "filter"
  | "generalize"
  | "require_approval"
  | "block";

export type ContentCategory = string;

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  environment: string;
  inference: "local";
}

export interface DisclosureContext {
  recipient: RecipientProfile;
  organization: string;
  recipient_id: string;
  purpose: Purpose;
  channel: Channel;
  classification: Classification;
  policy_version: string;
}

export interface ContextResponse extends DisclosureContext {
  sha256: string;
}

export interface Decision {
  region_id: string;
  location: string;
  category: ContentCategory;
  action: Action;
  rule_ids: string[];
  evidence_ids: string[];
  reason_code: string;
  reason: string;
  policy_version: string;
  transform: string | null;
}

export interface Revision {
  id: string;
  task_id: string;
  revision_number: number;
  status: RevisionStatus;
  context: ContextResponse;
  source_sha256: string;
  policy_sha256: string;
  output_sha256: string | null;
  decision_manifest_sha256: string | null;
  created_at: string;
  action_counts: Partial<Record<Action, number>>;
  decisions: Decision[];
}

export interface DisclosureTask {
  id: string;
  requester_id: string;
  file_kind: FileKind;
  source_sha256: string;
  created_at: string;
  revisions: Revision[];
}

export interface StageEvent {
  revision_id: string;
  sequence: number;
  stage: string;
  status: string;
  occurred_at: string;
}

export interface Simulation {
  id: string;
  task_id: string;
  base_revision_id: string;
  context: ContextResponse;
  status: RevisionStatus;
  action_counts: Partial<Record<Action, number>>;
  decisions: Decision[];
  downloadable: false;
}

export interface ReviewRegion {
  region_id: string;
  location: string;
  order: number;
  category: ContentCategory;
  source_text: string;
  output_preview: string | null;
  action: Action;
  rule_ids: string[];
  rule_reasons: string[];
  evidence_ids: string[];
  reason_code: string;
  transform: string | null;
}

export interface EvidenceRecord {
  id: string;
  title: string;
  tags: string[];
  excerpt: string;
}

export interface ReviewData {
  revision_id: string;
  task_id: string;
  file_kind: FileKind;
  regions: ReviewRegion[];
  evidence: EvidenceRecord[];
  preview_urls: string[];
}

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "consumed";

export interface Approval {
  id: string;
  revision_id: string;
  status: ApprovalStatus;
  binding_sha256: string;
  requester_id: string;
  reviewer_id: string | null;
  expires_at: string;
  consumed: boolean;
  reason_code: string | null;
}

export type ReviewIntent = "explain" | "simulate" | "draft_exception";

export interface CopilotThread {
  thread_id: string;
  task_id: string;
  revision_id: string;
  display_reference: string;
  turn_count: number;
}

export interface CopilotCitation {
  location: string;
  category: ContentCategory;
  action: Action;
  rule_ids: string[];
  evidence_ids: string[];
}

export interface CopilotReply {
  thread_id: string;
  task_id: string;
  revision_id: string;
  turn_number: number;
  intent: ReviewIntent;
  text: string;
  citations: CopilotCitation[];
  simulation_id: string | null;
  exception_draft_id: string | null;
  model_dependent: boolean;
}

export interface ExceptionDraft {
  id: string;
  task_id: string;
  revision_id: string;
  location: string;
  category: ContentCategory;
  rule_ids: string[];
  evidence_ids: string[];
  status: string;
  submitted: boolean;
}

export interface ExceptionSubmission {
  draft: ExceptionDraft;
  approval: Approval;
}

export interface ApiErrorBody {
  detail?: {
    code?: string;
    message?: string;
  };
}

export interface ScenarioPreset {
  id: string;
  label: string;
  description: string;
  accepts: FileKind[];
  requesterId: string;
  context: DisclosureContext;
}
