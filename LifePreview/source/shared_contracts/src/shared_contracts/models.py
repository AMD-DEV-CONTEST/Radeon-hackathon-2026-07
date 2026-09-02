from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid5

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)


Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")]
EntityType = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MimeType = Annotated[
    str,
    Field(
        min_length=3,
        max_length=127,
        pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
    ),
]
CapabilityName = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.:-]*$"),
]
SafeText = Annotated[str, Field(min_length=1, max_length=500)]
ModelName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._+:/@-]*$",
    ),
]
LongText = Annotated[str, Field(min_length=1, max_length=20_000)]
CanonicalJson = Annotated[str, Field(min_length=1, max_length=1_000_000)]
JsonPointer = Annotated[
    str,
    Field(
        min_length=2,
        max_length=500,
        pattern=r"^/(?:[^~/]|~0|~1)+(?:/(?:[^~/]|~0|~1)+)*$",
    ),
]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContractVersion(StrictFrozenModel):
    major: Literal[1] = 1
    minor: NonNegativeInt = 0


class EntityDomain(StrEnum):
    PLATFORM = "platform"
    CREATIVE = "creative"
    FACTORY = "factory"
    SHARED = "shared"


class EntityRef(StrictFrozenModel):
    domain: EntityDomain
    entity_type: EntityType
    entity_id: UUID


class ComponentName(StrEnum):
    ANALYSIS = "analysis"
    CREATIVE_HUB = "creative_hub"
    DRAMA_FACTORY = "drama_factory"


class ArtifactRef(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    owner: ComponentName
    artifact_id: UUID
    sha256: Sha256Digest
    bytes: PositiveInt
    mime: MimeType
    version: PositiveInt


class EvidenceConsumer(StrEnum):
    LEARNING = "learning"
    FACTORY_QC = "factory_qc"
    HUB_EVALUATION = "hub_evaluation"


class EvidenceAvailability(StrEnum):
    OBSERVED = "observed"
    NA = "n/a"


class EvidenceModality(StrEnum):
    VISUAL_FRAME = "visual_frame"
    FACE_MOTION = "face_motion"
    AUDIO = "audio"
    TRANSCRIPT = "transcript"
    AUDIO_DSP = "audio_dsp"


class EvidenceSamplingReason(StrEnum):
    SCENE_ANCHOR = "scene_anchor"
    TRANSITION = "transition"
    SPEECH_MOTION = "speech_motion"
    ACTION_MOTION = "action_motion"


class EvidenceProcessor(StrictFrozenModel):
    role: Identifier
    name: ModelName
    version: ModelName
    config_sha256: Sha256Digest


class EvidenceCacheIdentity(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    source_sha256: Sha256Digest
    source_bytes: PositiveInt
    pipeline_version: Identifier
    processors: tuple[EvidenceProcessor, ...] = Field(min_length=1, max_length=32)

    @field_validator("processors")
    @classmethod
    def processor_roles_must_be_unique(
        cls,
        value: tuple[EvidenceProcessor, ...],
    ) -> tuple[EvidenceProcessor, ...]:
        roles = [processor.role for processor in value]
        if len(roles) != len(set(roles)):
            raise ValueError("evidence processor roles must be unique")
        return value


def stable_evidence_cache_key(identity: EvidenceCacheIdentity) -> str:
    processors = sorted(
        (
            processor.model_dump(mode="json")
            for processor in identity.processors
        ),
        key=lambda processor: processor["role"],
    )
    payload = {
        "contract_version": identity.contract_version.model_dump(mode="json"),
        "source_sha256": identity.source_sha256,
        "source_bytes": identity.source_bytes,
        "pipeline_version": identity.pipeline_version,
        "processors": processors,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_EVIDENCE_BUNDLE_NAMESPACE = UUID("45e0ea24-a3d2-5437-87e4-a2cc6c87e565")


def evidence_bundle_id(cache_key: str) -> UUID:
    if len(cache_key) != 64 or any(
        character not in "0123456789abcdef"
        for character in cache_key
    ):
        raise ValueError("evidence cache key is invalid")
    return uuid5(_EVIDENCE_BUNDLE_NAMESPACE, cache_key)


class FrameEvidence(StrictFrozenModel):
    frame_id: UUID
    timestamp_ms: NonNegativeInt
    scene_index: NonNegativeInt
    reasons: tuple[EvidenceSamplingReason, ...] = Field(
        min_length=1,
        max_length=4,
    )
    artifact: ArtifactRef

    @field_validator("reasons")
    @classmethod
    def reasons_must_be_unique(
        cls,
        value: tuple[EvidenceSamplingReason, ...],
    ) -> tuple[EvidenceSamplingReason, ...]:
        if len(value) != len(set(value)):
            raise ValueError("frame sampling reasons must be unique")
        return value


class TranscriptEvidenceSegment(StrictFrozenModel):
    segment_id: UUID
    start_ms: NonNegativeInt
    end_ms: PositiveInt
    text: str = Field(min_length=1, max_length=10_000)
    language: str | None = Field(
        default=None,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    emotion: Identifier | None = None
    audio_events: tuple[Identifier, ...] = Field(default=(), max_length=32)
    speaker: Identifier | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("transcript segment end must be after start")
        if len(self.audio_events) != len(set(self.audio_events)):
            raise ValueError("audio events must be unique")
        return self


class AudioMetrics(StrictFrozenModel):
    availability: EvidenceAvailability
    reason: SafeText | None = None
    rms_loudness_dbfs: float | None = Field(default=None, ge=-160, le=6)
    peak_dbfs: float | None = Field(default=None, ge=-160, le=6)
    silence_ratio: float | None = Field(default=None, ge=0, le=1)
    clipping_ratio: float | None = Field(default=None, ge=0, le=1)
    estimated_snr_db: float | None = Field(default=None, ge=-40, le=160)

    @model_validator(mode="after")
    def availability_matches_values(self):
        metrics = (
            self.rms_loudness_dbfs,
            self.peak_dbfs,
            self.silence_ratio,
            self.clipping_ratio,
        )
        if self.availability is EvidenceAvailability.NA:
            if not self.reason:
                raise ValueError("N/A audio metrics require a reason")
            if any(value is not None for value in (*metrics, self.estimated_snr_db)):
                raise ValueError("N/A audio metrics cannot contain observations")
        else:
            if self.reason:
                raise ValueError("observed audio metrics cannot contain an N/A reason")
            if any(value is None for value in metrics):
                raise ValueError("observed audio metrics are incomplete")
        return self


class DimensionCoverage(StrictFrozenModel):
    dimension: Identifier
    availability: EvidenceAvailability
    modalities: tuple[EvidenceModality, ...] = Field(default=(), max_length=8)
    reason: SafeText | None = None

    @model_validator(mode="after")
    def availability_requires_evidence_or_reason(self):
        if len(self.modalities) != len(set(self.modalities)):
            raise ValueError("coverage modalities must be unique")
        if self.availability is EvidenceAvailability.NA and not self.reason:
            raise ValueError("N/A coverage requires a reason")
        if self.availability is EvidenceAvailability.OBSERVED:
            if self.reason:
                raise ValueError("observed coverage cannot contain an N/A reason")
            if not self.modalities:
                raise ValueError("observed coverage requires an evidence modality")
        return self


class EvidenceProviderRun(StrictFrozenModel):
    role: Identifier
    name: ModelName
    version: ModelName
    capabilities: tuple[Identifier, ...] = Field(default=(), max_length=32)
    fallback_used: bool = False
    fallback_reason: Identifier | None = None

    @model_validator(mode="after")
    def fallback_is_explicit(self):
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("provider capabilities must be unique")
        if self.fallback_used != (self.fallback_reason is not None):
            raise ValueError("fallback use and reason must be recorded together")
        return self


class EvidenceWindow(StrictFrozenModel):
    window_id: UUID
    start_ms: NonNegativeInt
    end_ms: PositiveInt
    frame_ids: tuple[UUID, ...] = Field(default=(), max_length=10_000)
    transcript_segment_ids: tuple[UUID, ...] = Field(
        default=(),
        max_length=10_000,
    )
    labels: tuple[Identifier, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("evidence window end must be after start")
        if len(self.frame_ids) != len(set(self.frame_ids)):
            raise ValueError("evidence window frame references must be unique")
        if len(self.transcript_segment_ids) != len(
            set(self.transcript_segment_ids)
        ):
            raise ValueError(
                "evidence window transcript references must be unique"
            )
        if len(self.labels) != len(set(self.labels)):
            raise ValueError("evidence window labels must be unique")
        return self


class TimelineEvidenceBundle(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    bundle_id: UUID
    cache_key: Sha256Digest
    cache_identity: EvidenceCacheIdentity
    source: ArtifactRef
    duration_ms: PositiveInt
    frames: tuple[FrameEvidence, ...] = Field(default=(), max_length=50_000)
    transcript: tuple[TranscriptEvidenceSegment, ...] = Field(
        default=(),
        max_length=100_000,
    )
    audio_metrics: AudioMetrics
    windows: tuple[EvidenceWindow, ...] = Field(
        default=(),
        max_length=50_000,
    )
    coverage: tuple[DimensionCoverage, ...] = Field(
        default=(),
        max_length=256,
    )
    providers: tuple[EvidenceProviderRun, ...] = Field(
        default=(),
        max_length=32,
    )
    consumers: tuple[EvidenceConsumer, ...] = Field(
        default=tuple(EvidenceConsumer),
        min_length=3,
        max_length=3,
    )

    @model_validator(mode="after")
    def validate_bundle(self):
        if (
            self.source.sha256 != self.cache_identity.source_sha256
            or self.source.bytes != self.cache_identity.source_bytes
        ):
            raise ValueError("evidence source does not match cache identity")
        expected_key = stable_evidence_cache_key(self.cache_identity)
        if self.cache_key != expected_key:
            raise ValueError("evidence cache key does not match identity")
        if self.bundle_id != evidence_bundle_id(expected_key):
            raise ValueError("evidence bundle id is not deterministic")
        if set(self.consumers) != set(EvidenceConsumer):
            raise ValueError("evidence bundle must support all shared consumers")

        frame_ids: set[UUID] = set()
        previous_frame = -1
        for frame in self.frames:
            if frame.frame_id in frame_ids:
                raise ValueError("frame evidence ids must be unique")
            if (
                frame.timestamp_ms < previous_frame
                or frame.timestamp_ms >= self.duration_ms
            ):
                raise ValueError("frame evidence timeline is invalid")
            frame_ids.add(frame.frame_id)
            previous_frame = frame.timestamp_ms

        segment_ids: set[UUID] = set()
        previous_segment_end = 0
        for segment in self.transcript:
            if segment.segment_id in segment_ids:
                raise ValueError("transcript evidence ids must be unique")
            if (
                segment.start_ms < previous_segment_end
                or segment.end_ms > self.duration_ms
            ):
                raise ValueError("transcript evidence timeline is invalid")
            segment_ids.add(segment.segment_id)
            previous_segment_end = segment.end_ms

        previous_window_end = 0
        window_ids: set[UUID] = set()
        for window in self.windows:
            if (
                window.window_id in window_ids
                or window.start_ms < previous_window_end
                or window.end_ms > self.duration_ms
                or not set(window.frame_ids).issubset(frame_ids)
                or not set(window.transcript_segment_ids).issubset(segment_ids)
            ):
                raise ValueError("evidence windows are invalid")
            window_ids.add(window.window_id)
            previous_window_end = window.end_ms

        dimensions = [item.dimension for item in self.coverage]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("coverage dimensions must be unique")
        for item in self.coverage:
            if (
                item.dimension == "lip_sync"
                and item.availability is EvidenceAvailability.OBSERVED
                and not {
                    EvidenceModality.AUDIO,
                    EvidenceModality.TRANSCRIPT,
                    EvidenceModality.FACE_MOTION,
                }.issubset(item.modalities)
            ):
                raise ValueError(
                    "lip sync requires audio, transcript, and face motion evidence"
                )

        roles = [provider.role for provider in self.providers]
        if len(roles) != len(set(roles)):
            raise ValueError("provider roles must be unique")
        return self


def build_timeline_evidence_bundle(
    *,
    source: ArtifactRef,
    cache_identity: EvidenceCacheIdentity,
    duration_ms: int,
    frames: tuple[FrameEvidence, ...],
    transcript: tuple[TranscriptEvidenceSegment, ...],
    audio_metrics: AudioMetrics,
    coverage: tuple[DimensionCoverage, ...],
    providers: tuple[EvidenceProviderRun, ...],
    windows: tuple[EvidenceWindow, ...] = (),
) -> TimelineEvidenceBundle:
    cache_key = stable_evidence_cache_key(cache_identity)
    return TimelineEvidenceBundle(
        bundle_id=evidence_bundle_id(cache_key),
        cache_key=cache_key,
        cache_identity=cache_identity,
        source=source,
        duration_ms=duration_ms,
        frames=frames,
        transcript=transcript,
        audio_metrics=audio_metrics,
        windows=windows,
        coverage=coverage,
        providers=providers,
    )


def evidence_bundle_for_consumer(
    bundle: TimelineEvidenceBundle,
    consumer: EvidenceConsumer,
) -> TimelineEvidenceBundle:
    if consumer not in bundle.consumers:
        raise ValueError("evidence consumer is not supported")
    return bundle


def canonical_json(value: JsonValue) -> str:
    """Return the single UTF-8 JSON spelling used by immutable contracts."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def stable_json_sha256(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_canonical_json(value: str) -> str:
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("value must be valid JSON") from exc
    if canonical_json(decoded) != value:
        raise ValueError("value must use canonical JSON encoding")
    return value


class EvidenceSpan(StrictFrozenModel):
    bundle_id: UUID
    start_ms: NonNegativeInt
    end_ms: PositiveInt
    window_ids: tuple[UUID, ...] = Field(default=(), max_length=1_000)
    frame_ids: tuple[UUID, ...] = Field(default=(), max_length=10_000)
    transcript_segment_ids: tuple[UUID, ...] = Field(
        default=(),
        max_length=10_000,
    )
    observation_kind: Identifier
    note: SafeText | None = None

    @model_validator(mode="after")
    def validate_span(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("evidence span end must be after start")
        reference_groups = (
            self.window_ids,
            self.frame_ids,
            self.transcript_segment_ids,
        )
        if not any(reference_groups):
            raise ValueError("evidence span requires a concrete evidence reference")
        if any(len(group) != len(set(group)) for group in reference_groups):
            raise ValueError("evidence span references must be unique")
        return self


class KnowledgeCard(StrictFrozenModel):
    title: SafeText
    category: Identifier
    claim: LongText
    transfer_recipe: LongText
    applicability: tuple[SafeText, ...] = Field(default=(), max_length=128)
    contraindications: tuple[SafeText, ...] = Field(default=(), max_length=128)
    anti_patterns: tuple[SafeText, ...] = Field(default=(), max_length=128)
    evidence_spans: tuple[EvidenceSpan, ...] = Field(
        min_length=1,
        max_length=10_000,
    )
    evidence_strength: float = Field(ge=0, le=1)
    model_confidence: float = Field(ge=0, le=1)
    rights_status: Identifier
    allowed_use: tuple[Identifier, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def lists_must_be_unique(self):
        groups = (
            self.applicability,
            self.contraindications,
            self.anti_patterns,
            self.evidence_spans,
            self.allowed_use,
        )
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("knowledge card list values must be unique")
        return self


_KNOWLEDGE_REVISION_NAMESPACE = UUID("93949cd9-0c76-5bd6-8295-73aa7d225873")
_KNOWLEDGE_REVIEW_NAMESPACE = UUID("99c1a338-e54c-5b23-bae6-8529f37ddf54")
_KNOWLEDGE_PACK_NAMESPACE = UUID("fe552020-c8cb-5369-bfa6-456bb3a53100")
_IMPORT_PLAN_NAMESPACE = UUID("9ba405f3-5974-5c80-9a8e-9cc7931e0b5d")


def _revision_identity_payload(
    *,
    knowledge_id: UUID,
    revision: int,
    card: KnowledgeCard,
    created_by: str,
    model_version: str | None,
    prompt_version: str | None,
    created_at: datetime,
) -> dict[str, JsonValue]:
    return {
        "knowledge_id": str(knowledge_id),
        "revision": revision,
        "card": card.model_dump(mode="json"),
        "created_by": created_by,
        "model_version": model_version,
        "prompt_version": prompt_version,
        "created_at": created_at.isoformat(),
    }


class KnowledgeRevision(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    revision_id: UUID
    revision_sha256: Sha256Digest
    knowledge_id: UUID
    revision: PositiveInt
    card: KnowledgeCard
    created_by: Identifier
    model_version: ModelName | None = None
    prompt_version: ModelName | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def identity_matches_content(self):
        digest = stable_json_sha256(
            _revision_identity_payload(
                knowledge_id=self.knowledge_id,
                revision=self.revision,
                card=self.card,
                created_by=self.created_by,
                model_version=self.model_version,
                prompt_version=self.prompt_version,
                created_at=self.created_at,
            )
        )
        if self.revision_sha256 != digest:
            raise ValueError("knowledge revision hash does not match its content")
        if self.revision_id != uuid5(_KNOWLEDGE_REVISION_NAMESPACE, digest):
            raise ValueError("knowledge revision id is not deterministic")
        return self


def build_knowledge_revision(
    *,
    knowledge_id: UUID,
    revision: int,
    card: KnowledgeCard,
    created_by: str,
    created_at: datetime,
    model_version: str | None = None,
    prompt_version: str | None = None,
) -> KnowledgeRevision:
    digest = stable_json_sha256(
        _revision_identity_payload(
            knowledge_id=knowledge_id,
            revision=revision,
            card=card,
            created_by=created_by,
            model_version=model_version,
            prompt_version=prompt_version,
            created_at=created_at,
        )
    )
    return KnowledgeRevision(
        revision_id=uuid5(_KNOWLEDGE_REVISION_NAMESPACE, digest),
        revision_sha256=digest,
        knowledge_id=knowledge_id,
        revision=revision,
        card=card,
        created_by=created_by,
        model_version=model_version,
        prompt_version=prompt_version,
        created_at=created_at,
    )


class KnowledgeReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


def _review_identity_payload(
    *,
    revision_id: UUID,
    revision_sha256: str,
    decision: KnowledgeReviewDecision,
    reviewed_by: str,
    reason: str | None,
    reviewed_at: datetime,
) -> dict[str, JsonValue]:
    return {
        "revision_id": str(revision_id),
        "revision_sha256": revision_sha256,
        "decision": decision.value,
        "reviewer_type": "human",
        "reviewed_by": reviewed_by,
        "reason": reason,
        "reviewed_at": reviewed_at.isoformat(),
    }


class KnowledgeReview(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    review_id: UUID
    review_sha256: Sha256Digest
    revision_id: UUID
    revision_sha256: Sha256Digest
    decision: KnowledgeReviewDecision
    reviewer_type: Literal["human"] = "human"
    reviewed_by: Identifier
    reason: SafeText | None = None
    reviewed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_review(self):
        if self.decision is KnowledgeReviewDecision.REJECTED and not self.reason:
            raise ValueError("rejected knowledge review requires a reason")
        digest = stable_json_sha256(
            _review_identity_payload(
                revision_id=self.revision_id,
                revision_sha256=self.revision_sha256,
                decision=self.decision,
                reviewed_by=self.reviewed_by,
                reason=self.reason,
                reviewed_at=self.reviewed_at,
            )
        )
        if self.review_sha256 != digest:
            raise ValueError("knowledge review hash does not match its content")
        if self.review_id != uuid5(_KNOWLEDGE_REVIEW_NAMESPACE, digest):
            raise ValueError("knowledge review id is not deterministic")
        return self


def build_knowledge_review(
    revision: KnowledgeRevision,
    *,
    decision: KnowledgeReviewDecision,
    reviewed_by: str,
    reviewed_at: datetime,
    reason: str | None = None,
) -> KnowledgeReview:
    digest = stable_json_sha256(
        _review_identity_payload(
            revision_id=revision.revision_id,
            revision_sha256=revision.revision_sha256,
            decision=decision,
            reviewed_by=reviewed_by,
            reason=reason,
            reviewed_at=reviewed_at,
        )
    )
    return KnowledgeReview(
        review_id=uuid5(_KNOWLEDGE_REVIEW_NAMESPACE, digest),
        review_sha256=digest,
        revision_id=revision.revision_id,
        revision_sha256=revision.revision_sha256,
        decision=decision,
        reviewed_by=reviewed_by,
        reason=reason,
        reviewed_at=reviewed_at,
    )


class ApprovedKnowledgeRevision(StrictFrozenModel):
    revision: KnowledgeRevision
    review: KnowledgeReview

    @model_validator(mode="after")
    def review_approves_exact_revision(self):
        if (
            self.review.decision is not KnowledgeReviewDecision.APPROVED
            or self.review.revision_id != self.revision.revision_id
            or self.review.revision_sha256 != self.revision.revision_sha256
        ):
            raise ValueError("review does not approve the exact knowledge revision")
        return self


class RejectedKnowledgeRevision(StrictFrozenModel):
    revision: KnowledgeRevision
    review: KnowledgeReview

    @model_validator(mode="after")
    def review_rejects_exact_revision(self):
        if (
            self.review.decision is not KnowledgeReviewDecision.REJECTED
            or self.review.revision_id != self.revision.revision_id
            or self.review.revision_sha256 != self.revision.revision_sha256
        ):
            raise ValueError("review does not reject the exact knowledge revision")
        return self


class FactoryDocument(StrEnum):
    STORY_BIBLE = "story_bible"
    CHARACTER_BIBLE = "character_bible"
    SCENE_BIBLE = "scene_bible"
    SHOT_LIST = "shot_list"
    PROMPT_CONSTRAINTS = "prompt_constraints"


class FieldLock(StrictFrozenModel):
    document: FactoryDocument
    path: JsonPointer
    reason: SafeText


class FactoryDocumentSnapshot(StrictFrozenModel):
    document: FactoryDocument
    content_json: CanonicalJson

    @field_validator("content_json")
    @classmethod
    def content_must_be_canonical(cls, value: str) -> str:
        decoded = json.loads(_validate_canonical_json(value))
        if not isinstance(decoded, dict):
            raise ValueError("factory document snapshot must contain a JSON object")
        return value


class FactoryProjectSnapshot(StrictFrozenModel):
    schema_version: Identifier
    capabilities: tuple[CapabilityName, ...] = Field(default=(), max_length=256)
    documents: tuple[FactoryDocumentSnapshot, ...] = Field(
        min_length=1,
        max_length=10_000,
    )
    locked_fields: tuple[FieldLock, ...] = Field(default=(), max_length=10_000)

    @model_validator(mode="after")
    def values_must_be_unique(self):
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("factory capabilities must be unique")
        document_names = [item.document for item in self.documents]
        if len(document_names) != len(set(document_names)):
            raise ValueError("factory documents must be unique")
        lock_targets = [(item.document, item.path) for item in self.locked_fields]
        if len(lock_targets) != len(set(lock_targets)):
            raise ValueError("factory field locks must be unique")
        return self


class KnowledgePackTarget(StrictFrozenModel):
    genre: Identifier
    episode_count: PositiveInt
    episode_duration_seconds: PositiveInt
    directing_style: SafeText


class KnowledgeMappingPolicy(StrEnum):
    REPLACE = "replace"
    REVIEW = "review"


class KnowledgeRevisionRef(StrictFrozenModel):
    knowledge_id: UUID
    revision_id: UUID
    revision: PositiveInt
    revision_sha256: Sha256Digest
    approval_id: UUID
    approval_sha256: Sha256Digest


class KnowledgeMapping(StrictFrozenModel):
    mapping_id: Identifier
    source_revision_id: UUID
    document: FactoryDocument
    path: JsonPointer
    incoming_json: CanonicalJson
    policy: KnowledgeMappingPolicy = KnowledgeMappingPolicy.REVIEW
    enabled: bool = True
    disabled_reason: SafeText | None = None
    required_capabilities: tuple[CapabilityName, ...] = Field(
        default=(),
        max_length=64,
    )

    @field_validator("incoming_json")
    @classmethod
    def incoming_value_must_be_canonical(cls, value: str) -> str:
        return _validate_canonical_json(value)

    @model_validator(mode="after")
    def enabled_state_is_explicit(self):
        if self.enabled == (self.disabled_reason is not None):
            raise ValueError(
                "disabled mapping state and disabled reason must be recorded together"
            )
        if len(self.required_capabilities) != len(
            set(self.required_capabilities)
        ):
            raise ValueError("mapping capabilities must be unique")
        return self


def _knowledge_pack_identity_payload(
    *,
    revisions: tuple[KnowledgeRevisionRef, ...],
    target: KnowledgePackTarget,
    target_schema_version: str,
    required_capabilities: tuple[str, ...],
    mappings: tuple[KnowledgeMapping, ...],
    forbidden_fields: tuple[FieldLock, ...],
    created_by: str,
    created_at: datetime,
) -> dict[str, JsonValue]:
    return {
        "revisions": [item.model_dump(mode="json") for item in revisions],
        "target": target.model_dump(mode="json"),
        "target_schema_version": target_schema_version,
        "required_capabilities": list(required_capabilities),
        "mappings": [item.model_dump(mode="json") for item in mappings],
        "forbidden_fields": [
            item.model_dump(mode="json") for item in forbidden_fields
        ],
        "created_by": created_by,
        "created_at": created_at.isoformat(),
    }


class KnowledgePack(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    pack_id: UUID
    pack_sha256: Sha256Digest
    revisions: tuple[KnowledgeRevisionRef, ...] = Field(
        min_length=1,
        max_length=10_000,
    )
    target: KnowledgePackTarget
    target_schema_version: Identifier
    required_capabilities: tuple[CapabilityName, ...] = Field(
        default=(),
        max_length=256,
    )
    mappings: tuple[KnowledgeMapping, ...] = Field(
        min_length=1,
        max_length=100_000,
    )
    forbidden_fields: tuple[FieldLock, ...] = Field(
        default=(),
        max_length=10_000,
    )
    created_by: Identifier
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_pack(self):
        revision_ids = [item.revision_id for item in self.revisions]
        if len(revision_ids) != len(set(revision_ids)):
            raise ValueError("knowledge pack revisions must be unique")
        mapping_ids = [item.mapping_id for item in self.mappings]
        mapping_targets = [
            (item.document, item.path) for item in self.mappings
        ]
        if len(mapping_ids) != len(set(mapping_ids)):
            raise ValueError("knowledge mapping ids must be unique")
        if len(mapping_targets) != len(set(mapping_targets)):
            raise ValueError("knowledge mapping targets must be unique")
        if not {item.source_revision_id for item in self.mappings}.issubset(
            revision_ids
        ):
            raise ValueError("knowledge mapping references an unselected revision")
        if len(self.required_capabilities) != len(
            set(self.required_capabilities)
        ):
            raise ValueError("knowledge pack capabilities must be unique")
        forbidden_targets = [
            (item.document, item.path) for item in self.forbidden_fields
        ]
        if len(forbidden_targets) != len(set(forbidden_targets)):
            raise ValueError("knowledge pack forbidden fields must be unique")
        digest = stable_json_sha256(
            _knowledge_pack_identity_payload(
                revisions=self.revisions,
                target=self.target,
                target_schema_version=self.target_schema_version,
                required_capabilities=self.required_capabilities,
                mappings=self.mappings,
                forbidden_fields=self.forbidden_fields,
                created_by=self.created_by,
                created_at=self.created_at,
            )
        )
        if self.pack_sha256 != digest:
            raise ValueError("knowledge pack hash does not match its content")
        if self.pack_id != uuid5(_KNOWLEDGE_PACK_NAMESPACE, digest):
            raise ValueError("knowledge pack id is not deterministic")
        return self


def build_knowledge_pack_contract(
    *,
    revisions: tuple[KnowledgeRevisionRef, ...],
    target: KnowledgePackTarget,
    target_schema_version: str,
    required_capabilities: tuple[str, ...],
    mappings: tuple[KnowledgeMapping, ...],
    forbidden_fields: tuple[FieldLock, ...],
    created_by: str,
    created_at: datetime,
) -> KnowledgePack:
    ordered_revisions = tuple(
        sorted(revisions, key=lambda item: str(item.revision_id))
    )
    ordered_mappings = tuple(
        sorted(
            mappings,
            key=lambda item: (item.document.value, item.path, item.mapping_id),
        )
    )
    ordered_forbidden = tuple(
        sorted(
            forbidden_fields,
            key=lambda item: (item.document.value, item.path),
        )
    )
    ordered_capabilities = tuple(sorted(required_capabilities))
    digest = stable_json_sha256(
        _knowledge_pack_identity_payload(
            revisions=ordered_revisions,
            target=target,
            target_schema_version=target_schema_version,
            required_capabilities=ordered_capabilities,
            mappings=ordered_mappings,
            forbidden_fields=ordered_forbidden,
            created_by=created_by,
            created_at=created_at,
        )
    )
    return KnowledgePack(
        pack_id=uuid5(_KNOWLEDGE_PACK_NAMESPACE, digest),
        pack_sha256=digest,
        revisions=ordered_revisions,
        target=target,
        target_schema_version=target_schema_version,
        required_capabilities=ordered_capabilities,
        mappings=ordered_mappings,
        forbidden_fields=ordered_forbidden,
        created_by=created_by,
        created_at=created_at,
    )


class GenerationMode(StrEnum):
    T2V = "t2v"
    I2V = "i2v"
    FIRST_LAST_FRAME = "first_last_frame"


class ReferenceDutyKind(StrEnum):
    IDENTITY = "identity"
    MOTION = "motion"
    SCENE = "scene"
    COMPOSITION = "composition"


class ReferenceDuty(StrictFrozenModel):
    artifact: ArtifactRef
    duty: ReferenceDutyKind
    description: SafeText


class VideoResolution(StrictFrozenModel):
    width: int = Field(ge=256, le=8192)
    height: int = Field(ge=256, le=8192)

    @model_validator(mode="after")
    def dimensions_are_even(self):
        if self.width % 2 or self.height % 2:
            raise ValueError("video resolution dimensions must be even")
        return self


class GenerationRequestBase(StrictFrozenModel):
    project_revision_id: UUID
    scene_id: UUID
    clip_id: UUID
    run_id: UUID
    prompt_snapshot_id: UUID
    prompt_compiler_version: Identifier
    resolved_seed: int = Field(ge=1, le=2**63 - 1)
    seed_derivation_version: Identifier
    seed_input_hash: Sha256Digest
    attempt_index: NonNegativeInt
    duration_seconds: float = Field(gt=0, le=60)
    aspect_ratio: str = Field(pattern=r"^[1-9][0-9]?:[1-9][0-9]?$")
    resolution: VideoResolution
    audio_intent: SafeText
    reference_duties: tuple[ReferenceDuty, ...] = Field(default=(), max_length=16)
    reference_exclusions: tuple[SafeText, ...] = Field(default=(), max_length=32)
    model_id: Identifier
    capability_snapshot_id: UUID
    fallback_policy_snapshot_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    parent_run_id: UUID | None = None
    fallback_from_run_id: UUID | None = None

    @model_validator(mode="after")
    def references_have_unique_duties(self):
        duties = [reference.duty for reference in self.reference_duties]
        if len(duties) != len(set(duties)):
            raise ValueError("reference duties must be unique")
        if len(self.reference_exclusions) != len(set(self.reference_exclusions)):
            raise ValueError("reference exclusions must be unique")
        return self


class TextToVideoRequest(GenerationRequestBase):
    mode: Literal[GenerationMode.T2V] = GenerationMode.T2V


class ImageToVideoRequest(GenerationRequestBase):
    mode: Literal[GenerationMode.I2V] = GenerationMode.I2V
    first_image: ArtifactRef


class FirstLastFrameRequest(GenerationRequestBase):
    mode: Literal[GenerationMode.FIRST_LAST_FRAME] = (
        GenerationMode.FIRST_LAST_FRAME
    )
    first_image: ArtifactRef
    last_image: ArtifactRef

    @model_validator(mode="after")
    def endpoints_are_distinct(self):
        if self.first_image.artifact_id == self.last_image.artifact_id:
            raise ValueError("first and last frame artifacts must be distinct")
        return self


GenerationRequest = Annotated[
    TextToVideoRequest | ImageToVideoRequest | FirstLastFrameRequest,
    Field(discriminator="mode"),
]


class ModelCapability(StrictFrozenModel):
    capability_id: UUID
    model_id: Identifier
    operation: GenerationMode
    workflow_id: Identifier
    workflow_version: Identifier
    local_only: Literal[True] = True
    supported_resolutions: tuple[VideoResolution, ...] = Field(min_length=1)
    supported_durations_seconds: tuple[float, ...] = Field(min_length=1)
    supported_dtypes: tuple[str, ...] = Field(min_length=1)
    estimated_vram_mib: PositiveInt
    warm_load_cost_seconds: NonNegativeInt
    verified: bool
    snapshot_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_capability(self):
        if any(value <= 0 or value > 60 for value in self.supported_durations_seconds):
            raise ValueError("model capability duration is invalid")
        identity = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        if self.snapshot_sha256 != stable_json_sha256(identity):
            raise ValueError("model capability hash does not match its content")
        return self


class ModelSourceType(StrEnum):
    HUGGING_FACE = "hugging_face"
    COMFY_BUNDLE = "comfy_bundle"
    EXISTING_LOCAL = "existing_local"


class ModelInstallStatus(StrEnum):
    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    INSTALLED = "installed"
    FAILED = "failed"


class ModelVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    HASH_VERIFIED = "hash_verified"
    LOAD_VERIFIED = "load_verified"
    FAILED = "failed"


class ModelRegistryEntry(StrictFrozenModel):
    registry_entry_id: UUID
    model_id: Identifier
    display_name: SafeText
    source_url: str = Field(min_length=1, max_length=2000)
    source_type: ModelSourceType
    license_name: SafeText
    license_snapshot_sha256: Sha256Digest
    expected_size_bytes: PositiveInt | None = None
    artifact_sha256: Sha256Digest | None = None
    local_path: str | None = Field(default=None, max_length=2000)
    install_status: ModelInstallStatus
    verification_status: ModelVerificationStatus
    verified_at: AwareDatetime | None = None
    capability_ids: tuple[UUID, ...] = Field(min_length=1)
    compiler_profile: Identifier
    snapshot_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_registry_entry(self):
        if len(self.capability_ids) != len(set(self.capability_ids)):
            raise ValueError("model capability ids must be unique")
        installed = self.install_status is ModelInstallStatus.INSTALLED
        verified = self.verification_status in {
            ModelVerificationStatus.HASH_VERIFIED,
            ModelVerificationStatus.LOAD_VERIFIED,
        }
        if installed and not self.local_path:
            raise ValueError("installed model requires a local path")
        if verified and (
            not installed
            or not self.artifact_sha256
            or self.verified_at is None
        ):
            raise ValueError(
                "verified model requires installed artifact hash and time"
            )
        identity = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        if self.snapshot_sha256 != stable_json_sha256(identity):
            raise ValueError("model registry hash does not match its content")
        return self


class FallbackChange(StrEnum):
    MODEL = "model"
    RESOLUTION = "resolution"
    DURATION = "duration"


class FallbackPolicySnapshot(StrictFrozenModel):
    snapshot_id: UUID
    policy_version: PositiveInt
    default_block: Literal[True] = True
    allowed_changes: tuple[FallbackChange, ...] = ()
    fallback_model_ids: tuple[Identifier, ...] = ()
    fallback_resolutions: tuple[VideoResolution, ...] = ()
    created_by_actor: Identifier
    created_at: AwareDatetime
    snapshot_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_fallback_policy(self):
        if len(self.allowed_changes) != len(set(self.allowed_changes)):
            raise ValueError("fallback changes must be unique")
        if len(self.fallback_model_ids) != len(set(self.fallback_model_ids)):
            raise ValueError("fallback models must be unique")
        identity = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        if self.snapshot_sha256 != stable_json_sha256(identity):
            raise ValueError("fallback policy hash does not match its content")
        return self


class CloudDataType(StrEnum):
    TEXT = "text"
    TRANSCRIPT = "transcript"
    FRAMES = "frames"
    AUDIO = "audio"
    VIDEO = "video"


class CloudExecutionPolicySnapshot(StrictFrozenModel):
    snapshot_id: UUID
    project_id: UUID
    run_id: UUID
    policy_version: PositiveInt
    provider_allowlist: tuple[Identifier, ...] = ()
    allowed_data_types: tuple[CloudDataType, ...] = ()
    provider_retention_notice: SafeText | None = None
    consented_at: AwareDatetime | None = None
    created_by_actor: Identifier
    created_at: AwareDatetime
    snapshot_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_cloud_policy(self):
        if len(self.provider_allowlist) != len(set(self.provider_allowlist)):
            raise ValueError("cloud providers must be unique")
        if len(self.allowed_data_types) != len(set(self.allowed_data_types)):
            raise ValueError("cloud data types must be unique")
        if self.allowed_data_types and (
            not self.provider_allowlist
            or not self.provider_retention_notice
            or self.consented_at is None
        ):
            raise ValueError(
                "cloud data authorization requires provider, retention notice, "
                "and explicit consent time"
            )
        identity = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        if self.snapshot_sha256 != stable_json_sha256(identity):
            raise ValueError("cloud execution policy hash does not match content")
        return self


class ImportAction(StrEnum):
    ADD = "add"
    REPLACE = "replace"
    CONFLICT = "conflict"
    LOCKED = "locked"
    DISABLED = "disabled"
    UNCHANGED = "unchanged"


class ImportCompatibilityIssue(StrictFrozenModel):
    code: Identifier
    message: SafeText
    action: SafeText


class ImportOperation(StrictFrozenModel):
    mapping_id: Identifier
    source_revision_id: UUID
    document: FactoryDocument
    path: JsonPointer
    action: ImportAction
    current_exists: bool
    current_json: CanonicalJson | None = None
    incoming_json: CanonicalJson
    resolved_json: CanonicalJson | None = None
    reason: SafeText
    requires_resolution: bool = False

    @field_validator("current_json", "incoming_json", "resolved_json")
    @classmethod
    def values_must_be_canonical(cls, value: str | None) -> str | None:
        return None if value is None else _validate_canonical_json(value)

    @model_validator(mode="after")
    def current_state_is_consistent(self):
        if self.current_exists != (self.current_json is not None):
            raise ValueError("current field existence does not match current value")
        if self.action in {ImportAction.CONFLICT, ImportAction.LOCKED}:
            if not self.requires_resolution:
                raise ValueError("conflicting import operation requires resolution")
        elif self.requires_resolution:
            raise ValueError("non-conflicting import operation cannot require resolution")
        if self.action is ImportAction.CONFLICT and self.resolved_json is not None:
            raise ValueError("unresolved conflict cannot contain a resolved value")
        return self


def _import_plan_identity_payload(
    *,
    pack_id: UUID,
    pack_sha256: str,
    compiler_version: str,
    target_snapshot_sha256: str,
    compatible: bool,
    compatibility_issues: tuple[ImportCompatibilityIssue, ...],
    operations: tuple[ImportOperation, ...],
    resulting_locks: tuple[FieldLock, ...],
    ready_for_confirmation: bool,
) -> dict[str, JsonValue]:
    return {
        "pack_id": str(pack_id),
        "pack_sha256": pack_sha256,
        "compiler_version": compiler_version,
        "target_snapshot_sha256": target_snapshot_sha256,
        "compatible": compatible,
        "compatibility_issues": [
            item.model_dump(mode="json") for item in compatibility_issues
        ],
        "operations": [item.model_dump(mode="json") for item in operations],
        "resulting_locks": [
            item.model_dump(mode="json") for item in resulting_locks
        ],
        "ready_for_confirmation": ready_for_confirmation,
    }


class ImportPlan(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    plan_id: UUID
    plan_sha256: Sha256Digest
    pack_id: UUID
    pack_sha256: Sha256Digest
    compiler_version: Identifier
    target_snapshot_sha256: Sha256Digest
    compatible: bool
    compatibility_issues: tuple[ImportCompatibilityIssue, ...] = Field(
        default=(),
        max_length=256,
    )
    operations: tuple[ImportOperation, ...] = Field(
        min_length=1,
        max_length=100_000,
    )
    resulting_locks: tuple[FieldLock, ...] = Field(
        default=(),
        max_length=20_000,
    )
    ready_for_confirmation: bool

    @model_validator(mode="after")
    def validate_plan(self):
        if self.compatible == bool(self.compatibility_issues):
            raise ValueError("import compatibility does not match its issues")
        expected_ready = self.compatible and not any(
            item.requires_resolution for item in self.operations
        )
        if self.ready_for_confirmation != expected_ready:
            raise ValueError("import readiness does not match its operations")
        operation_ids = [item.mapping_id for item in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("import plan operations must be unique")
        digest = stable_json_sha256(
            _import_plan_identity_payload(
                pack_id=self.pack_id,
                pack_sha256=self.pack_sha256,
                compiler_version=self.compiler_version,
                target_snapshot_sha256=self.target_snapshot_sha256,
                compatible=self.compatible,
                compatibility_issues=self.compatibility_issues,
                operations=self.operations,
                resulting_locks=self.resulting_locks,
                ready_for_confirmation=self.ready_for_confirmation,
            )
        )
        if self.plan_sha256 != digest:
            raise ValueError("import plan hash does not match its content")
        if self.plan_id != uuid5(_IMPORT_PLAN_NAMESPACE, digest):
            raise ValueError("import plan id is not deterministic")
        return self


def build_import_plan(
    *,
    pack: KnowledgePack,
    compiler_version: str,
    target_snapshot_sha256: str,
    compatibility_issues: tuple[ImportCompatibilityIssue, ...],
    operations: tuple[ImportOperation, ...],
    resulting_locks: tuple[FieldLock, ...],
) -> ImportPlan:
    ordered_issues = tuple(
        sorted(compatibility_issues, key=lambda item: item.code)
    )
    ordered_operations = tuple(
        sorted(
            operations,
            key=lambda item: (item.document.value, item.path, item.mapping_id),
        )
    )
    ordered_locks = tuple(
        sorted(
            resulting_locks,
            key=lambda item: (item.document.value, item.path),
        )
    )
    compatible = not ordered_issues
    ready = compatible and not any(
        item.requires_resolution for item in ordered_operations
    )
    digest = stable_json_sha256(
        _import_plan_identity_payload(
            pack_id=pack.pack_id,
            pack_sha256=pack.pack_sha256,
            compiler_version=compiler_version,
            target_snapshot_sha256=target_snapshot_sha256,
            compatible=compatible,
            compatibility_issues=ordered_issues,
            operations=ordered_operations,
            resulting_locks=ordered_locks,
            ready_for_confirmation=ready,
        )
    )
    return ImportPlan(
        plan_id=uuid5(_IMPORT_PLAN_NAMESPACE, digest),
        plan_sha256=digest,
        pack_id=pack.pack_id,
        pack_sha256=pack.pack_sha256,
        compiler_version=compiler_version,
        target_snapshot_sha256=target_snapshot_sha256,
        compatible=compatible,
        compatibility_issues=ordered_issues,
        operations=ordered_operations,
        resulting_locks=ordered_locks,
        ready_for_confirmation=ready,
    )


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PROVIDER = "provider"
    TRANSIENT = "transient"
    INTERNAL = "internal"


class SafeError(StrictFrozenModel):
    error_code: Identifier
    category: ErrorCategory
    retryable: bool
    safe_message: SafeText
    action: SafeText
    stage: Identifier
    request_id: UUID


class JobEventType(StrEnum):
    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    CHECKPOINT = "checkpoint"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobEvent(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    event_id: UUID
    job_id: UUID
    request_id: UUID
    sequence: PositiveInt
    event_type: JobEventType
    occurred_at: AwareDatetime
    data: dict[str, JsonValue] = Field(default_factory=dict)


class LearningSourceKind(StrEnum):
    PROFILE = "profile"
    LINK = "link"
    LOCAL = "local"


_DOUYIN_SHARE_URL_PATTERN = re.compile(r'https://[^\s<>"\'`]+', re.IGNORECASE)
_DOUYIN_SHARE_TRAILING_PUNCTUATION = "，。！？、；：）】》}],.!?;:"


def extract_douyin_urls_from_share_text(value: str) -> tuple[str, ...]:
    """Extract canonical Douyin HTTPS URLs from user-visible share copy."""
    urls: list[str] = []
    for match in _DOUYIN_SHARE_URL_PATTERN.findall(value):
        candidate = match.rstrip(_DOUYIN_SHARE_TRAILING_PUNCTUATION)
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError:
            continue
        host = (parsed.hostname or "").rstrip(".").lower()
        if (
            parsed.scheme.lower() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port not in (None, 443)
            or (host != "douyin.com" and not host.endswith(".douyin.com"))
        ):
            continue
        normalized = urlunsplit(
            ("https", host, parsed.path or "/", parsed.query, "")
        )
        if normalized not in urls:
            urls.append(normalized)
    return tuple(urls)


class LearningSourceRequest(StrictFrozenModel):
    kind: LearningSourceKind
    sec_user_id: str | None = Field(default=None, min_length=1, max_length=255)
    urls: tuple[str, ...] = Field(default=(), max_length=100)
    share_text: str | None = Field(default=None, min_length=1, max_length=10_000)
    root_id: str | None = Field(default=None, min_length=1, max_length=128)
    relative_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
    )
    collect_comments: bool = False

    @model_validator(mode="before")
    @classmethod
    def populate_urls_from_share_text(cls, value):
        if not isinstance(value, dict):
            return value
        share_text = value.get("share_text")
        if share_text is None:
            return value
        if value.get("urls"):
            raise ValueError("link source cannot provide both urls and share_text")
        if not isinstance(share_text, str):
            return value
        normalized = dict(value)
        normalized["share_text"] = share_text.strip()
        normalized["urls"] = extract_douyin_urls_from_share_text(share_text)
        return normalized

    @field_validator("sec_user_id")
    @classmethod
    def normalize_sec_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("invalid sec_user_id")
        return cleaned

    @field_validator("urls")
    @classmethod
    def normalize_douyin_urls(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = []
        for value in values:
            if not value or any(
                ord(character) < 32 or ord(character) == 127
                for character in value
            ):
                raise ValueError("invalid Douyin URL")
            parsed = urlsplit(value)
            if (
                parsed.scheme.lower() != "https"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or parsed.port not in (None, 443)
            ):
                raise ValueError("invalid Douyin URL")
            host = (parsed.hostname or "").rstrip(".").lower()
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError("invalid Douyin URL")
            if host != "douyin.com" and not host.endswith(".douyin.com"):
                raise ValueError("invalid Douyin URL")
            normalized.append(
                urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
            )
        return tuple(normalized)

    @model_validator(mode="after")
    def exactly_one_source_shape(self) -> "LearningSourceRequest":
        if self.kind is LearningSourceKind.PROFILE:
            valid = (
                self.sec_user_id is not None
                and not self.urls
                and self.share_text is None
                and self.root_id is None
                and self.relative_path is None
            )
        elif self.kind is LearningSourceKind.LINK:
            valid = (
                bool(self.urls)
                and self.sec_user_id is None
                and self.root_id is None
                and self.relative_path is None
            )
        else:
            valid = (
                self.root_id is not None
                and self.relative_path is not None
                and self.sec_user_id is None
                and not self.urls
                and self.share_text is None
                and not self.collect_comments
            )
        if not valid:
            raise ValueError("source fields do not match source kind")
        return self


class LearningAnalysisRequest(StrictFrozenModel):
    media_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    force: bool = False

    @field_validator("media_ids")
    @classmethod
    def media_ids_must_be_unique(
        cls,
        values: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("media_ids must be unique")
        return values


class CapabilityHandshake(StrictFrozenModel):
    contract_version: ContractVersion = Field(default_factory=ContractVersion)
    component: ComponentName
    capabilities: tuple[CapabilityName, ...] = Field(min_length=1)
    generated_at: AwareDatetime

    @field_validator("capabilities")
    @classmethod
    def capabilities_must_be_unique(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value


CANONICAL_MODELS: tuple[type[BaseModel], ...] = (
    ContractVersion,
    EntityRef,
    ArtifactRef,
    TimelineEvidenceBundle,
    KnowledgeCard,
    KnowledgeRevision,
    KnowledgeReview,
    KnowledgePack,
    FactoryProjectSnapshot,
    ImportPlan,
    SafeError,
    JobEvent,
    LearningSourceRequest,
    LearningAnalysisRequest,
    CapabilityHandshake,
)
