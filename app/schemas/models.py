from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.security.paths import validate_project_id


class ProjectStatus(StrEnum):
    CREATED = "created"
    IMPORTING = "importing"
    READY = "ready"
    FAILED = "failed"


class TaskStatus(StrEnum):
    COMPLETED = "completed"
    MOSTLY_COMPLETED = "mostly_completed"
    IN_PROGRESS = "in_progress"
    NOT_STARTED = "not_started"
    DELAYED = "delayed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    QUEUED = "queued"
    SCANNING = "scanning"
    INDEXING = "indexing"
    RETRIEVING = "retrieving"
    EVALUATING = "evaluating"
    DRAFTING = "drafting"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Stage E — Step timing & progress models
# ---------------------------------------------------------------------------


class StepDef(StrEnum):
    """Named phases tracked by the controlled runner."""
    PARSE = "parse"
    EMBED = "embed"
    INDEX = "index"
    RETRIEVE = "retrieve"
    RULES = "rules"
    MODEL_GENERATE = "model_generate"
    FILE_WRITE = "file_write"


class StepTiming(BaseModel):
    """Timing record for a single pipeline step."""
    step: StepDef
    started_at: datetime
    finished_at: datetime | None = None
    elapsed_ms: float | None = None
    current_file: str | None = Field(default=None, max_length=500)
    error: str | None = Field(default=None, max_length=4000)


class RunProgress(BaseModel):
    """Live progress snapshot returned via polling / SSE."""
    run_id: str
    status: RunStatus
    current_step: int = Field(default=0, ge=0, le=8)
    current_step_name: str = ""
    percentage: int = Field(default=0, ge=0, le=100)
    current_file: str | None = Field(default=None, max_length=500)
    error_summary: str | None = Field(default=None, max_length=4000)
    timing_by_step: list[StepTiming] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)


class ProjectCreate(BaseModel):
    project_id: str = Field(description="Stable lowercase project identifier")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("project_id")
    @classmethod
    def check_project_id(cls, value: str) -> str:
        return validate_project_id(value)


class Project(ProjectCreate):
    created_at: datetime
    status: ProjectStatus = ProjectStatus.CREATED
    source_file_count: int = Field(default=0, ge=0)
    failed_file_count: int = Field(default=0, ge=0)


class Task(BaseModel):
    task_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    owner: str | None = Field(default=None, max_length=120)
    due_date: date | None = None
    priority: str | None = Field(default=None, max_length=40)
    acceptance_criteria: str | None = Field(default=None, max_length=4000)
    source_reference: str | None = Field(default=None, max_length=1000)


class Evidence(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=160)
    relative_path: str = Field(min_length=1, max_length=1000)
    locator: str = Field(min_length=1, max_length=500, description="Page, heading, sheet, or cell range")
    excerpt: str = Field(min_length=1, max_length=8000)
    score: float = Field(ge=0, le=1)


class TaskEvaluation(BaseModel):
    task_id: str = Field(min_length=1, max_length=120)
    status: TaskStatus
    explanation: str = Field(min_length=1, max_length=4000)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    risk_level: str = Field(default="low", pattern="^(low|medium|high)$")
    risk_reason: str = Field(default="", max_length=4000)
    recommendation: str = Field(default="", max_length=4000)


class RunState(BaseModel):
    run_id: str = Field(min_length=1, max_length=120)
    project_id: str
    status: RunStatus = RunStatus.QUEUED
    current_step: int = Field(default=0, ge=0, le=8)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error: str | None = Field(default=None, max_length=4000)
    artifacts: dict[str, str] = Field(default_factory=dict)
    # Stage E fields
    timing_by_step: list[StepTiming] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)
    cancel_requested: bool = Field(default=False)
    current_file: str | None = Field(default=None, max_length=500)
    total_steps: int = Field(default=8, ge=1, le=20)

    @field_validator("project_id")
    @classmethod
    def check_project_id(cls, value: str) -> str:
        return validate_project_id(value)


class ReportDraft(BaseModel):
    project_id: str
    markdown: str = Field(min_length=1)
    evaluations: list[TaskEvaluation] = Field(default_factory=list)

    @field_validator("project_id")
    @classmethod
    def check_project_id(cls, value: str) -> str:
        return validate_project_id(value)


# ---------------------------------------------------------------------------
# Stage E — File upload & validation models
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS: set[str] = {
    ".md", ".txt", ".pdf", ".docx", ".xlsx", ".csv",
}

ALLOWED_MIME_TYPES: set[str] = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/csv",
    "application/vnd.ms-excel",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

EXTENSION_TO_MIME: dict[str, list[str]] = {
    ".md": ["text/markdown", "text/x-markdown", "text/plain"],
    ".txt": ["text/plain"],
    ".pdf": ["application/pdf"],
    ".docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    ".xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    ".csv": ["text/csv", "text/plain", "application/vnd.ms-excel"],
}

MAX_UPLOAD_SIZE_MB_DEFAULT: int = 50


class FileValidationError(BaseModel):
    """Structured file validation error."""
    filename: str
    error_code: str
    message: str
    user_message: str


class UploadResult(BaseModel):
    """Result of a file upload operation."""
    relative_path: str
    size_bytes: int
    sha256: str | None = None
    mime_detected: str | None = None
    extension_matched: bool = True
    virus_scan_status: str = "skipped"


class ProjectFileEntry(BaseModel):
    """Safe metadata for one file in a project's controlled source area."""

    relative_path: str
    filename: str
    size_bytes: int = Field(ge=0)
    updated_at: str
    sha256: str | None = None
    parse_version: int | None = Field(default=None, ge=1)
    index_version: int | None = Field(default=None, ge=1)
    processing_status: str = Field(pattern="^(uploaded|indexed)$")
    is_task_file: bool = False


# ---------------------------------------------------------------------------
# Stage E — Error codes
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    """Structured error returned by API endpoints."""
    error_code: str
    message: str
    user_message: str = ""
    details: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Phase F — Task lifecycle & human confirmation models
# ---------------------------------------------------------------------------

class PhaseFTaskStatus(StrEnum):
    """Task status values for the SQLite task lifecycle."""
    PENDING_CONFIRMATION = "pending_confirmation"
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    MOSTLY_COMPLETED = "mostly_completed"
    COMPLETED = "completed"
    DELAYED = "delayed"
    CANCELLED = "cancelled"


class TaskCreate(BaseModel):
    """Request model for creating a task via API."""
    title: str = Field(min_length=1, max_length=500)
    owner: str | None = Field(default=None, max_length=120)
    due_date: date | None = None
    priority: str | None = Field(default=None, max_length=40)
    acceptance_criteria: str | None = Field(default=None, max_length=4000)
    dependencies: list[str] = Field(default_factory=list, max_length=50)
    source_ref: str | None = Field(default=None, max_length=1000)
    status: PhaseFTaskStatus = PhaseFTaskStatus.PENDING_CONFIRMATION


class TaskUpdate(BaseModel):
    """Request model for updating a task via API."""
    title: str | None = Field(default=None, max_length=500)
    owner: str | None = Field(default=None, max_length=120)
    due_date: date | None = None
    priority: str | None = Field(default=None, max_length=40)
    acceptance_criteria: str | None = Field(default=None, max_length=4000)
    dependencies: list[str] | None = None
    source_ref: str | None = Field(default=None, max_length=1000)


class TaskStatusTransition(BaseModel):
    """Request model for changing a task's status."""
    status: PhaseFTaskStatus
    reason: str = Field(default="", max_length=2000)
    changed_by: str | None = Field(default=None, max_length=120)


class TaskRecord(BaseModel):
    """Full task record as stored in SQLite."""
    id: str
    project_id: str
    title: str
    owner: str | None = None
    due_date: str | None = None
    priority: str | None = None
    acceptance_criteria: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    source_ref: str | None = None
    status: PhaseFTaskStatus = PhaseFTaskStatus.PENDING_CONFIRMATION
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    confirmation_basis: str | None = None
    confirmation_notes: str | None = None
    created_at: str = ""
    updated_at: str = ""


class TaskChangeRecord(BaseModel):
    """Record of a single task status transition."""
    id: int
    task_id: str
    project_id: str
    from_status: str | None = None
    to_status: str
    changed_by: str | None = None
    change_reason: str | None = None
    changed_at: str = ""


class CandidateTask(BaseModel):
    """A task extracted from source material, pending human confirmation."""
    title: str = Field(min_length=1, max_length=500)
    owner: str | None = Field(default=None, max_length=120)
    due_date: date | None = None
    priority: str | None = Field(default=None, max_length=40)
    acceptance_criteria: str | None = Field(default=None, max_length=4000)
    dependencies: list[str] = Field(default_factory=list)
    source_ref: str | None = Field(default=None, max_length=1000)
    source_kind: str = Field(min_length=1, max_length=60)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ConfirmationRecord(BaseModel):
    """A record in the human confirmation queue."""
    id: int
    task_id: str
    project_id: str
    candidate_title: str
    candidate_owner: str | None = None
    candidate_due_date: str | None = None
    candidate_priority: str | None = None
    candidate_acceptance: str | None = None
    candidate_dependencies: list[str] = Field(default_factory=list)
    source_ref: str | None = None
    source_kind: str
    confidence: float = 0.5
    status: str = "pending"
    confirmed_by: str | None = None
    confirmation_basis: str | None = None
    confirmation_notes: str | None = None
    confirmed_at: str | None = None
    created_at: str = ""


class ConfirmationAction(BaseModel):
    """Request model for a confirmation action (accept / modify / ignore)."""
    action: str = Field(pattern="^(accept|modify|ignore)$")
    # API handlers overwrite this with the signed-in actor. It is optional
    # only for isolated legacy service callers.
    confirmed_by: str | None = Field(default=None, max_length=120)
    confirmation_basis: str | None = Field(default=None, max_length=1000)
    confirmation_notes: str | None = Field(default=None, max_length=4000)
    modified_title: str | None = Field(default=None, max_length=500)
    modified_owner: str | None = Field(default=None, max_length=120)
    modified_due_date: date | None = None
    modified_priority: str | None = Field(default=None, max_length=40)
    modified_acceptance: str | None = Field(default=None, max_length=4000)
    modified_dependencies: list[str] | None = None


class TaskImportDiff(BaseModel):
    """Diff preview for CSV / XLSX import before confirmation."""
    new_rows: int = Field(default=0, ge=0)
    duplicate_rows: int = Field(default=0, ge=0)
    conflict_rows: int = Field(default=0, ge=0)
    preview: list[dict[str, str]] = Field(default_factory=list)


class TaskImportConfirm(BaseModel):
    """Request model for confirming an import."""
    confirmed_by: str | None = Field(default=None, max_length=120)
    skip_duplicates: bool = True
    overwrite_conflicts: bool = False


class TaskImportResult(BaseModel):
    """Result after confirming and executing an import."""
    imported: int = 0
    skipped: int = 0
    errors: int = 0
    details: list[str] = Field(default_factory=list)


class OperationAuditRecord(BaseModel):
    """Operation audit record."""
    id: int
    project_id: str
    entity_type: str
    entity_id: str
    operation: str
    operator: str | None = None
    details: str | None = None
    created_at: str = ""


class TaskExtractionRequest(BaseModel):
    """Request model for extracting candidate tasks from text."""
    source_text: str = Field(min_length=0, max_length=100000)
    source_kind: str = Field(default="meeting_notes", max_length=60)
    project_id: str = Field(min_length=1, max_length=120)


class TaskExtractionResult(BaseModel):
    """Result of extracting candidate tasks from a text source."""
    candidates: list[CandidateTask] = Field(default_factory=list)


class ConfirmQueueFilter(BaseModel):
    """Filter for listing confirmation queue items."""
    status: str | None = Field(default=None, pattern="^(pending|accepted|ignored)$")


# ---------------------------------------------------------------------------
# Stage G — Risk & Knowledge Monitoring models
# ---------------------------------------------------------------------------

class RiskSeverityStr(StrEnum):
    """Severity of a risk record."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLifecycleStr(StrEnum):
    """Lifecycle state of a risk record."""
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class RiskRuleTypeStr(StrEnum):
    """Risk rule type categories."""
    NEAR_DEADLINE = "near_deadline"
    OVERDUE = "overdue"
    NO_EVIDENCE = "no_evidence"
    ACCEPTANCE_GAP = "acceptance_gap"
    DEPENDENCY_BLOCK = "dependency_block"
    MATERIAL_CONFLICT = "material_conflict"
    CUSTOM = "custom"


class RiskRuleConfig(BaseModel):
    """Risk rule configuration model."""
    rule_id: str = Field(min_length=1, max_length=120)
    rule_name: str = Field(default="", max_length=200)
    rule_type: str = Field(default="custom", max_length=60)
    description: str = Field(default="", max_length=2000)
    severity: RiskSeverityStr = RiskSeverityStr.MEDIUM
    config_json: str = Field(default="{}", max_length=8000)
    enabled: bool = True


class RiskRecordSummary(BaseModel):
    """Summary of a risk record (API-friendly)."""
    record_id: str = Field(min_length=1, max_length=120)
    project_id: str = ""
    risk_type: str = ""
    entity_type: str = "task"
    entity_id: str = ""
    severity: RiskSeverityStr = RiskSeverityStr.MEDIUM
    title: str = ""
    description: str = ""
    lifecycle: RiskLifecycleStr = RiskLifecycleStr.ACTIVE
    source_material: str = ""
    acknowledged_by: str | None = None
    resolved_by: str | None = None
    resolution_note: str = ""
    created_at: str = ""
    updated_at: str = ""


class RiskScanRequest(BaseModel):
    """Request to trigger a project risk scan."""
    project_id: str = Field(min_length=1, max_length=120)
    scan_type: str = Field(default="full", pattern="^(full|incremental|task_only|material_only)$")
    notify_external: bool = False


class RiskScanSummary(BaseModel):
    """Result of a risk scan."""
    scan_id: str
    project_id: str
    total_rules: int = 0
    new_risks: int = 0
    active_risks: int = 0
    total_risks: int = 0
    status: str = "completed"
    scan_type: str = "full"
    risk_summary: dict = Field(default_factory=dict)
    impact_summary: str = ""


class DocVersionSummary(BaseModel):
    """Document version record for API responses."""
    id: int | None = None
    project_id: str = ""
    relative_path: str = ""
    sha256: str = ""
    parse_version: int = 1
    index_version: int = 1
    replaced_by: str | None = None
    is_current: bool = True
    last_seen_at: str = ""


class ChangeImpactEntry(BaseModel):
    """A single change impact entry."""
    entity_type: str = "task"
    entity_id: str = ""
    entity_title: str = ""
    impact_type: str = "reference_changed"
    reason: str = ""
    severity: str = "medium"
    source_file: str = ""


class ChangeImpactReport(BaseModel):
    """Full change impact analysis report for API."""
    project_id: str
    changed_files: list[str] = Field(default_factory=list)
    total_affected: int = 0
    affected_tasks: list[ChangeImpactEntry] = Field(default_factory=list)
    affected_reports: list[ChangeImpactEntry] = Field(default_factory=list)
    generated_at: str = ""


class QualityTestCaseModel(BaseModel):
    """A single quality benchmark test case."""
    test_case_id: str = Field(min_length=1, max_length=120)
    category: str = "factual"
    question: str = ""
    expected_answer: str | None = None
    expected_relevant: list[str] = Field(default_factory=list)
    should_refuse: bool = False
    conflict_docs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class QualityBenchmarkRun(BaseModel):
    """Result of a quality benchmark evaluation run."""
    benchmark_name: str = "default"
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    avg_recall: float = 0.0
    avg_citation_accuracy: float = 0.0
    avg_refusal_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_failure_rate: float = 0.0
    run_at: str = ""
    per_category: dict[str, dict[str, float]] = Field(default_factory=dict)


class QualityMetricEntry(BaseModel):
    """A single quality metric record."""
    benchmark_name: str = "default"
    test_case_id: str = ""
    category: str = "factual"
    recall_rate: float = 0.0
    citation_accuracy: float = 0.0
    refusal_rate: float = 0.0
    latency_ms: float = 0.0
    failure_rate: float = 0.0
    run_at: str = ""


# ===========================================================================
# Phase H — Team Collaboration Workspace models
# ===========================================================================

class ProjectRole(StrEnum):
    ADMIN = "admin"
    PM = "pm"
    MEMBER = "member"
    GUEST = "guest"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    display_name: str
    is_system_admin: bool = False


class UserProfile(BaseModel):
    user_id: str
    username: str
    display_name: str
    is_active: bool = True
    is_system_admin: bool = False


class ProjectMemberEntry(BaseModel):
    id: str = ""
    project_id: str
    user_id: str
    username: str = ""
    display_name: str = ""
    role: ProjectRole
    joined_at: str = ""


class ProjectMemberAdd(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    role: ProjectRole = ProjectRole.MEMBER


class ProjectOverview(BaseModel):
    project_id: str
    project_name: str = ""
    task_stats: dict = Field(default_factory=dict)
    risk_stats: dict = Field(default_factory=dict)
    pending_confirmations: int = 0
    recent_doc_changes: list[dict] = Field(default_factory=list)
    recent_runs: list[dict] = Field(default_factory=list)


class TaskBoardQuery(BaseModel):
    status: str | None = None
    owner: str | None = None
    priority: str | None = None
    due_before: str | None = None
    due_after: str | None = None
    sort_by: str = "due_date"
    sort_order: str = "asc"
    group_by: str | None = None  # owner, status, priority
    search: str | None = Field(default=None, max_length=200)


class TaskBoardCard(BaseModel):
    task_id: str
    title: str
    owner: str | None = None
    due_date: str | None = None
    priority: str | None = None
    status: str
    comment_count: int = 0
    risk_level: str = "low"


class TaskBoardResponse(BaseModel):
    project_id: str
    groups: dict[str, list[TaskBoardCard]] = Field(default_factory=dict)  # grouped view
    total_count: int = 0
    filters_applied: dict = Field(default_factory=dict)


class RiskAssignmentRequest(BaseModel):
    risk_id: str = Field(min_length=1, max_length=120)
    assignee_user_id: str = Field(min_length=1, max_length=120)


class RiskLifecycleUpdate(BaseModel):
    action: str = Field(pattern="^(acknowledge|resolve|dismiss|reopen)$")
    note: str = Field(default="", max_length=2000)
    actor: str = Field(default="", max_length=120)


class RiskCenterEntry(BaseModel):
    record_id: str
    project_id: str = ""
    title: str = ""
    severity: str = "medium"
    lifecycle: str = "active"
    description: str = ""
    assigned_to: str | None = None
    assignee_name: str | None = None
    comment_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class ReportDraftEntry(BaseModel):
    id: str = ""
    project_id: str
    title: str
    content_md: str = ""
    version: int = 1
    status: str = "draft"
    author_id: str = ""
    author_name: str = ""
    created_at: str = ""
    updated_at: str = ""


class ReportDraftCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(default="", max_length=100_000)


class ReportDraftUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    content_md: str | None = Field(default=None, max_length=100_000)


class ReportApprovalRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|request_changes)$")
    comment: str = Field(default="", max_length=2000)


class ReportExportFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


class CommentCreate(BaseModel):
    entity_type: str = Field(pattern="^(task|risk|report_section|report)$")
    entity_id: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=8000)
    parent_id: str | None = Field(default=None, max_length=120)
    mentions: list[str] = Field(default_factory=list, max_length=50)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class CommentEntry(BaseModel):
    id: str = ""
    project_id: str
    entity_type: str
    entity_id: str
    author_id: str = ""
    author_name: str = ""
    parent_id: str | None = None
    body: str
    is_resolved: bool = False
    mentions: list[str] = Field(default_factory=list)
    replies: list["CommentEntry"] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class NotificationEntry(BaseModel):
    id: str = ""
    recipient_id: str = ""
    kind: str
    title: str
    body: str = ""
    link: str = ""
    is_read: bool = False
    created_at: str = ""


class NotificationBatchRead(BaseModel):
    notification_ids: list[str] = Field(min_length=1, max_length=200)


# ===========================================================================
# Phase J — Production & AMD Radeon Optimization models
# ===========================================================================


class QueueStatus(BaseModel):
    """Real-time task queue status."""
    active_llm_calls: int = 0
    active_embedding_calls: int = 0
    queued_calls: int = 0
    total_completed: int = 0
    total_cancelled: int = 0
    total_timeouts: int = 0
    total_errors: int = 0
    global_llm_capacity: int = 4
    global_embedding_capacity: int = 8


class CacheStats(BaseModel):
    """Cache statistics."""
    enabled: bool = True
    size: int = 0
    max_entries: int = 5000
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0
    evictions: int = 0
    ttls: dict[str, int] = Field(default_factory=dict)


class CacheInvalidateRequest(BaseModel):
    """Request to invalidate cache entries."""
    project_id: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, pattern="^(index|embedding|report)$")
    key_prefix: str | None = Field(default=None, max_length=256)


class GPUMetricModel(BaseModel):
    """GPU metric for API response."""
    device_id: int = 0
    name: str = ""
    vram_total_mb: float = 0.0
    vram_used_mb: float = 0.0
    vram_free_mb: float = 0.0
    utilization_pct: float = 0.0
    temperature_c: float = 0.0


class ModelMetadataModel(BaseModel):
    """Model metadata for API response."""
    model_name: str = ""
    model_path: str = ""
    quantization: str = ""
    context_size: int = 0
    gpu_layers: int = 0
    backend: str = "rocm"
    llama_cpp_version: str = ""


class SystemMetricsModel(BaseModel):
    """System metrics for API response."""
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    disk_used_pct: float = 0.0


class HealthCheckResponse(BaseModel):
    """Full health check response."""
    status: str = "healthy"  # healthy | degraded | critical
    issues: list[dict[str, str]] = Field(default_factory=list)
    gpu_metrics: list[GPUMetricModel] = Field(default_factory=list)
    system_metrics: SystemMetricsModel = Field(default_factory=SystemMetricsModel)
    model_metadata: ModelMetadataModel = Field(default_factory=ModelMetadataModel)
    llm_error_rate: float = 0.0
    queue_status: QueueStatus = Field(default_factory=QueueStatus)
    cache_stats: CacheStats = Field(default_factory=CacheStats)
    timestamp: float = 0.0


class BenchmarkSnapshotModel(BaseModel):
    """Benchmark snapshot for API."""
    label: str = ""
    first_token_latency_ms: float = 0.0
    generation_tokens_per_second: float = 0.0
    embedding_throughput_texts_per_second: float = 0.0
    end_to_end_latency_ms: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    gpu_utilization_pct: float = 0.0
    gpu_model: str = ""
    quantization: str = ""
    llama_cpp_version: str = ""
    backend: str = "rocm"
    context_size: int = 0
    gpu_layers: int = 0
    timestamp: float = 0.0


class BenchmarkCompareResponse(BaseModel):
    """Before/after benchmark comparison."""
    baseline_label: str = ""
    optimized_label: str = ""
    first_token_latency: dict[str, float] = Field(default_factory=dict)
    generation_speed: dict[str, float] = Field(default_factory=dict)
    embedding_throughput: dict[str, float] = Field(default_factory=dict)
    end_to_end_latency: dict[str, float] = Field(default_factory=dict)
    vram_usage: dict[str, float] = Field(default_factory=dict)
    gpu_utilization: dict[str, float] = Field(default_factory=dict)
    hardware_info: dict[str, str] = Field(default_factory=dict)


class BackupCreateRequest(BaseModel):
    """Request to create a backup."""
    label: str = Field(default="", max_length=200)


class BackupEntry(BaseModel):
    """A backup entry in the listing."""
    backup_dir: str = ""
    name: str = ""
    timestamp: str = ""
    label: str = ""
    total_size_bytes: int = 0
    file_count: int = 0
    status: str = "success"


class BackupRestoreRequest(BaseModel):
    """Request to restore from a backup."""
    backup_dir: str = Field(min_length=1, max_length=1024)
    dry_run: bool = False


class LogRotationResult(BaseModel):
    """Log rotation result."""
    rotated: bool = False
    reason: str = ""
    size_mb: float = 0.0
    max_mb: float = 0.0
    old_path: str = ""
    new_path: str = ""
    compressed: bool = False


class StressTestConfigModel(BaseModel):
    """Stress test configuration."""
    large_file_count: int = Field(default=1, ge=0, le=100)
    large_file_size_mb: int = Field(default=10, ge=1, le=1000)
    batch_file_count: int = Field(default=20, ge=1, le=1000)
    batch_file_size_kb: int = Field(default=50, ge=1, le=10240)
    long_context_prompt_tokens: int = Field(default=4000, ge=100, le=32000)
    long_context_requests: int = Field(default=5, ge=1, le=100)
    multi_project_count: int = Field(default=4, ge=1, le=50)
    multi_project_requests_per_project: int = Field(default=10, ge=1, le=100)  # noqa: E501
