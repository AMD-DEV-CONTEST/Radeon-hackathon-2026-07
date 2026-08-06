"""Small immutable contracts shared by the Shidu domain services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID


T = TypeVar("T")


@dataclass(frozen=True)
class Stored(Generic[T]):
    value: T
    created: bool


@dataclass(frozen=True)
class Book:
    id: UUID
    project_id: UUID
    identity_digest: str
    title: str
    author: str
    language: str
    edition: str
    translator: str
    created_at: datetime


@dataclass(frozen=True)
class BookMergeRecord:
    id: UUID
    project_id: UUID
    source_book_id: UUID
    target_book_id: UUID
    reason: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class InputResolution:
    id: UUID
    project_id: UUID
    raw_input: str
    status: str
    candidate_book_ids: tuple[UUID, ...]
    selected_book_id: UUID | None
    digest: str
    created_at: datetime


@dataclass(frozen=True)
class BookDiscoveryCandidate:
    """Reader identity whose content digest is a local exact-body observation."""

    id: UUID
    project_id: UUID
    input_resolution_id: UUID
    ordinal: int
    title: str
    author: str
    language: str
    edition: str
    translator: str
    identity_digest: str
    canonical_url: str
    reader_content_digest: str
    search_provider: str
    search_schema_digest: str
    reader_provider: str
    reader_schema_digest: str
    created_at: datetime


@dataclass(frozen=True)
class BookDiscoveryResolution:
    id: UUID
    project_id: UUID
    raw_input: str
    status: str
    selected_book_id: UUID | None
    candidates: tuple[BookDiscoveryCandidate, ...]
    digest: str
    created_at: datetime

    @property
    def retryable(self) -> bool:
        return False


@dataclass(frozen=True)
class BookDiscoverySelection:
    id: UUID
    project_id: UUID
    input_resolution_id: UUID
    candidate_id: UUID
    book_id: UUID
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class ResearchJob:
    id: UUID
    project_id: UUID
    book_id: UUID
    provider_version: str
    status: str
    query_budget: int
    reader_budget: int
    retry_budget: int
    digest: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class SearchQuery:
    id: UUID
    project_id: UUID
    research_job_id: UUID
    ordinal: int
    query: str
    provider: str
    provider_version: str
    digest: str


@dataclass(frozen=True)
class SearchHit:
    id: UUID
    project_id: UUID
    research_job_id: UUID
    search_query_id: UUID
    ordinal: int
    canonical_url: str
    title: str
    snippet: str
    source_type: str
    digest: str


@dataclass(frozen=True)
class SourceFailure:
    id: UUID
    project_id: UUID
    research_job_id: UUID
    stage: str
    canonical_url: str
    reason_code: str
    attempts: int
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class SourceDocumentRevision:
    id: UUID
    project_id: UUID
    research_job_id: UUID
    canonical_url: str
    source_type: str
    source_classification_version: str
    registered_domain: str
    search_hit_id: UUID | None
    revision: int
    content: str
    content_digest: str
    digest: str
    command_key: str
    created_at: datetime
    interaction_observed: bool = False
    interaction_signal: float | None = None
    interaction_metrics: dict[str, int] | None = None
    interaction_normalization_version: str = "shidu-public-interaction-v1"


@dataclass(frozen=True)
class EvidenceClaim:
    id: UUID
    project_id: UUID
    research_job_id: UUID
    source_document_revision_id: UUID
    claim_type: str
    normalized_claim: str
    source_span: dict[str, Any]
    excerpt_digest: str
    is_direct_quote: bool
    spoiler_level: str
    confidence: float
    conflict_group_key: str | None
    conflict_severity: str | None
    digest: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class EvidenceClaimDraft:
    project_id: UUID
    research_job_id: UUID
    source_document_revision_id: UUID
    claim_type: str
    normalized_claim: str
    source_span_start: int
    source_span_end: int
    excerpt_digest: str
    is_direct_quote: bool
    spoiler_level: str
    confidence: float
    conflict_key: str | None = None
    conflict_severity: str | None = None


@dataclass(frozen=True)
class EvidenceConflictAdjudicationRevision:
    id: UUID
    project_id: UUID
    research_job_id: UUID
    revision: int
    evidence_ids: tuple[UUID, ...]
    evidence_set_digest: str
    adjudicator_version: str
    decisions: tuple[dict[str, Any], ...]
    digest: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class EvidencePackRevision:
    id: UUID
    project_id: UUID
    research_job_id: UUID
    revision: int
    evidence_ids: tuple[UUID, ...]
    conflict_adjudication_revision_id: UUID
    adjudicator_version: str
    conflicts: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]
    publishable: bool
    insufficiency_reason_codes: tuple[str, ...]
    digest: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class ResonanceDirectionRevision:
    id: UUID
    project_id: UUID
    evidence_pack_revision_id: UUID
    direction_key: str
    revision: int
    publication_ordinal: int
    evidence_count: int
    score: float
    score_version: str
    validator_version: str
    payload: dict[str, Any]
    digest: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class TrialMethodologyRevision:
    id: UUID
    project_id: UUID
    methodology_key: str
    methodology_version: str
    revision: int
    prompt_digest: str
    validator_version: str
    payload: dict[str, Any]
    digest: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class TrialScriptRevision:
    id: UUID
    project_id: UUID
    book_id: UUID
    evidence_pack_revision_id: UUID
    resonance_direction_revision_id: UUID
    methodology_revision_id: UUID
    revision: int
    validator_version: str
    payload: dict[str, Any]
    digest: str
    command_key: str
    created_at: datetime
    source_trial_script_revision_id: UUID | None = None
    source_safety_decision_digest: str | None = None


@dataclass(frozen=True)
class VoicePresetRevision:
    id: UUID
    project_id: UUID
    preset_key: str
    revision: int
    provider: str
    model_id: str
    model_digest: str
    speaker: str
    language: str
    instruction_digest: str
    enabled: bool
    discovery_service_version: str
    discovery_tool_name: str
    discovery_schema_digest: str
    payload: dict[str, Any]
    digest: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class TTSTake:
    id: UUID
    project_id: UUID
    trial_script_revision_id: UUID
    voice_preset_revision_id: UUID
    cue_key: str
    requested_provider: str
    requested_model_id: str
    actual_provider: str
    actual_model_id: str
    actual_service_version: str
    actual_tool_name: str
    actual_schema_digest: str
    speaker: str
    language: str
    instruction_digest: str
    audio_artifact_id: UUID
    audio_digest: str
    qc_accepted: bool
    retry_count: int
    error_classification: str | None
    lipsync_required: bool
    metadata: dict[str, Any]
    digest: str
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class VideoJobProjection:
    id: UUID
    project_id: UUID
    book_id: UUID
    external_job_id: str
    status: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ReaderFeedback:
    id: UUID
    project_id: UUID
    book_id: UUID
    rating: int | None
    payload: dict[str, Any]
    digest: str


@dataclass(frozen=True)
class VideoBookBinding:
    id: UUID
    project_id: UUID
    video_id: str
    book_id: UUID
    command_key: str
    created_at: datetime


@dataclass(frozen=True)
class CreateBook:
    project_id: UUID
    title: str
    author: str
    language: str
    edition: str
    translator: str
    command_key: str


@dataclass(frozen=True)
class DiscoveredBookIdentity:
    title: str
    author: str
    language: str
    edition: str
    translator: str
    canonical_url: str
    reader_content_digest: str


@dataclass(frozen=True)
class CreateBookDiscoveryResolution:
    project_id: UUID
    raw_input: str
    candidates: tuple[DiscoveredBookIdentity, ...]
    search_provider: str
    search_schema_digest: str
    reader_provider: str
    reader_schema_digest: str
    command_key: str


@dataclass(frozen=True)
class SelectBookDiscoveryCandidate:
    project_id: UUID
    input_resolution_id: UUID
    candidate_id: UUID
    command_key: str


@dataclass(frozen=True)
class MergeBooks:
    project_id: UUID
    source_book_id: UUID
    target_book_id: UUID
    reason: str
    command_key: str


@dataclass(frozen=True)
class BindVideoToBook:
    project_id: UUID
    video_id: str
    book_id: UUID
    command_key: str


@dataclass(frozen=True)
class CreateResearchJob:
    project_id: UUID
    book_id: UUID
    provider_version: str
    command_key: str
    query_budget: int = 4
    reader_budget: int = 8
    retry_budget: int = 2


@dataclass(frozen=True)
class CreateSearchQuery:
    project_id: UUID
    research_job_id: UUID
    ordinal: int
    query: str
    provider: str
    provider_version: str
    command_key: str


@dataclass(frozen=True)
class CreateSearchHit:
    project_id: UUID
    search_query_id: UUID
    ordinal: int
    canonical_url: str
    title: str
    snippet: str
    source_type: str


@dataclass(frozen=True)
class StoreSourceFailure:
    project_id: UUID
    research_job_id: UUID
    stage: str
    canonical_url: str
    reason_code: str
    attempts: int
    command_key: str


@dataclass(frozen=True)
class StoreSourceDocument:
    project_id: UUID
    research_job_id: UUID
    canonical_url: str
    content: str
    command_key: str
    source_type: str = "web"
    source_classification_version: str = "shidu-source-type-v1"
    search_hit_id: UUID | None = None
    interaction_metrics: dict[str, int] | None = None


@dataclass(frozen=True)
class AppendEvidenceClaim:
    project_id: UUID
    research_job_id: UUID
    source_document_revision_id: UUID
    claim_type: str
    normalized_claim: str
    source_span_start: int
    source_span_end: int
    excerpt_digest: str
    is_direct_quote: bool
    spoiler_level: str
    confidence: float
    conflict_group_key: str | None
    conflict_severity: str | None
    command_key: str


@dataclass(frozen=True)
class StoreConflictAdjudication:
    project_id: UUID
    research_job_id: UUID
    evidence_ids: tuple[UUID, ...]
    evidence_set_digest: str
    adjudicator_version: str
    decisions: tuple[dict[str, Any], ...]
    command_key: str


@dataclass(frozen=True)
class FreezeEvidencePack:
    project_id: UUID
    research_job_id: UUID
    evidence_ids: tuple[UUID, ...]
    conflict_adjudication_revision_id: UUID
    command_key: str


@dataclass(frozen=True)
class DirectionDraft:
    direction_key: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishDirections:
    project_id: UUID
    evidence_pack_revision_id: UUID
    directions: tuple[DirectionDraft, ...]
    command_key: str


@dataclass(frozen=True)
class FreezeTrialMethodology:
    project_id: UUID
    methodology_key: str
    methodology_version: str
    prompt_digest: str
    validator_version: str
    payload: dict[str, Any]
    command_key: str


@dataclass(frozen=True)
class StoreTrialScript:
    project_id: UUID
    book_id: UUID
    evidence_pack_revision_id: UUID
    resonance_direction_revision_id: UUID
    methodology_revision_id: UUID
    payload: dict[str, Any]
    command_key: str
    source_trial_script_revision_id: UUID | None = None
    source_safety_decision_digest: str | None = None


@dataclass(frozen=True)
class StoreVoicePresetRevision:
    project_id: UUID
    preset_key: str
    provider: str
    model_id: str
    model_digest: str
    speaker: str
    language: str
    instruction: str | None
    applicable_book_categories: tuple[str, ...]
    default_gender: str
    enabled: bool
    discovery_service_version: str
    discovery_tool_name: str
    discovery_schema_digest: str
    discovered_speakers: tuple[str, ...]
    policy_allowed_speakers: tuple[str, ...]
    command_key: str


@dataclass(frozen=True)
class RecordTTSTake:
    project_id: UUID
    trial_script_revision_id: UUID
    voice_preset_revision_id: UUID
    cue_key: str
    cue_text_digest: str
    requested_provider: str
    requested_model_id: str
    actual_provider: str
    actual_model_id: str
    actual_service_version: str
    actual_tool_name: str
    actual_schema_digest: str
    speaker: str
    language: str
    instruction_digest: str
    audio_artifact_id: UUID
    audio_digest: str
    audio_byte_size: int
    audio_mime: str
    sample_rate_hz: int
    channels: int
    pcm_sample_width_bytes: int
    duration_seconds: float
    peak_amplitude: float
    clipping_ratio: float
    silence_ratio: float
    leading_silence_seconds: float
    trailing_silence_seconds: float
    qc_accepted: bool
    qc_defect_codes: tuple[str, ...]
    retry_count: int
    error_classification: str | None
    lipsync_required: bool
    command_key: str
