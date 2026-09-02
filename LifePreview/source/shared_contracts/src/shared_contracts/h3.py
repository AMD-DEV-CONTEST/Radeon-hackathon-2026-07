from __future__ import annotations

import hmac
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)
from pydantic_core import to_jsonable_python

from .character_reference import CharacterReferenceSetV1
from .models import StrictFrozenModel, stable_json_sha256


Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
Identifier = Annotated[
    str,
    Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
UnitScore = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
AttemptOrdinal = Annotated[int, Field(ge=0, le=1)]

H3_PRODUCT_CONTRACT_VERSIONS = {
    "project_creative_ir": "project.creative.ir.v1",
    "character_reference_set": "character.reference-set.v1",
    "episode_generation_ir": "episode.generation.ir.v1",
    "h3_sequence": "h3.sequence.v1",
    "h3_attempt_selection": "h3.attempt-selection.v1",
    "h3_delivery": "h3.delivery.v1",
}


def h3_contract_digest(value: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 identity for an H3 contract payload."""

    return stable_json_sha256(dict(value))  # type: ignore[arg-type]


class H3GenerationMode(StrEnum):
    REF2VA = "ref2va"


class H3SelectedResonanceV1(StrictFrozenModel):
    resonance_id: Identifier
    revision_id: UUID
    label: ShortText
    source_pack_revision_id: UUID


class H3NarratorLockV1(StrictFrozenModel):
    narrator_id: Identifier
    voice_source: Literal["h3_native"]
    disclosure: ShortText


class H3SubjectV1(StrictFrozenModel):
    subject_id: Identifier
    character_id: Identifier
    age_stage: Identifier


class H3CharacterReferenceRequirementV1(StrictFrozenModel):
    character_id: Identifier
    age_stage: Identifier
    views_required: tuple[
        Literal["front"],
        Literal["three_quarter_left"],
        Literal["profile_left"],
    ]


class H3ScenePlanV1(StrictFrozenModel):
    scene_number: Annotated[int, Field(ge=1)]
    location: ShortText
    interior_exterior: Literal["interior", "exterior"]
    day_night: Literal["day", "night"]
    subject_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=100)
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=500)
    resonance_role: ShortText
    narration_intent: ShortText
    target_duration_seconds: Annotated[
        float,
        Field(gt=0.0, le=90.0, allow_inf_nan=False),
    ]

    @model_validator(mode="after")
    def validate_scene_plan(self) -> H3ScenePlanV1:
        if len(self.subject_ids) != len(set(self.subject_ids)):
            raise ValueError("scene subject ids must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("scene evidence ids must be unique")
        return self


class H3CreativeModelTraceV1(StrictFrozenModel):
    primary: Identifier
    fallback: Identifier | None = None


class H3EpisodeModelTraceV1(StrictFrozenModel):
    episode_router: Identifier
    fallback: Identifier | None = None


class ProjectCreativeIRV1(StrictFrozenModel):
    project_id: UUID
    source_document_revision_ids: tuple[UUID, ...] = Field(
        min_length=1,
        max_length=1_000,
    )
    evidence_pack_revision_id: UUID
    selected_resonance: H3SelectedResonanceV1
    trial_script_revision_id: UUID
    narrator_lock: H3NarratorLockV1
    subjects: tuple[H3SubjectV1, ...] = Field(min_length=1, max_length=100)
    character_reference_requirements: tuple[
        H3CharacterReferenceRequirementV1, ...
    ] = Field(
        min_length=1,
        max_length=100,
    )
    scene_plans: tuple[H3ScenePlanV1, ...] = Field(min_length=1, max_length=500)
    target_duration_seconds: Literal[90]
    aspect_ratio: Literal["16:9"]
    narrative_point_of_view: Literal["first_person"]
    creative_model_trace: H3CreativeModelTraceV1
    revision_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_revision_digest(self) -> ProjectCreativeIRV1:
        if len(self.source_document_revision_ids) != len(
            set(self.source_document_revision_ids)
        ):
            raise ValueError("source document revision ids must be unique")
        subject_ids = tuple(subject.subject_id for subject in self.subjects)
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("project subject ids must be unique")
        subject_character_keys = tuple(
            (subject.character_id, subject.age_stage)
            for subject in self.subjects
        )
        if len(subject_character_keys) != len(set(subject_character_keys)):
            raise ValueError(
                "project subjects must map uniquely to character references"
            )
        requirement_keys = tuple(
            (requirement.character_id, requirement.age_stage)
            for requirement in self.character_reference_requirements
        )
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("character reference requirements must be unique")
        if set(subject_character_keys) != set(requirement_keys):
            raise ValueError(
                "project subjects and character reference requirements must match"
            )
        declared_subject_ids = set(subject_ids)
        if any(
            subject_id not in declared_subject_ids
            for scene in self.scene_plans
            for subject_id in scene.subject_ids
        ):
            raise ValueError("scene subject ids must be declared by the project")
        scene_numbers = tuple(scene.scene_number for scene in self.scene_plans)
        if scene_numbers != tuple(range(1, len(scene_numbers) + 1)):
            raise ValueError("scene numbers must be contiguous from 1")
        identity = self.model_dump(mode="json", exclude={"revision_digest"})
        actual = h3_contract_digest(identity)
        if not hmac.compare_digest(actual, self.revision_digest):
            raise ValueError("project revision digest mismatch")
        return self


class H3ShotV1(StrictFrozenModel):
    shot_ordinal: Annotated[int, Field(ge=1)]
    start_seconds: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    end_seconds: Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
    framing: ShortText
    camera_move: ShortText
    subject_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=100)
    action: ShortText
    expression: ShortText

    @model_validator(mode="after")
    def validate_time_window(self) -> H3ShotV1:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("shot end must be after shot start")
        if len(self.subject_ids) != len(set(self.subject_ids)):
            raise ValueError("shot subject ids must be unique")
        return self


_SPEECH_UNIT_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9]+")


def estimate_h3_speech_seconds(text: str) -> float:
    """Estimate native H3 Mandarin speech time using a stable text-only rule."""

    units = _SPEECH_UNIT_PATTERN.findall(text)
    weighted_units = sum(1 if len(unit) == 1 else max(1, len(unit) // 4) for unit in units)
    return round(max(0.25, weighted_units / 14.0), 6)


class H3SpeechWindowV1(StrictFrozenModel):
    text: Annotated[str, Field(min_length=1, max_length=2_000)]
    start_seconds: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    end_seconds: Annotated[float, Field(gt=0.0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def validate_speech_window(self) -> H3SpeechWindowV1:
        available = self.end_seconds - self.start_seconds
        if available <= 0:
            raise ValueError("speech window end must be after start")
        required = estimate_h3_speech_seconds(self.text)
        if available + 1e-9 < required:
            raise ValueError(
                f"speech window is too short: requires {required:.3f} seconds"
            )
        return self


class H3ActionSoundV1(StrictFrozenModel):
    role: Literal["overlay"]
    label: ShortText
    start_seconds: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    end_seconds: Annotated[float, Field(gt=0.0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def validate_time_window(self) -> H3ActionSoundV1:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("overlay sound end must be after start")
        return self


class H3AudioPlanV1(StrictFrozenModel):
    voice_source: Literal["h3_native"]
    base_ambience: Annotated[str, Field(min_length=1, max_length=500)]
    tail_guard_seconds: Annotated[
        float,
        Field(gt=0.0, allow_inf_nan=False),
    ]
    narration: H3SpeechWindowV1
    action_sounds: tuple[H3ActionSoundV1, ...] = Field(default=(), max_length=100)
    internal_cut_times: tuple[
        Annotated[float, Field(gt=0.0, allow_inf_nan=False)], ...
    ] = Field(default=(), max_length=100)

    @field_validator("internal_cut_times")
    @classmethod
    def cuts_are_ordered_and_unique(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if tuple(sorted(value)) != value or len(value) != len(set(value)):
            raise ValueError("internal cut times must be strictly ordered")
        return value


class H3AudioSafetyError(ValueError):
    """Raised when a native H3 narration window is unsafe for delivery."""


def validate_h3_audio_safety(
    audio_plan: H3AudioPlanV1,
    *,
    sequence_duration_seconds: float,
) -> None:
    if not math.isfinite(sequence_duration_seconds) or sequence_duration_seconds <= 0:
        raise H3AudioSafetyError("sequence duration must be positive")
    narration = audio_plan.narration
    if narration.start_seconds < 0.5:
        raise H3AudioSafetyError("speech lead-in must be at least 0.5 seconds")
    if narration.end_seconds > sequence_duration_seconds - audio_plan.tail_guard_seconds:
        raise H3AudioSafetyError(
            "speech tail is shorter than the configured tail guard"
        )
    if narration.end_seconds > sequence_duration_seconds:
        raise H3AudioSafetyError("speech exceeds sequence duration")
    for cut in audio_plan.internal_cut_times:
        if cut >= sequence_duration_seconds:
            raise H3AudioSafetyError("internal cut exceeds sequence duration")
        if narration.start_seconds < cut < narration.end_seconds:
            raise H3AudioSafetyError("speech cannot cross an internal cut")
    for sound in audio_plan.action_sounds:
        if sound.end_seconds > sequence_duration_seconds:
            raise H3AudioSafetyError("overlay sound exceeds sequence duration")


class H3SourceLineageV1(StrictFrozenModel):
    attempt_ordinal: AttemptOrdinal
    artifact_digest: Sha256Digest
    qc_evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=100)
    repair_trigger_codes: tuple[Identifier, ...] = Field(default=(), max_length=100)
    generated_at: AwareDatetime

    @field_validator("qc_evidence_ids", "repair_trigger_codes")
    @classmethod
    def identifiers_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("lineage identifiers must be unique")
        return value


class H3ReferenceBindingV1(StrictFrozenModel):
    subject_id: Identifier
    reference_set: CharacterReferenceSetV1

    @model_validator(mode="after")
    def require_frozen_reference_set(self) -> H3ReferenceBindingV1:
        if self.reference_set.state != "frozen":
            raise ValueError("H3 reference binding requires a frozen reference set")
        return self


class H3SequencePlanV1(StrictFrozenModel):
    sequence_id: UUID
    ordinal: Annotated[int, Field(ge=1)]
    mode: Literal[H3GenerationMode.REF2VA]
    frame_count: Annotated[int, Field(ge=73, le=362)]
    fps: Literal[24]
    duration_seconds: Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
    requested_duration_seconds: Annotated[
        float,
        Field(ge=3.0, le=15.0, allow_inf_nan=False),
    ]
    reference_bindings: tuple[H3ReferenceBindingV1, ...] = Field(
        min_length=1,
        max_length=100,
    )
    shots: tuple[H3ShotV1, ...] = Field(min_length=1, max_length=2)
    audio_plan: H3AudioPlanV1
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_sequence(self) -> H3SequencePlanV1:
        if self.frame_count % 17 != 5:
            raise ValueError("frame count must satisfy the H3 17n+5 grid")
        expected_duration = self.frame_count / self.fps
        if not math.isclose(
            self.duration_seconds,
            expected_duration,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("duration must equal frame count divided by fps")
        required_frames = math.ceil(
            self.requested_duration_seconds * self.fps - 1e-12
        )
        expected_frame_count = required_frames + (
            (5 - required_frames) % 17
        )
        if self.frame_count != expected_frame_count:
            raise ValueError(
                "frame count must be the upward snap of requested duration"
            )
        reference_set_ids = tuple(
            binding.reference_set.reference_set_id
            for binding in self.reference_bindings
        )
        if len(reference_set_ids) != len(set(reference_set_ids)):
            raise ValueError("reference bindings must use unique reference sets")
        binding_subject_ids = tuple(
            binding.subject_id for binding in self.reference_bindings
        )
        if len(binding_subject_ids) != len(set(binding_subject_ids)):
            raise ValueError("reference binding subject ids must be unique")
        shot_subject_ids = {
            subject_id
            for shot in self.shots
            for subject_id in shot.subject_ids
        }
        if set(binding_subject_ids) != shot_subject_ids:
            raise ValueError(
                "shot subjects must exactly match reference binding subjects"
            )
        expected_ordinals = tuple(range(1, len(self.shots) + 1))
        if tuple(shot.shot_ordinal for shot in self.shots) != expected_ordinals:
            raise ValueError("shot ordinals must be contiguous from 1")
        if not math.isclose(self.shots[0].start_seconds, 0.0, abs_tol=1e-9):
            raise ValueError("first shot must start at sequence start")
        if not math.isclose(
            self.shots[-1].end_seconds,
            self.duration_seconds,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("final shot must end at sequence duration")
        for previous, current in zip(self.shots, self.shots[1:]):
            if not math.isclose(
                previous.end_seconds,
                current.start_seconds,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError("shots must form a contiguous sequence")
        expected_cuts = tuple(shot.end_seconds for shot in self.shots[:-1])
        actual_cuts = self.audio_plan.internal_cut_times
        if len(actual_cuts) != len(expected_cuts) or any(
            not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
            for actual, expected in zip(actual_cuts, expected_cuts)
        ):
            raise ValueError("audio cuts must equal the real shot boundaries")
        validate_h3_audio_safety(
            self.audio_plan,
            sequence_duration_seconds=self.duration_seconds,
        )
        return self


def h3_sequence_compilation_identity(
    value: H3SequencePlanV1 | H3SequenceV1 | Mapping[str, Any],
) -> dict[str, JsonValue]:
    """Return the logical compiler input without compiler-output digests."""

    if isinstance(value, H3SequencePlanV1):
        source: Any = value.model_dump(mode="json")
    elif isinstance(value, H3SequenceV1):
        source = value.plan.model_dump(mode="json")
    elif isinstance(value, Mapping):
        mapping = dict(value)
        source = mapping["plan"] if "plan" in mapping else mapping
    else:
        raise TypeError("H3 sequence compilation identity requires a sequence or mapping")

    # A JSON round trip both normalizes UUID/datetime/model values and guarantees
    # that no mutable container in the returned identity aliases the caller input.
    normalized = to_jsonable_python(source)
    identity = json.loads(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    if not isinstance(identity, dict):
        raise TypeError("H3 sequence compilation identity must be a JSON object")
    for runtime_field in (
        "prompt_digest",
        "workflow_digest",
        "initial_attempt",
        "repair_attempt",
        "selection_policy_revision",
        "selection",
        "state",
    ):
        identity.pop(runtime_field, None)
    return identity


class EpisodeGenerationIRV1(StrictFrozenModel):
    episode_revision_id: UUID
    project_ir_id: UUID
    project_ir_revision_digest: Sha256Digest
    project_ir: ProjectCreativeIRV1
    reference_set_revision_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    model_family: Literal["minimax-h3"]
    sequence_plans: tuple[H3SequencePlanV1, ...] = Field(
        min_length=1,
        max_length=100,
    )
    duration_allocation_digest: Sha256Digest
    model_trace: H3EpisodeModelTraceV1
    revision_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_episode(self) -> EpisodeGenerationIRV1:
        if self.project_ir_id != self.project_ir.project_id:
            raise ValueError("episode project IR id does not match embedded project IR")
        if self.project_ir_revision_digest != self.project_ir.revision_digest:
            raise ValueError(
                "episode project IR digest does not match embedded project IR"
            )
        if len(self.reference_set_revision_ids) != len(
            set(self.reference_set_revision_ids)
        ):
            raise ValueError("reference set revision ids must be unique")
        sequence_ids = tuple(
            sequence.sequence_id for sequence in self.sequence_plans
        )
        if len(sequence_ids) != len(set(sequence_ids)):
            raise ValueError("episode sequence ids must be unique")
        bound_reference_ids: list[UUID] = []
        subjects_by_id = {
            subject.subject_id: subject for subject in self.project_ir.subjects
        }
        for sequence in self.sequence_plans:
            for binding in sequence.reference_bindings:
                subject = subjects_by_id.get(binding.subject_id)
                reference_set = binding.reference_set
                if subject is None or (
                    subject.character_id != reference_set.character_id
                    or subject.age_stage != reference_set.age_stage
                ):
                    raise ValueError(
                        "reference binding does not match project subject authority"
                    )
                revision_id = reference_set.reference_set_revision_id
                if revision_id not in bound_reference_ids:
                    bound_reference_ids.append(revision_id)
        if self.reference_set_revision_ids != tuple(bound_reference_ids):
            raise ValueError(
                "episode reference declarations must exactly match sequence references"
            )
        identity = self.model_dump(mode="json", exclude={"revision_digest"})
        actual = h3_contract_digest(identity)
        if not hmac.compare_digest(actual, self.revision_digest):
            raise ValueError("episode revision digest mismatch")
        return self


class H3CandidateScoreV1(StrictFrozenModel):
    sequence_id: UUID
    attempt_ordinal: AttemptOrdinal
    media_integrity: UnitScore
    identity_and_semantics: UnitScore
    technical_quality: UnitScore
    aesthetic_quality: UnitScore
    exception_codes: tuple[Identifier, ...] = Field(default=(), max_length=100)

    @field_validator("exception_codes")
    @classmethod
    def exception_codes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("exception codes must be unique")
        return value

    def score_vector(self) -> tuple[float, float, float, float]:
        return (
            self.media_integrity,
            self.identity_and_semantics,
            self.technical_quality,
            self.aesthetic_quality,
        )


class H3QCDefectEvidenceV1(StrictFrozenModel):
    defect_code: Identifier
    severity: Literal["CRITICAL", "MAJOR", "MINOR"]
    message: ShortText
    time_range_ms: tuple[
        Annotated[int, Field(ge=0, le=16_000)],
        Annotated[int, Field(ge=0, le=16_000)],
    ] | None = None
    evidence_refs: tuple[Identifier, ...] = Field(min_length=1, max_length=100)
    recommended_repair_action: ShortText

    @model_validator(mode="after")
    def validate_defect_evidence(self) -> H3QCDefectEvidenceV1:
        if self.time_range_ms is not None:
            start_ms, end_ms = self.time_range_ms
            if end_ms <= start_ms:
                raise ValueError("defect evidence end must be after start")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("defect evidence references must be unique")
        return self


class H3AttemptQCEvidenceV1(StrictFrozenModel):
    evaluation_id: UUID
    project_id: UUID
    workflow_run_id: UUID
    stage: Literal["clip"]
    gate_key: Identifier
    sequence_id: UUID
    attempt_ordinal: AttemptOrdinal
    artifact_id: UUID
    artifact_digest: Sha256Digest
    artifact_operation_run_id: UUID
    artifact_operation_attempt_id: UUID
    qc_policy_revision: Literal["h3.audiovisual-qc.v1"]
    policy_snapshot_id: UUID
    policy_snapshot_digest: Sha256Digest
    evidence_pack_id: UUID
    evidence_pack_digest: Sha256Digest
    prompt_key: Literal["h3.audiovisual-qc"]
    prompt_text: Literal[
        "按固定 H3 音画规则检查候选片段并返回结构化证据。"
    ]
    prompt_revision_id: UUID
    prompt_digest: Sha256Digest
    rubric_revision_id: Literal["h3.audiovisual-qc-rubric.v1"]
    rubric_digest: Sha256Digest
    evaluator_name: Literal["zhipu/glm-4.6v+local"]
    evaluator_version: Literal["h3-audiovisual-qc.v1"]
    evaluator_bundle_digest: Sha256Digest
    implementation_digest: Sha256Digest
    candidate: H3CandidateScoreV1
    defects: tuple[H3QCDefectEvidenceV1, ...] = Field(default=(), max_length=100)
    confidence: UnitScore
    evaluated_at: AwareDatetime
    evidence_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_qc_evidence(self) -> H3AttemptQCEvidenceV1:
        if self.candidate.sequence_id != self.sequence_id:
            raise ValueError("QC candidate sequence does not match evidence sequence")
        if self.candidate.attempt_ordinal != self.attempt_ordinal:
            raise ValueError("QC candidate attempt does not match evidence attempt")
        defect_codes = tuple(defect.defect_code for defect in self.defects)
        if len(defect_codes) != len(set(defect_codes)):
            raise ValueError("QC defect codes must be unique")
        if defect_codes != self.candidate.exception_codes:
            raise ValueError("QC defect codes must exactly match candidate exceptions")
        identity = self.model_dump(mode="json", exclude={"evidence_digest"})
        actual = h3_contract_digest(identity)
        if not hmac.compare_digest(actual, self.evidence_digest):
            raise ValueError("QC evidence digest mismatch")
        return self


class H3AttemptSelectionV1(StrictFrozenModel):
    sequence_id: UUID
    candidates: tuple[H3CandidateScoreV1, ...] = Field(min_length=1, max_length=2)
    selected_attempt_ordinal: AttemptOrdinal
    selected_cleanly: bool
    selected_with_qc_exception: bool
    exception_codes: tuple[Identifier, ...] = Field(default=(), max_length=100)
    qc_policy_revision: Literal["h3.selection.v1"]
    selected_at: AwareDatetime
    selection_reason: ShortText
    selection_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_selection(self) -> H3AttemptSelectionV1:
        _validate_candidate_set(self.candidates, self.sequence_id)
        selected = _winning_candidate(self.candidates)
        if self.selected_attempt_ordinal != selected.attempt_ordinal:
            raise ValueError("selected attempt does not match deterministic ranking")
        clean = not selected.exception_codes
        if self.selected_cleanly != clean:
            raise ValueError("clean selection flag does not match exception codes")
        if self.selected_with_qc_exception == clean:
            raise ValueError("QC exception selection flag is inconsistent")
        if self.exception_codes != selected.exception_codes:
            raise ValueError("selection exception codes do not match candidate")
        identity = self.model_dump(mode="json", exclude={"selection_digest"})
        actual = h3_contract_digest(identity)
        if not hmac.compare_digest(actual, self.selection_digest):
            raise ValueError("selection digest mismatch")
        return self


class H3SequenceV1(StrictFrozenModel):
    plan: H3SequencePlanV1
    prompt_digest: Sha256Digest
    workflow_digest: Sha256Digest
    initial_attempt: H3SourceLineageV1
    repair_attempt: H3SourceLineageV1 | None = None
    selection_policy_revision: Literal["h3.selection.v1"]
    selection: H3AttemptSelectionV1 | None = None
    state: Literal["generated", "selected", "delivered"]

    @model_validator(mode="after")
    def validate_runtime_sequence(self) -> H3SequenceV1:
        if self.initial_attempt.attempt_ordinal != 0:
            raise ValueError("initial attempt ordinal must be 0")
        if self.initial_attempt.repair_trigger_codes:
            raise ValueError("initial attempt cannot have repair trigger codes")
        available_attempt_ordinals = (0,)
        if self.repair_attempt is not None:
            if self.repair_attempt.attempt_ordinal != 1:
                raise ValueError("repair attempt ordinal must be 1")
            if not self.repair_attempt.repair_trigger_codes:
                raise ValueError("repair attempt requires a trigger code")
            available_attempt_ordinals = (0, 1)

        if self.state == "generated":
            if self.selection is not None:
                raise ValueError("generated sequence cannot carry a selection")
            return self

        if self.selection is None:
            raise ValueError("selected or delivered sequence requires a selection")
        if self.selection.sequence_id != self.plan.sequence_id:
            raise ValueError("selection sequence id must match the sequence plan")
        selected_candidate_ordinals = tuple(
            sorted(candidate.attempt_ordinal for candidate in self.selection.candidates)
        )
        if selected_candidate_ordinals != available_attempt_ordinals:
            raise ValueError(
                "selection candidate attempts must exactly match available attempts"
            )
        return self


class H3DeliveryDisclosureV1(StrictFrozenModel):
    code: Literal["SOURCE_GROUNDED", "AI_COMPLETED_NON_ORIGINAL"]
    content_mode: Literal["source_grounded", "ai_completed"]
    label: ShortText
    notice: ShortText

    @model_validator(mode="after")
    def validate_disclosure_mode(self) -> H3DeliveryDisclosureV1:
        expected = {
            "source_grounded": "SOURCE_GROUNDED",
            "ai_completed": "AI_COMPLETED_NON_ORIGINAL",
        }[self.content_mode]
        if self.code != expected:
            raise ValueError("delivery disclosure code and content_mode do not match")
        if self.content_mode == "ai_completed":
            combined = f"{self.label}{self.notice}"
            if (
                "ai" not in combined.casefold()
                or "补全" not in combined
                or "非原文" not in combined
            ):
                raise ValueError(
                    "AI-completed disclosure must identify AI 补全 and 非原文 content"
                )
        return self


class H3DeliverySequenceSourceV1(StrictFrozenModel):
    sequence_id: UUID
    selected_attempt_ordinal: AttemptOrdinal
    source_artifact_digest: Sha256Digest


class H3DeliveryAssemblyManifestV1(StrictFrozenModel):
    sequence_sources: tuple[H3DeliverySequenceSourceV1, ...] = Field(
        min_length=1,
        max_length=100,
    )
    playback_asset_id: UUID
    download_asset_id: UUID

    @model_validator(mode="after")
    def validate_sequence_sources(self) -> H3DeliveryAssemblyManifestV1:
        sequence_ids = tuple(source.sequence_id for source in self.sequence_sources)
        if len(sequence_ids) != len(set(sequence_ids)):
            raise ValueError("delivery sequence sources must be unique")
        return self


class H3DeliveryV1(StrictFrozenModel):
    episode_revision_id: UUID
    status: Literal["succeeded"]
    assembly_manifest: H3DeliveryAssemblyManifestV1
    disclosure: H3DeliveryDisclosureV1
    delivery_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_delivery_digest(self) -> H3DeliveryV1:
        identity = self.model_dump(mode="json", exclude={"delivery_digest"})
        actual = h3_contract_digest(identity)
        if not hmac.compare_digest(actual, self.delivery_digest):
            raise ValueError("delivery_digest mismatch")
        return self


def _validate_candidate_set(
    candidates: tuple[H3CandidateScoreV1, ...],
    sequence_id: UUID,
) -> None:
    if len(candidates) not in (1, 2):
        raise ValueError("candidate selection requires one or two candidates")
    if any(candidate.sequence_id != sequence_id for candidate in candidates):
        raise ValueError("candidate sequence does not match selection sequence")
    ordinals = tuple(candidate.attempt_ordinal for candidate in candidates)
    if len(set(ordinals)) != len(ordinals):
        raise ValueError("candidate attempt ordinals must be unique")
    expected = (0,) if len(candidates) == 1 else (0, 1)
    if tuple(sorted(ordinals)) != expected:
        raise ValueError("candidate set must contain initial and optional repair")


def _winning_candidate(
    candidates: tuple[H3CandidateScoreV1, ...],
) -> H3CandidateScoreV1:
    return max(
        candidates,
        key=lambda candidate: (
            not candidate.exception_codes,
            *candidate.score_vector(),
            -candidate.attempt_ordinal,
        ),
    )


def select_best_h3_attempt(
    *,
    candidates: tuple[H3CandidateScoreV1, ...],
    sequence_id: UUID,
    qc_policy_revision: str,
    selected_at: datetime,
    selection_reason: str,
) -> H3AttemptSelectionV1:
    _validate_candidate_set(candidates, sequence_id)
    ordered = tuple(sorted(candidates, key=lambda candidate: candidate.attempt_ordinal))
    selected = _winning_candidate(ordered)
    clean = not selected.exception_codes
    identity: dict[str, JsonValue] = {
        "sequence_id": str(sequence_id),
        "candidates": [candidate.model_dump(mode="json") for candidate in ordered],
        "selected_attempt_ordinal": selected.attempt_ordinal,
        "selected_cleanly": clean,
        "selected_with_qc_exception": not clean,
        "exception_codes": list(selected.exception_codes),
        "qc_policy_revision": qc_policy_revision,
        "selected_at": selected_at.isoformat().replace("+00:00", "Z"),
        "selection_reason": selection_reason,
    }
    digest = h3_contract_digest(identity)
    return H3AttemptSelectionV1(
        **identity,
        selection_digest=digest,
    )
