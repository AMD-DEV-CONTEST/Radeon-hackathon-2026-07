from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import to_jsonable_python
from shared_contracts import (
    ArtifactRef,
    CloudExecutionPolicySnapshot,
    FallbackPolicySnapshot,
    GenerationRequest,
    ReferenceDuty,
    VideoResolution,
    stable_json_sha256,
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GenerationRunStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    SUBMITTED = "submitted"
    RUNNING = "running"
    MATERIALIZING = "materializing"
    CANDIDATE = "candidate"
    ELIGIBLE = "eligible"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_HUMAN = "needs_human"


class TakeEligibility(StrEnum):
    CANDIDATE = "candidate"
    ELIGIBLE = "eligible"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"


class HumanVerdict(StrEnum):
    KEEP = "keep"
    FIX_IN_POST = "fix_in_post"
    EDIT = "edit"
    REROLL = "reroll"
    REWRITE = "rewrite"


class HumanVerdictEvent(FrozenModel):
    event_id: UUID
    visual_take_id: UUID
    verdict: HumanVerdict
    actor_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=255)
    expected_canon_version: int = Field(ge=0)
    derived_run_id: UUID | None = None
    changed_variable: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=2000)
    created_at: AwareDatetime


class DeliveryEligibility(StrEnum):
    CANDIDATE = "candidate"
    ELIGIBLE = "eligible"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"


class FactoryQCVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_HUMAN = "needs_human"


FACTORY_QC_DIMENSION_IDS = (
    "technical_quality",
    "character_consistency",
    "scene_consistency",
    "motion_naturalness",
    "physical_plausibility",
    "lighting_readability",
    "subtitle_quality",
    "lipsync_quality",
    "audio_technical_quality",
)


class FactoryQCEvidenceSpan(FrozenModel):
    artifact_ref: ArtifactRef
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def time_range_is_valid(self):
        if (
            self.start_ms is not None
            and self.end_ms is not None
            and self.end_ms < self.start_ms
        ):
            raise ValueError("QC evidence end must not precede start")
        return self


class FactoryQCScore(FrozenModel):
    dimension_id: Literal[
        "technical_quality",
        "character_consistency",
        "scene_consistency",
        "motion_naturalness",
        "physical_plausibility",
        "lighting_readability",
        "subtitle_quality",
        "lipsync_quality",
        "audio_technical_quality",
    ]
    score: int | None = Field(default=None, ge=1, le=10)
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    na_reason: str | None = Field(default=None, min_length=1, max_length=500)
    evidence: tuple[FactoryQCEvidenceSpan, ...] = ()

    @model_validator(mode="after")
    def score_or_na(self):
        if self.score is None and self.na_reason is None:
            raise ValueError("N/A QC score requires a reason")
        if self.score is not None and self.na_reason is not None:
            raise ValueError("scored QC dimension cannot include an N/A reason")
        return self


class FactoryQCEvaluation(FrozenModel):
    evaluation_id: UUID
    subject_type: Literal["visual_take", "delivery_take"]
    subject_id: UUID
    rubric_id: Literal["ai-short-drama"] = "ai-short-drama"
    rubric_version: Literal[1] = 1
    evaluator_model: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=200)
    evidence_mode: Literal["full_video", "frames_only"]
    scores: tuple[FactoryQCScore, ...] = Field(min_length=9, max_length=9)
    verdict: FactoryQCVerdict
    attempts_exhausted: bool = False
    raw_response_ref: ArtifactRef | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_evaluation(self):
        dimensions = tuple(item.dimension_id for item in self.scores)
        if set(dimensions) != set(FACTORY_QC_DIMENSION_IDS):
            raise ValueError("factory QC must contain every rubric dimension once")
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("factory QC dimensions must be unique")
        if (
            self.subject_type == "visual_take"
            and self.evidence_mode == "frames_only"
        ):
            temporal = {
                "motion_naturalness",
                "physical_plausibility",
                "lipsync_quality",
                "audio_technical_quality",
            }
            if any(
                score.dimension_id in temporal and score.score is not None
                for score in self.scores
            ):
                raise ValueError(
                    "frames-only QC cannot score temporal or audio dimensions"
                )
        if (
            self.verdict is FactoryQCVerdict.NEEDS_HUMAN
            and not self.attempts_exhausted
        ):
            raise ValueError("NeedsHuman QC must exhaust automated attempts")
        if (
            self.verdict is FactoryQCVerdict.PASS
            and self.attempts_exhausted
        ):
            raise ValueError("passing QC cannot exhaust attempts")
        return self


class DirectorState(FrozenModel):
    directing_voice: str = Field(min_length=1, max_length=2000)
    narrative_spine: str = Field(min_length=1, max_length=4000)
    felt_intent: str = Field(min_length=1, max_length=1000)
    narrative_job: str = Field(min_length=1, max_length=1000)
    completed_beats: tuple[str, ...] = ()
    reserved_beats: tuple[str, ...] = ()
    primary_spend: Literal["identity", "motion", "scene"]
    planned_start_state: dict[str, Any] = Field(default_factory=dict)
    planned_end_state: dict[str, Any] = Field(default_factory=dict)
    accepted_observed_state: dict[str, Any] | None = None
    open_motion_vectors: tuple[str, ...] = ()
    chain_depth: int = Field(default=0, ge=0, le=3)
    reanchor_policy: Literal["block", "explicit", "fallback"] = "block"

    @model_validator(mode="after")
    def beats_do_not_overlap(self):
        overlap = set(self.completed_beats) & set(self.reserved_beats)
        if overlap:
            raise ValueError("completed and reserved beats must not overlap")
        return self


class ClipContract(FrozenModel):
    duration_seconds: float = Field(gt=0, le=60)
    aspect_ratio: str = Field(pattern=r"^[1-9][0-9]?:[1-9][0-9]?$")
    resolution: VideoResolution
    camera: str = Field(min_length=1, max_length=1000)
    motion: str = Field(min_length=1, max_length=1000)
    lighting: str = Field(min_length=1, max_length=1000)
    reference_duties: tuple[ReferenceDuty, ...] = ()
    exclusions: tuple[str, ...] = ()


class ProjectRevision(FrozenModel):
    project_id: UUID
    revision_id: UUID
    parent_revision_id: UUID | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    source_kind: Literal["native", "legacy_import"] = "native"
    source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Scene(FrozenModel):
    scene_id: UUID
    project_revision_id: UUID
    order: int = Field(ge=0)
    narrative_spine: str = Field(min_length=1, max_length=4000)
    continuity_state: dict[str, Any] = Field(default_factory=dict)
    reanchor_policy: Literal["block", "explicit", "fallback"] = "block"


class Clip(FrozenModel):
    clip_id: UUID
    scene_id: UUID
    order: int = Field(ge=0)
    felt_intent: str = Field(min_length=1, max_length=1000)
    narrative_job: str = Field(min_length=1, max_length=1000)
    reserved_beats: tuple[str, ...] = ()
    locks: tuple[str, ...] = ()
    contract: ClipContract
    director_state: DirectorState


class ProviderCheckpoint(FrozenModel):
    run_id: UUID
    instance_id: str = Field(min_length=1, max_length=100)
    gpu_id: str = Field(min_length=1, max_length=100)
    gpu_lease_id: UUID
    hub_job_lease_id: UUID
    submission_nonce: str = Field(min_length=16, max_length=128)
    client_id: str = Field(min_length=16, max_length=128)
    prompt_id: str | None = Field(default=None, max_length=255)
    workflow_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    submitted_at: AwareDatetime | None = None
    last_observed_state: str = Field(min_length=1, max_length=100)
    progress: dict[str, Any] = Field(default_factory=dict)


class GenerationRun(FrozenModel):
    run_id: UUID
    clip_id: UUID
    operation: str
    request: GenerationRequest
    fallback_policy: FallbackPolicySnapshot
    cloud_policy: CloudExecutionPolicySnapshot
    status: GenerationRunStatus
    attempt_index: int = Field(ge=0)
    reroll_index: int = Field(ge=0)
    changed_variable: str | None = Field(default=None, max_length=100)
    parent_run_id: UUID | None = None
    fallback_from_run_id: UUID | None = None
    prompt_version: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    safe_error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def request_identity_matches(self):
        if self.request.run_id != self.run_id:
            raise ValueError("generation request run id does not match run")
        if self.request.clip_id != self.clip_id:
            raise ValueError("generation request clip id does not match run")
        if self.request.attempt_index != self.attempt_index:
            raise ValueError("generation request attempt does not match run")
        if self.operation != self.request.mode.value:
            raise ValueError("generation operation does not match request mode")
        return self


class VisualTake(FrozenModel):
    visual_take_id: UUID
    run_id: UUID
    raw_video_ref: ArtifactRef
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_state: dict[str, Any]
    eligibility: TakeEligibility
    factory_qc_evaluation_id: UUID | None = None
    created_at: AwareDatetime


class LegacyImportedTake(FrozenModel):
    legacy_take_id: UUID
    clip_id: UUID
    source_shot_id: str = Field(min_length=1, max_length=255)
    keyframe_ref: ArtifactRef | None = None
    raw_video_ref: ArtifactRef | None = None
    final_video_ref: ArtifactRef | None = None
    voice_ref: ArtifactRef | None = None
    explicit_keyframe_seed: int | None = Field(default=None, ge=1)
    explicit_clip_seed: int | None = Field(default=None, ge=1)
    seed_status: Literal["explicit", "legacy_seed_unknown"]
    legacy_status: str = Field(min_length=1, max_length=100)
    legacy_qc: dict[str, Any] = Field(default_factory=dict)
    source_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    imported_at: AwareDatetime


class ContinuityAnchorAccepted(FrozenModel):
    event_id: UUID
    scene_id: UUID
    clip_id: UUID
    visual_take_id: UUID
    actor_id: str = Field(min_length=1, max_length=100)
    observed_state: dict[str, Any]
    accepted_at: AwareDatetime


class VisualCanonRevision(FrozenModel):
    scene_id: UUID
    canon_version: int = Field(ge=1)
    visual_take_id: UUID
    continuity_anchor_event_id: UUID
    previous_version: int | None = Field(default=None, ge=1)
    created_at: AwareDatetime


class SilencePolicyBinding(FrozenModel):
    role: Literal["ambience", "sfx", "music"]
    silence_policy_revision_id: UUID
    silence_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    maximum_silence_ms: int = Field(gt=0, le=70_000)


class DeliveryTake(FrozenModel):
    delivery_take_id: UUID
    visual_take_id: UUID
    visual_take_ids: tuple[UUID, ...] = ()
    trial_script_revision_id: UUID | None = None
    audio_alignment_revision_id: UUID | None = None
    audio_alignment_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    command_idempotency_key_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    delivery_request_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    tts_take_ids: tuple[UUID, ...] = ()
    tts_audio_refs: tuple[ArtifactRef, ...] = ()
    silence_policy_bindings: tuple[SilencePolicyBinding, ...] = ()
    audio_timeline_ref: ArtifactRef | None = None
    dialogue_ref: ArtifactRef | None = None
    ambience_ref: ArtifactRef | None = None
    sfx_ref: ArtifactRef | None = None
    music_ref: ArtifactRef | None = None
    subtitle_ref: ArtifactRef | None = None
    lipsync_video_ref: ArtifactRef | None = None
    final_composite_ref: ArtifactRef
    eligibility: DeliveryEligibility
    factory_qc_evaluation_id: UUID | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validates_shidu_audio_lineage(self):
        if self.trial_script_revision_id is None:
            return self
        if self.lipsync_video_ref is not None:
            raise ValueError("Shidu delivery must not include a lipsync artifact")
        if (
            self.audio_alignment_revision_id is None
            or self.audio_alignment_digest is None
            or self.command_idempotency_key_digest is None
            or self.delivery_request_digest is None
            or self.audio_timeline_ref is None
            or self.dialogue_ref is None
            or self.subtitle_ref is None
            or not self.tts_take_ids
            or len(self.tts_take_ids) != len(self.tts_audio_refs)
        ):
            raise ValueError("Shidu delivery requires exact audio lineage")
        if (
            len(self.visual_take_ids) != 6
            or len(set(self.visual_take_ids)) != 6
            or self.visual_take_ids[0] != self.visual_take_id
        ):
            raise ValueError(
                "Shidu delivery requires six ordered visual take ids"
            )
        if len(set(self.tts_take_ids)) != len(self.tts_take_ids):
            raise ValueError("Shidu TTS take ids must be unique")
        artifact_ids = [item.artifact_id for item in self.tts_audio_refs]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("Shidu TTS audio artifacts must be unique")
        silence_by_role = {
            item.role: item for item in self.silence_policy_bindings
        }
        if len(silence_by_role) != len(self.silence_policy_bindings):
            raise ValueError("Shidu silence policy roles must be unique")
        track_refs = {
            "ambience": self.ambience_ref,
            "sfx": self.sfx_ref,
            "music": self.music_ref,
        }
        if any(
            (track_refs[role] is None) == (role not in silence_by_role)
            for role in track_refs
        ):
            raise ValueError(
                "each Shidu final audio track requires artifact or silence policy"
            )
        return self


class DeliveryAccepted(FrozenModel):
    event_id: UUID
    project_id: UUID
    delivery_take_id: UUID
    actor_id: str = Field(min_length=1, max_length=100)
    accepted_at: AwareDatetime


class DeliveryRevision(FrozenModel):
    project_id: UUID
    delivery_version: int = Field(ge=1)
    delivery_take_id: UUID
    delivery_acceptance_event_id: UUID
    previous_version: int | None = Field(default=None, ge=1)
    created_at: AwareDatetime


class FactoryOutboxEvent(FrozenModel):
    event_id: UUID
    sequence: int = Field(ge=1)
    topic: str = Field(min_length=1, max_length=100)
    aggregate_id: UUID
    payload: dict[str, Any]
    created_at: AwareDatetime
    published_at: AwareDatetime | None = None


class FactoryProjectState(FrozenModel):
    schema_version: Literal["factory.project-state.v3"] = "factory.project-state.v3"
    state_version: int = Field(ge=0)
    project_revision: ProjectRevision
    scenes: tuple[Scene, ...]
    clips: tuple[Clip, ...]
    runs: tuple[GenerationRun, ...] = ()
    checkpoints: tuple[ProviderCheckpoint, ...] = ()
    legacy_imported_takes: tuple[LegacyImportedTake, ...] = ()
    visual_takes: tuple[VisualTake, ...] = ()
    continuity_acceptances: tuple[ContinuityAnchorAccepted, ...] = ()
    visual_canon_revisions: tuple[VisualCanonRevision, ...] = ()
    verdict_events: tuple[HumanVerdictEvent, ...] = ()
    delivery_takes: tuple[DeliveryTake, ...] = ()
    factory_qc_evaluations: tuple[FactoryQCEvaluation, ...] = ()
    delivery_acceptances: tuple[DeliveryAccepted, ...] = ()
    delivery_revisions: tuple[DeliveryRevision, ...] = ()
    outbox_events: tuple[FactoryOutboxEvent, ...] = ()
    updated_at: AwareDatetime
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "scenes",
        "clips",
        "runs",
        "checkpoints",
        "legacy_imported_takes",
        "visual_takes",
        "continuity_acceptances",
        "visual_canon_revisions",
        "verdict_events",
        "delivery_takes",
        "factory_qc_evaluations",
        "delivery_acceptances",
        "delivery_revisions",
        "outbox_events",
    )
    @classmethod
    def identities_are_unique(cls, values):
        if not values:
            return values
        identity_fields = {
            Scene: "scene_id",
            Clip: "clip_id",
            GenerationRun: "run_id",
            ProviderCheckpoint: "run_id",
            LegacyImportedTake: "legacy_take_id",
            VisualTake: "visual_take_id",
            ContinuityAnchorAccepted: "event_id",
            VisualCanonRevision: "canon_version",
            HumanVerdictEvent: "event_id",
            DeliveryTake: "delivery_take_id",
            FactoryQCEvaluation: "evaluation_id",
            DeliveryAccepted: "event_id",
            DeliveryRevision: "delivery_version",
            FactoryOutboxEvent: "event_id",
        }
        identity_field = identity_fields[type(values[0])]
        if type(values[0]) is VisualCanonRevision:
            identifiers = [
                (item.scene_id, item.canon_version)
                for item in values
            ]
        elif type(values[0]) is DeliveryRevision:
            identifiers = [
                (item.project_id, item.delivery_version)
                for item in values
            ]
        else:
            identifiers = [
                getattr(item, identity_field)
                for item in values
            ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("factory state identities must be unique")
        return values

    @model_validator(mode="after")
    def references_are_consistent(self):
        revision_id = self.project_revision.revision_id
        scene_by_id = {item.scene_id: item for item in self.scenes}
        clip_by_id = {item.clip_id: item for item in self.clips}
        run_by_id = {item.run_id: item for item in self.runs}
        visual_by_id = {
            item.visual_take_id: item for item in self.visual_takes
        }
        continuity_by_id = {
            item.event_id: item for item in self.continuity_acceptances
        }
        delivery_by_id = {
            item.delivery_take_id: item for item in self.delivery_takes
        }
        factory_qc_by_id = {
            item.evaluation_id: item
            for item in self.factory_qc_evaluations
        }
        delivery_acceptance_by_id = {
            item.event_id: item for item in self.delivery_acceptances
        }

        if any(
            scene.project_revision_id != revision_id
            for scene in self.scenes
        ):
            raise ValueError("scene references a different project revision")
        if any(clip.scene_id not in scene_by_id for clip in self.clips):
            raise ValueError("clip references an unavailable scene")
        for run in self.runs:
            clip = clip_by_id.get(run.clip_id)
            if (
                clip is None
                or run.request.project_revision_id != revision_id
                or run.request.scene_id != clip.scene_id
            ):
                raise ValueError(
                    "generation run references unavailable project state"
                )
            if (
                run.parent_run_id is not None
                and run.parent_run_id not in run_by_id
            ):
                raise ValueError(
                    "derived generation run references unavailable parent"
                )
        if any(
            checkpoint.run_id not in run_by_id
            for checkpoint in self.checkpoints
        ):
            raise ValueError("provider checkpoint references unavailable run")
        if any(
            take.clip_id not in clip_by_id
            for take in self.legacy_imported_takes
        ):
            raise ValueError("legacy take references unavailable clip")
        if any(
            take.run_id not in run_by_id
            for take in self.visual_takes
        ):
            raise ValueError("visual take references unavailable run")

        for acceptance in self.continuity_acceptances:
            take = visual_by_id.get(acceptance.visual_take_id)
            run = None if take is None else run_by_id.get(take.run_id)
            clip = None if run is None else clip_by_id.get(run.clip_id)
            if (
                take is None
                or clip is None
                or clip.clip_id != acceptance.clip_id
                or clip.scene_id != acceptance.scene_id
            ):
                raise ValueError(
                    "continuity acceptance references inconsistent take"
                )
        canon_versions: dict[UUID, list[int]] = {}
        for revision in self.visual_canon_revisions:
            take = visual_by_id.get(revision.visual_take_id)
            acceptance = continuity_by_id.get(
                revision.continuity_anchor_event_id
            )
            if (
                take is None
                or acceptance is None
                or acceptance.visual_take_id != revision.visual_take_id
                or acceptance.scene_id != revision.scene_id
                or take.eligibility is not TakeEligibility.ACCEPTED
            ):
                raise ValueError(
                    "visual canon references an unaccepted visual take"
                )
            canon_versions.setdefault(revision.scene_id, []).append(
                revision.canon_version
            )
            expected_previous = (
                None
                if revision.canon_version == 1
                else revision.canon_version - 1
            )
            if revision.previous_version != expected_previous:
                raise ValueError("visual canon history is not contiguous")
        if any(
            sorted(versions) != list(range(1, len(versions) + 1))
            for versions in canon_versions.values()
        ):
            raise ValueError("visual canon versions are not contiguous")

        for event in self.verdict_events:
            if event.visual_take_id not in visual_by_id:
                raise ValueError("verdict references unavailable visual take")
            if (
                event.derived_run_id is not None
                and event.derived_run_id not in run_by_id
            ):
                raise ValueError("verdict references unavailable derived run")
        if any(
            take.visual_take_id not in visual_by_id
            or any(
                visual_take_id not in visual_by_id
                or visual_by_id[visual_take_id].eligibility
                is not TakeEligibility.ACCEPTED
                for visual_take_id in take.visual_take_ids
            )
            for take in self.delivery_takes
        ):
            raise ValueError("delivery take references unavailable visual take")
        for evaluation in self.factory_qc_evaluations:
            if evaluation.subject_type == "visual_take":
                subject = visual_by_id.get(evaluation.subject_id)
            else:
                subject = delivery_by_id.get(evaluation.subject_id)
            if subject is None:
                raise ValueError("factory QC references unavailable take")
            if subject.factory_qc_evaluation_id != evaluation.evaluation_id:
                raise ValueError("factory QC is not bound to its subject take")
        for take in self.visual_takes:
            if (
                take.factory_qc_evaluation_id is not None
                and take.factory_qc_evaluation_id not in factory_qc_by_id
            ):
                raise ValueError("visual take QC result is unavailable")
        for take in self.delivery_takes:
            if (
                take.factory_qc_evaluation_id is not None
                and take.factory_qc_evaluation_id not in factory_qc_by_id
            ):
                raise ValueError("delivery take QC result is unavailable")
        for acceptance in self.delivery_acceptances:
            if (
                acceptance.project_id != self.project_revision.project_id
                or acceptance.delivery_take_id not in delivery_by_id
            ):
                raise ValueError(
                    "delivery acceptance references unavailable take"
                )
        for revision in self.delivery_revisions:
            take = delivery_by_id.get(revision.delivery_take_id)
            acceptance = delivery_acceptance_by_id.get(
                revision.delivery_acceptance_event_id
            )
            if (
                revision.project_id != self.project_revision.project_id
                or take is None
                or take.eligibility is not DeliveryEligibility.ACCEPTED
                or acceptance is None
                or acceptance.delivery_take_id != revision.delivery_take_id
            ):
                raise ValueError(
                    "delivery revision references an unaccepted take"
                )
            expected_previous = (
                None
                if revision.delivery_version == 1
                else revision.delivery_version - 1
            )
            if revision.previous_version != expected_previous:
                raise ValueError("delivery history is not contiguous")
        delivery_versions = sorted(
            item.delivery_version for item in self.delivery_revisions
        )
        if delivery_versions != list(
            range(1, len(delivery_versions) + 1)
        ):
            raise ValueError("delivery versions are not contiguous")

        sequences = [item.sequence for item in self.outbox_events]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError(
                "factory outbox sequences must be ordered and contiguous"
            )
        return self

    @model_validator(mode="after")
    def validate_state_hash(self, info: ValidationInfo):
        if isinstance(info.context, dict) and info.context.get("skip_state_hash"):
            return self
        identity = self.model_dump(mode="json", exclude={"state_sha256"})
        if self.state_sha256 != stable_json_sha256(identity):
            raise ValueError("factory project state hash does not match content")
        return self


def with_state_hash(payload: dict[str, Any]) -> FactoryProjectState:
    payload = dict(payload)
    payload.pop("state_sha256", None)
    normalized = to_jsonable_python(payload)
    normalized["state_sha256"] = "0" * 64
    draft = FactoryProjectState.model_validate(
        normalized,
        context={"skip_state_hash": True},
    )
    identity = draft.model_dump(mode="json", exclude={"state_sha256"})
    identity["state_sha256"] = stable_json_sha256(identity)
    return FactoryProjectState.model_validate(identity)
