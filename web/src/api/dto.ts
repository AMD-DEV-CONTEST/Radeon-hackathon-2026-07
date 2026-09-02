// TypeScript DTOs for the Unified Web Workbench API.
//
// CONTRACT RULE (UI-0 / spec): frontend DTO field names MUST NOT diverge from
// the backend Pydantic `app.schemas.models` fields. The backend returns
// snake_case JSON (no camelCase transform is configured), so every DTO field
// is written in snake_case to mirror the Schema 1:1. There is intentionally
// NO client-side key renaming layer.
//
// Each `export interface` carries a `// maps: <PydanticModel>` annotation.
// `scripts/validate_ui_contract.py` parses these annotations and asserts that
// every DTO field name exists on the corresponding backend model — this is
// the automated guard against hand-written, inconsistent field names.

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

// maps: LoginRequest
export interface LoginRequest {
  username: string
  password: string
}

// maps: TokenResponse
export interface TokenResponse {
  access_token: string
  token_type: string
  user_id: string
  username: string
  display_name: string
  is_system_admin: boolean
}

// maps: UserProfile
export interface UserProfile {
  user_id: string
  username: string
  display_name: string
  is_active: boolean
  is_system_admin: boolean
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

// maps: ProjectCreate
export interface ProjectCreate {
  project_id: string
  name: string
  description: string | null
}

// maps: Project
export interface Project {
  project_id: string
  name: string
  description: string | null
  created_at: string
  status: ProjectStatus
  source_file_count: number
  failed_file_count: number
}

export type ProjectStatus = 'created' | 'importing' | 'ready' | 'failed'

// Structural: backend returns `task_stats` as a plain dict (no named model).
export interface TaskStats {
  total: number
  [status: string]: number
}

// Structural: backend returns `risk_stats` as a plain dict (no named model).
export interface RiskStats {
  total_active?: number
  [severity: string]: number | undefined
}

// Structural: backend returns `recent_doc_changes` as list[dict] (no named model).
export interface DocChangeSummary {
  path: string
  sha256: string
  is_current: boolean
  last_seen: string
}

// Structural: backend returns `recent_runs` as list[dict] (no named model).
export interface RunSummary {
  run_id: string
  status: RunStatus
  created_at: string
  completed_at: string | null
}

// maps: ProjectOverview
export interface ProjectOverview {
  project_id: string
  project_name: string
  task_stats: TaskStats
  risk_stats: RiskStats
  pending_confirmations: number
  recent_doc_changes: DocChangeSummary[]
  recent_runs: RunSummary[]
}

// maps: UploadResult
export interface UploadResult {
  relative_path: string
  size_bytes: number
  sha256: string | null
  mime_detected: string | null
  extension_matched: boolean
  virus_scan_status: string
}

// maps: ProjectFileEntry
export interface ProjectFileEntry {
  relative_path: string
  filename: string
  size_bytes: number
  updated_at: string
  sha256: string | null
  parse_version: number | null
  index_version: number | null
  processing_status: 'uploaded' | 'indexed'
  is_task_file: boolean
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export type RunStatus =
  | 'queued'
  | 'scanning'
  | 'indexing'
  | 'retrieving'
  | 'evaluating'
  | 'drafting'
  | 'waiting_confirmation'
  | 'completed'
  | 'failed'
  | 'cancelled'

// maps: StepTiming
export interface StepTiming {
  step: string
  started_at: string | null
  finished_at: string | null
  elapsed_ms: number | null
  current_file: string | null
  error: string | null
}

// maps: RunState
export interface RunState {
  run_id: string
  project_id: string
  status: RunStatus
  current_step: number
  created_at: string
  updated_at: string
  completed_at: string | null
  error: string | null
  artifacts: Record<string, string>
  timing_by_step: StepTiming[]
  retry_count: number
  cancel_requested: boolean
  current_file: string | null
  total_steps: number
}

// maps: RunProgress
export interface RunProgress {
  run_id: string
  status: RunStatus
  current_step: number
  current_step_name: string | null
  percentage: number
  current_file: string | null
  error_summary: string | null
  timing_by_step: StepTiming[]
  retry_count: number
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

// Mirrors backend enum `PhaseFTaskStatus` (app/schemas/models.py).
export type PhaseFTaskStatus =
  | 'pending_confirmation'
  | 'not_started'
  | 'in_progress'
  | 'mostly_completed'
  | 'completed'
  | 'delayed'
  | 'cancelled'

// Mirrors backend `ALLOWED_TRANSITIONS` (app/schemas/task_sql.py). The UI only
// OFFERS these targets; the server remains the single authority and still
// rejects invalid transitions with TASK_INVALID_TRANSITION / TASK_CANCELLED_FINAL.
export const TASK_ALLOWED_TRANSITIONS: Record<PhaseFTaskStatus, PhaseFTaskStatus[]> = {
  pending_confirmation: ['not_started', 'cancelled'],
  not_started: ['in_progress', 'cancelled', 'delayed'],
  in_progress: ['mostly_completed', 'completed', 'delayed', 'cancelled'],
  mostly_completed: ['completed', 'in_progress', 'delayed'],
  completed: [],
  delayed: ['in_progress', 'completed', 'cancelled'],
  cancelled: [],
}

// maps: TaskRecord
export interface TaskRecord {
  id: string
  project_id: string
  title: string
  owner: string | null
  due_date: string | null
  priority: string
  acceptance_criteria: string
  dependencies: string[]
  source_ref: string | null
  status: string
  confirmed_by: string | null
  confirmed_at: string | null
  confirmation_basis: string | null
  confirmation_notes: string | null
  created_at: string
  updated_at: string
}

// maps: TaskCreate
export interface TaskCreate {
  title: string
  owner: string | null
  due_date: string | null
  priority: string
  acceptance_criteria: string
  dependencies: string[]
  source_ref: string | null
  status: string
}

// maps: TaskUpdate
export interface TaskUpdate {
  title?: string | null
  owner?: string | null
  due_date?: string | null
  priority?: string | null
  acceptance_criteria?: string | null
  dependencies?: string[] | null
  source_ref?: string | null
}

// maps: TaskStatusTransition
export interface TaskStatusTransition {
  status: PhaseFTaskStatus
  reason: string
}

// maps: TaskChangeRecord
export interface TaskChangeRecord {
  id: number
  task_id: string
  project_id: string
  from_status: string | null
  to_status: string
  changed_by: string | null
  change_reason: string | null
  changed_at: string
}

// maps: CandidateTask
export interface CandidateTask {
  title: string
  owner: string | null
  due_date: string | null
  priority: string | null
  acceptance_criteria: string | null
  dependencies: string[]
  source_ref: string | null
  source_kind: string
  confidence: number
}

// maps: ConfirmationRecord
export interface ConfirmationRecord {
  id: number
  task_id: string
  project_id: string
  candidate_title: string
  candidate_owner: string | null
  candidate_due_date: string | null
  candidate_priority: string | null
  candidate_acceptance: string | null
  candidate_dependencies: string[]
  source_ref: string | null
  source_kind: string
  confidence: number
  status: 'pending' | 'accepted' | 'ignored'
  confirmed_by: string | null
  confirmation_basis: string | null
  confirmation_notes: string | null
  confirmed_at: string | null
  created_at: string
}

// maps: ConfirmationAction
export interface ConfirmationAction {
  action: 'accept' | 'modify' | 'ignore'
  confirmation_basis?: string | null
  confirmation_notes?: string | null
  modified_title?: string | null
  modified_owner?: string | null
  modified_due_date?: string | null
  modified_priority?: string | null
  modified_acceptance?: string | null
  modified_dependencies?: string[] | null
}

// maps: TaskImportDiff
export interface TaskImportDiff {
  new_rows: number
  duplicate_rows: number
  conflict_rows: number
  preview: Record<string, string>[]
}

// maps: TaskImportResult
export interface TaskImportResult {
  imported: number
  skipped: number
  errors: number
  details: string[]
}

// maps: OperationAuditRecord
export interface OperationAuditRecord {
  id: number
  project_id: string
  entity_type: string
  entity_id: string
  operation: string
  operator: string | null
  details: string | null
  created_at: string
}

// maps: TaskExtractionRequest
export interface TaskExtractionRequest {
  source_text: string
  source_kind: string
  project_id: string
}

// maps: TaskExtractionResult
export interface TaskExtractionResult {
  candidates: CandidateTask[]
}

// ---------------------------------------------------------------------------
// Risk
// ---------------------------------------------------------------------------

export type RiskLifecycle = 'active' | 'acknowledged' | 'resolved' | 'dismissed' | 'expired'

// maps: RiskCenterEntry
export interface RiskCenterEntry {
  record_id: string
  project_id: string
  title: string
  severity: string
  lifecycle: RiskLifecycle
  description: string | null
  assigned_to: string | null
  assignee_name: string | null
  comment_count: number
  created_at: string
  updated_at: string
}

// maps: RiskAssignmentRequest
export interface RiskAssignmentRequest {
  risk_id: string
  assignee_user_id: string
}

// maps: RiskLifecycleUpdate
export interface RiskLifecycleUpdate {
  action: 'acknowledge' | 'resolve' | 'dismiss' | 'reopen'
  note: string
  actor?: string
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

export type ReportDraftStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'archived'

// maps: ReportDraftEntry
export interface ReportDraftEntry {
  id: string
  project_id: string
  title: string
  content_md: string
  version: number
  status: ReportDraftStatus
  author_id: string
  author_name: string
  created_at: string
  updated_at: string
}

// maps: ReportDraftCreate
export interface ReportDraftCreate {
  title: string
  content_md: string
}

// maps: ReportDraftUpdate
export interface ReportDraftUpdate {
  title?: string
  content_md?: string
}

// maps: ReportApprovalRequest
export interface ReportApprovalRequest {
  decision: 'approved' | 'rejected' | 'request_changes'
  comment: string
}

export interface ReportApprovalEntry {
  id: string
  report_id: string
  approver_id: string
  approver_name: string
  decision: string
  comment: string
  created_at: string
}

// maps: ProjectMemberEntry
export interface ProjectMemberEntry {
  id: string
  project_id: string
  user_id: string
  username: string
  display_name: string
  role: 'admin' | 'pm' | 'member' | 'guest'
  joined_at: string
}

// maps: ProjectMemberAdd
export interface ProjectMemberAdd {
  user_id: string
  role: 'admin' | 'pm' | 'member' | 'guest'
}

// maps: CommentCreate
export interface CommentCreate {
  entity_type: 'task' | 'risk' | 'report_section' | 'report'
  entity_id: string
  body: string
  parent_id?: string | null
  mentions?: string[]
}

// maps: CommentEntry
export interface CommentEntry {
  id: string
  project_id: string
  entity_type: string
  entity_id: string
  author_id: string
  author_name: string
  parent_id: string | null
  body: string
  is_resolved: boolean
  mentions: string[]
  replies: CommentEntry[]
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

// maps: NotificationEntry
export interface NotificationEntry {
  id: string
  kind: string
  title: string
  body: string
  link: string | null
  is_read: boolean
  recipient_id: string
  created_at: string
}

// ---------------------------------------------------------------------------
// Controlled integrations and operations (UI-5)
// ---------------------------------------------------------------------------

export interface ScmChangeItem {
  title: string
  body?: string
  labels?: string[]
}

export interface ScmPreviewRequest {
  project_id: string
  target: 'github_issues' | 'jira'
  operation: 'create' | 'update'
  items: ScmChangeItem[]
}

export interface ScmPreviewResponse {
  ok: boolean
  preview: Omit<ScmPreviewRequest, 'project_id'>
  confirmation_id: string
}

export interface IntegrationExecutionResult {
  ok: boolean
  summary: string
  details: Record<string, unknown>
}

export interface QueueMetrics {
  active_llm_calls: number
  active_embedding_calls: number
  queued_calls: number
  total_completed: number
  total_cancelled: number
  total_timeouts: number
  total_errors: number
  global_llm_capacity: number
  global_embedding_capacity: number
}

export interface CacheMetrics {
  enabled: boolean
  size: number
  max_entries: number
  hits: number
  misses: number
  hit_rate: number
  evictions: number
  ttls: Record<string, number>
}

export interface AdminHealth {
  status: string
  issues: Array<{ code?: string; message?: string }>
  gpu_metrics: Array<{ device_id: number; name: string; vram_total_mb: number; vram_used_mb: number; utilization_pct: number; temperature_c: number }>
  system_metrics: { disk_used_pct: number; disk_free_gb: number }
  model_metadata: { model_name: string; quantization: string; context_size: number; backend: string }
  llm_error_rate: number
  queue_status: QueueMetrics
  cache_stats: CacheMetrics
  timestamp: number
}

export interface BackupEntry {
  backup_dir: string
  name: string
  timestamp: string
  label: string
  total_size_bytes: number
  file_count: number
  status: string
}

// ---------------------------------------------------------------------------
// Shared error body (mirrors backend `ErrorDetail`)
// ---------------------------------------------------------------------------

// maps: ErrorDetail
export interface ErrorDetail {
  error_code: string
  message: string
  user_message: string
  details: Record<string, unknown>
}
