"""Public API and internal result schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

LENS_PACKS = (
    "profile_basics",
    "privacy_safety",
    "global_professional_context",
    "open_chinese_symbolism",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class AccessSession(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    expires_at: datetime
    session_id: str


class ThreadCreate(BaseModel):
    user_id: str = Field(default="demo-user", min_length=1, max_length=128)


class ThreadSummary(BaseModel):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


class ImageSummary(BaseModel):
    id: str
    thread_id: str
    original_name: str
    mime_type: str
    width: int
    height: int
    sha256: str
    created_at: datetime


class MessageRecord(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ThreadDetail(ThreadSummary):
    images: list[ImageSummary]
    messages: list[MessageRecord]


class RunRecord(BaseModel):
    id: str
    thread_id: str
    status: str
    request: dict[str, Any]
    result: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None


class AnalysisRunRequest(BaseModel):
    message: str = Field(min_length=3, max_length=4000)
    platform: str = Field(default="general", min_length=1, max_length=80)
    audience: str = Field(default="international collaborators", max_length=300)
    intent_keywords: list[str] = Field(default_factory=list, max_length=10)
    image_ids: list[str] = Field(min_length=1, max_length=4)
    enabled_packs: list[str] = Field(default_factory=lambda: list(LENS_PACKS))
    enable_private_lens: bool = False
    reuse_latest_analysis: bool = False


class AnalysisRunAccepted(BaseModel):
    run_id: str
    thread_id: str
    status: Literal["running"] = "running"
    poll_after_ms: int = Field(default=1000, ge=250, le=5000)


class EvidenceCard(BaseModel):
    card_id: str
    text: str
    pack: str
    source_title: str
    source_url: str
    license: str
    tags: list[str]
    score: float = 0.0


class ToolTrace(BaseModel):
    node: str
    tool: str
    status: Literal["completed", "failed", "skipped", "blocked"]
    duration_ms: float = 0.0
    summary: str = ""


class VisualObservation(BaseModel):
    visible_elements: list[str] = Field(default_factory=list, max_length=20)
    composition: str = Field(default="Not assessed", max_length=1000)
    text_candidates: list[str] = Field(default_factory=list, max_length=20)
    privacy_candidates: list[str] = Field(default_factory=list, max_length=20)
    uncertainties: list[str] = Field(default_factory=list, max_length=20)


class PrivateLensDraft(BaseModel):
    """Model-facing output for an optional, locally mounted private Lens Tool."""

    observed_motifs: list[str] = Field(default_factory=list, max_length=12)
    symbolic_associations: list[str] = Field(default_factory=list, max_length=8)
    technique_references: list[str] = Field(default_factory=list, max_length=8)
    uncertainties: list[str] = Field(default_factory=list, max_length=8)


class PrivateLensReading(PrivateLensDraft):
    image_id: str
    lens_name: str


class CandidateAssessment(BaseModel):
    image_id: str
    crop_resilience: int = Field(ge=0, le=5)
    small_size_clarity: int = Field(ge=0, le=5)
    privacy_safety: int = Field(ge=0, le=5)
    intent_alignment: int = Field(ge=0, le=5)
    contextual_ambiguity: int = Field(ge=0, le=5)
    rationale: str = Field(min_length=3, max_length=1200)


class CandidateComparison(BaseModel):
    recommended_image_id: str
    candidates: list[CandidateAssessment] = Field(min_length=2, max_length=4)
    decision_rule: str = Field(min_length=3, max_length=1200)
    caveat: str = Field(default="", max_length=1200)


class MemoryProposalDraft(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    memory_type: Literal["preference", "goal", "correction", "outcome"]
    reason: str = Field(min_length=3, max_length=500)


class StructuredReportDraft(BaseModel):
    summary: str = Field(min_length=3, max_length=2000)
    observed: list[str] = Field(default_factory=list, max_length=20)
    privacy: list[str] = Field(default_factory=list, max_length=20)
    context: list[str] = Field(default_factory=list, max_length=20)
    recommendations: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    cited_card_ids: list[str] = Field(default_factory=list, max_length=8)


class FollowUpDraft(BaseModel):
    answer: str = Field(min_length=3, max_length=2000)
    supporting_points: list[str] = Field(default_factory=list, max_length=8)
    cited_card_ids: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=4)


class PerformanceMetrics(BaseModel):
    total_duration_ms: float = 0.0
    local_tool_duration_ms: float = 0.0
    model_duration_ms: float = 0.0
    retrieval_duration_ms: float = 0.0
    image_count: int = 0
    evidence_count: int = 0


class AnalysisRunResponse(BaseModel):
    run_id: str
    thread_id: str
    status: Literal["completed", "blocked", "failed"]
    plan: list[str]
    observations: list[dict[str, Any]]
    private_lens_readings: list[PrivateLensReading]
    privacy_findings: list[dict[str, Any]]
    evidence: list[EvidenceCard]
    recalled_memories: list[dict[str, Any]]
    image_labels: dict[str, str]
    comparison: CandidateComparison | None = None
    memory_proposal: MemoryProposal | None = None
    report_markdown: str
    tool_trace: list[ToolTrace]
    performance_metrics: PerformanceMetrics


class MemoryProposalCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=3, max_length=1000)
    memory_type: Literal["preference", "goal", "correction", "outcome"]


class MemoryProposal(BaseModel):
    consent_id: str = Field(validation_alias="id")
    thread_id: str
    user_id: str
    text: str = Field(validation_alias="proposed_text")
    memory_type: str
    status: Literal["pending", "approved", "rejected"]
    created_at: datetime


class ConsentDecision(BaseModel):
    action: Literal["approve", "reject"]
    edited_text: str | None = Field(default=None, min_length=3, max_length=1000)


class MemoryRecord(BaseModel):
    id: str
    user_id: str
    text: str
    memory_type: str
    source_thread_id: str
    consent_id: str
    active: bool
    created_at: datetime


class ForgetMeResult(BaseModel):
    user_id: str
    threads_deleted: int
    images_deleted: int
    memories_deleted: int


class SystemStatus(BaseModel):
    app: str
    version: str
    environment: str
    deployment_mode: str
    auth_enabled: bool
    model_configured: bool
    model_reachable: bool | None
    model_endpoint: str
    model_name: str
    inference_ownership: str
    submission_topology_compliant: bool
    milvus_uri: str
    milvus_ready: bool
    sqlite_path: str
    private_lens_available: bool
    private_lens_name: str
