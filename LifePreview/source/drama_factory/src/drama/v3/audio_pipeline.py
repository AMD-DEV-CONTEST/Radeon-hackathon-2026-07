from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python
from shared_contracts import ArtifactRef, ComponentName, stable_json_sha256

from ..runtime import atomic_write_json
from ..utils.ffmpeg import burn_subtitles
from .artifact_catalog import FactoryArtifactCatalog
from .domain import (
    DeliveryEligibility,
    DeliveryTake,
    SilencePolicyBinding,
    TakeEligibility,
)
from .state_store import FactoryStateError, FactoryStateStore, artifact_from_file

if TYPE_CHECKING:
    from .qwen_tts_mcp import TTSTake, VoicePresetRevision


class DeliveryPipelineError(RuntimeError):
    pass


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_ALIGNMENT_NAMESPACE = UUID("29316e2a-1a5e-46d6-b082-68a7016a80d0")
_REVISION_REQUEST_NAMESPACE = UUID("b26cc09f-3b5a-4ed1-adb9-c624d9c06380")
_FINAL_AUDIO_ROLES = ("ambience", "sfx", "music")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AcceptedAudioArtifact(_FrozenModel):
    """An audio artifact already admitted by an explicit acceptance revision."""

    artifact_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=44)
    mime: Literal["audio/wav"] = "audio/wav"
    acceptance_revision_id: UUID
    duration_ms: int = Field(gt=0, le=300_000)
    sample_rate: int = Field(ge=8000, le=192000)
    channels: Literal[1] = 1

    def as_artifact_ref(self) -> ArtifactRef:
        return ArtifactRef(
            owner=ComponentName.DRAMA_FACTORY,
            artifact_id=self.artifact_id,
            sha256=self.sha256,
            bytes=self.byte_size,
            mime=self.mime,
            version=1,
        )


class SilencePolicyRevision(_FrozenModel):
    """Immutable authority for intentionally omitting optional audio tracks."""

    silence_policy_revision_id: UUID
    project_id: UUID
    revision: int = Field(ge=1)
    allowed_roles: tuple[Literal["ambience", "sfx", "music"], ...] = Field(
        min_length=1,
        max_length=3,
    )
    maximum_silence_ms: int = Field(gt=0, le=70_000)
    reason: str = Field(min_length=1, max_length=500)
    created_at: AwareDatetime
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validates_immutable_content(self):
        if len(set(self.allowed_roles)) != len(self.allowed_roles):
            raise ValueError("silence policy roles must be unique")
        expected = self.content_digest(
            silence_policy_revision_id=self.silence_policy_revision_id,
            project_id=self.project_id,
            revision=self.revision,
            allowed_roles=self.allowed_roles,
            maximum_silence_ms=self.maximum_silence_ms,
            reason=self.reason,
            created_at=self.created_at,
        )
        if self.digest != expected:
            raise ValueError("silence policy digest does not match content")
        return self

    @staticmethod
    def content_digest(**values: object) -> str:
        return stable_json_sha256(
            to_jsonable_python(
                {
                    "schema_version": "factory.shidu-silence-policy.v1",
                    **values,
                }
            )
        )

    @classmethod
    def create(cls, **values: object) -> SilencePolicyRevision:
        return cls(**values, digest=cls.content_digest(**values))


class FinalAudioTrack(_FrozenModel):
    """Truthful source decision for one optional final-mix track."""

    role: Literal["ambience", "sfx", "music"]
    artifact: AcceptedAudioArtifact | None = None
    silence_policy: SilencePolicyRevision | None = None

    @model_validator(mode="after")
    def exactly_one_authority(self):
        if (self.artifact is None) == (self.silence_policy is None):
            raise ValueError(
                "final audio track requires exactly one accepted artifact or "
                "silence policy"
            )
        if (
            self.silence_policy is not None
            and self.role not in self.silence_policy.allowed_roles
        ):
            raise ValueError("silence policy does not authorize this track role")
        return self

    def validate_for_duration(self, duration_ms: int) -> None:
        if (
            self.silence_policy is not None
            and duration_ms > self.silence_policy.maximum_silence_ms
        ):
            raise DeliveryPipelineError(
                "shidu.audio.silence_policy_duration_exceeded"
            )
        if self.artifact is not None and self.artifact.duration_ms < duration_ms:
            raise DeliveryPipelineError(
                "shidu.audio.accepted_track_duration_too_short"
            )


class AudioAlignmentPolicyRevision(_FrozenModel):
    alignment_policy_revision_id: UUID
    project_id: UUID
    revision: int = Field(ge=1)
    maximum_cue_overrun_ms: int = Field(ge=0, le=5000)
    maximum_cue_underrun_ms: int = Field(ge=0, le=5000)
    maximum_cascade_shift_ms: int = Field(ge=0, le=5000)
    created_at: AwareDatetime
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validates_immutable_content(self):
        expected = self.content_digest(
            alignment_policy_revision_id=self.alignment_policy_revision_id,
            project_id=self.project_id,
            revision=self.revision,
            maximum_cue_overrun_ms=self.maximum_cue_overrun_ms,
            maximum_cue_underrun_ms=self.maximum_cue_underrun_ms,
            maximum_cascade_shift_ms=self.maximum_cascade_shift_ms,
            created_at=self.created_at,
        )
        if self.digest != expected:
            raise ValueError("audio alignment policy digest does not match content")
        return self

    @staticmethod
    def content_digest(**values: object) -> str:
        return stable_json_sha256(
            to_jsonable_python(
                {
                    "schema_version": (
                        "factory.shidu-audio-alignment-policy.v1"
                    ),
                    **values,
                }
            )
        )

    @classmethod
    def create(cls, **values: object) -> AudioAlignmentPolicyRevision:
        return cls(**values, digest=cls.content_digest(**values))


class AlignedDialogueSegment(_FrozenModel):
    ordinal: int = Field(ge=1)
    cue_id: UUID
    cue_key: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=2000)
    tts_take_id: UUID
    tts_take_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_artifact_id: UUID
    audio_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_artifact_bytes: int = Field(gt=44)
    planned_start_ms: int = Field(ge=0)
    planned_end_ms: int = Field(gt=0)
    measured_duration_ms: int = Field(gt=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validates_duration(self):
        if self.end_ms - self.start_ms != self.measured_duration_ms:
            raise ValueError("aligned segment must use measured audio duration")
        return self


class AudioAlignmentRevision(_FrozenModel):
    audio_alignment_revision_id: UUID
    trial_script_revision_id: UUID
    audio_plan_id: UUID
    policy_revision_id: UUID
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    segments: tuple[AlignedDialogueSegment, ...] = Field(min_length=1)
    subtitle_segments: tuple[AlignedDialogueSegment, ...] = Field(min_length=1)
    duration_ms: int = Field(gt=0)
    lipsync_required: Literal[False] = False
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validates_timeline(self):
        if self.segments != self.subtitle_segments:
            raise ValueError("subtitle segments must mirror measured alignment")
        if any(
            current.end_ms > following.start_ms
            for current, following in zip(self.segments, self.segments[1:])
        ):
            raise ValueError("audio alignment segments overlap")
        if self.segments[-1].end_ms > self.duration_ms:
            raise ValueError("audio alignment exceeds plan duration")
        expected = stable_json_sha256(
            {
                "schema_version": "factory.shidu-audio-alignment.v1",
                "trial_script_revision_id": str(
                    self.trial_script_revision_id
                ),
                "audio_plan_id": str(self.audio_plan_id),
                "policy_revision_id": str(self.policy_revision_id),
                "policy_digest": self.policy_digest,
                "segments": [
                    item.model_dump(mode="json") for item in self.segments
                ],
                "subtitle_segments": [
                    item.model_dump(mode="json")
                    for item in self.subtitle_segments
                ],
                "duration_ms": self.duration_ms,
                "lipsync_required": False,
            }
        )
        if self.digest != expected:
            raise ValueError("audio alignment digest does not match content")
        if self.audio_alignment_revision_id != uuid5(
            _ALIGNMENT_NAMESPACE,
            expected,
        ):
            raise ValueError("audio alignment revision identity is invalid")
        return self


class AudioAlignmentRevisionRequest(_FrozenModel):
    request_id: UUID
    trial_script_revision_id: UUID
    audio_plan_id: UUID
    policy_revision_id: UUID
    tts_take_ids: tuple[UUID, ...] = Field(min_length=1)
    reason_codes: tuple[
        Literal[
            "cue_duration_overrun",
            "cue_duration_underrun",
            "cue_cascade_shift_exceeded",
            "timeline_duration_exceeded",
        ],
        ...,
    ] = Field(min_length=1)
    blocked_stage: Literal["final.assemble"] = "final.assemble"
    requested_revision_kind: Literal["script_or_alignment"] = (
        "script_or_alignment"
    )
    speed_change_allowed: Literal[False] = False
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validates_immutable_content(self):
        if len(set(self.tts_take_ids)) != len(self.tts_take_ids):
            raise ValueError("alignment request TTS take ids must be unique")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError(
                "alignment request reason codes must be unique and ordered"
            )
        identity = {
            "schema_version": "factory.shidu-alignment-revision-request.v1",
            "trial_script_revision_id": str(self.trial_script_revision_id),
            "audio_plan_id": str(self.audio_plan_id),
            "policy_revision_id": str(self.policy_revision_id),
            "tts_take_ids": [str(item) for item in self.tts_take_ids],
            "reason_codes": list(self.reason_codes),
            "blocked_stage": self.blocked_stage,
            "requested_revision_kind": self.requested_revision_kind,
            "speed_change_allowed": self.speed_change_allowed,
        }
        expected = stable_json_sha256(identity)
        if self.request_digest != expected:
            raise ValueError(
                "alignment revision request digest does not match content"
            )
        if self.request_id != uuid5(_REVISION_REQUEST_NAMESPACE, expected):
            raise ValueError("alignment revision request identity is invalid")
        return self


class AlignmentRevisionRequired(DeliveryPipelineError):
    error_code = "shidu.audio.alignment_revision_required"

    def __init__(self, request: AudioAlignmentRevisionRequest) -> None:
        super().__init__(self.error_code)
        self.request = request


def _measured_duration_ms(take: object) -> int:
    quality = getattr(take, "audio_quality", None)
    value = getattr(quality, "duration_seconds", None)
    if (
        getattr(quality, "accepted", None) is not True
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError("TTS take must carry accepted measured audio quality")
    return round(float(value) * 1000)


def _validate_tts_take_digest(take: object) -> None:
    required = (
        "take_id",
        "trial_script_revision_id",
        "cue_id",
        "cue_key",
        "voice_preset_revision_id",
        "voice_preset_digest",
        "request_digest",
        "requested",
        "actual",
        "instruction_digest",
        "audio_artifact",
        "audio_quality",
        "retry_count",
        "error_classification",
        "idempotency_key_digest",
        "lipsync_required",
        "take_digest",
        "created_at",
    )
    if any(not hasattr(take, field) for field in required):
        raise ValueError("TTS take immutable contract is incomplete")
    created_at = take.created_at
    if (
        not isinstance(created_at, datetime)
        or created_at.tzinfo is None
        or created_at.utcoffset() is None
    ):
        raise ValueError("TTS take creation time must be timezone-aware")
    try:
        requested = take.requested.model_dump(mode="json")
        actual = take.actual.model_dump(mode="json")
        artifact = take.audio_artifact.model_dump(mode="json")
        quality = take.audio_quality.model_dump(mode="json")
    except AttributeError as exc:
        raise ValueError("TTS take immutable nested contract is invalid") from exc
    expected = stable_json_sha256(
        {
            "take_id": str(take.take_id),
            "trial_script_revision_id": str(take.trial_script_revision_id),
            "cue_id": str(take.cue_id),
            "cue_key": take.cue_key,
            "voice_preset_revision_id": str(take.voice_preset_revision_id),
            "voice_preset_digest": take.voice_preset_digest,
            "request_digest": take.request_digest,
            "requested": requested,
            "actual": actual,
            "instruction_digest": take.instruction_digest,
            "audio_artifact": artifact,
            "audio_quality": quality,
            "retry_count": take.retry_count,
            "error_classification": take.error_classification,
            "idempotency_key_digest": take.idempotency_key_digest,
            "lipsync_required": take.lipsync_required,
            "created_at": created_at.isoformat(),
        }
    )
    if take.take_digest != expected:
        raise ValueError("TTS take digest does not match immutable content")


def _alignment_request(
    *,
    plan: AudioPlan,
    policy: AudioAlignmentPolicyRevision,
    takes: tuple[object, ...],
    script_revision_id: UUID,
    reason_codes: set[str],
) -> AudioAlignmentRevisionRequired:
    ordered_codes = tuple(sorted(reason_codes))
    identity = {
        "schema_version": "factory.shidu-alignment-revision-request.v1",
        "trial_script_revision_id": str(script_revision_id),
        "audio_plan_id": str(plan.plan_id),
        "policy_revision_id": str(policy.alignment_policy_revision_id),
        "tts_take_ids": [str(getattr(item, "take_id")) for item in takes],
        "reason_codes": list(ordered_codes),
        "blocked_stage": "final.assemble",
        "requested_revision_kind": "script_or_alignment",
        "speed_change_allowed": False,
    }
    digest = stable_json_sha256(identity)
    return AlignmentRevisionRequired(
        AudioAlignmentRevisionRequest(
            request_id=uuid5(_REVISION_REQUEST_NAMESPACE, digest),
            trial_script_revision_id=script_revision_id,
            audio_plan_id=plan.plan_id,
            policy_revision_id=policy.alignment_policy_revision_id,
            tts_take_ids=tuple(getattr(item, "take_id") for item in takes),
            reason_codes=ordered_codes,
            request_digest=digest,
        )
    )


def compile_audio_alignment(
    *,
    plan: AudioPlan,
    takes: tuple[object, ...],
    policy: AudioAlignmentPolicyRevision,
) -> AudioAlignmentRevision:
    """Bind one accepted immutable TTS take to every cue using measured time.

    A policy miss produces an immutable revision request and never an altered
    playback rate.  The function has no filesystem side effects, so the same
    inputs always produce the same revision/request identity.
    """

    if plan.lipsync_required:
        raise ValueError("Shidu audio alignment must not require lipsync")
    ordered_cues = tuple(sorted(plan.dialogue, key=lambda item: item.start_ms))
    if not ordered_cues or len(ordered_cues) != len(takes):
        raise ValueError("each dialogue cue requires exactly one TTS take")
    script_ids = {item.trial_script_revision_id for item in ordered_cues}
    if None in script_ids or len(script_ids) != 1:
        raise ValueError("Shidu cues require one exact trial script revision")
    script_revision_id = next(iter(script_ids))
    take_by_cue: dict[UUID, object] = {}
    take_ids: set[UUID] = set()
    artifact_ids: set[UUID] = set()
    preset_bindings: set[tuple[UUID, str]] = set()
    for take in takes:
        _validate_tts_take_digest(take)
        take_id = getattr(take, "take_id", None)
        cue_id = getattr(take, "cue_id", None)
        artifact = getattr(take, "audio_artifact", None)
        artifact_id = getattr(artifact, "artifact_id", None)
        if not isinstance(take_id, UUID) or not isinstance(cue_id, UUID):
            raise ValueError("TTS take identity is invalid")
        if take_id in take_ids:
            raise ValueError("TTS take identity must be unique per cue")
        if not isinstance(artifact_id, UUID) or artifact_id in artifact_ids:
            raise ValueError("TTS audio artifact identity must be unique per cue")
        if cue_id in take_by_cue:
            raise ValueError("each cue must resolve to one TTS take")
        if getattr(take, "lipsync_required", None) is not False:
            raise ValueError("Shidu TTS take must not require lipsync")
        if (
            getattr(take, "error_classification", None) is not None
            or getattr(artifact, "mime", None) != "audio/wav"
            or not isinstance(getattr(artifact, "sha256", None), str)
            or _SHA256.fullmatch(artifact.sha256) is None
            or not isinstance(getattr(artifact, "byte_size", None), int)
            or artifact.byte_size <= 44
        ):
            raise ValueError("TTS take audio artifact contract is invalid")
        quality = take.audio_quality
        if (
            getattr(quality, "sample_rate_hz", plan.sample_rate)
            != plan.sample_rate
            or getattr(quality, "channels", None) != 1
        ):
            raise ValueError("TTS take audio format does not match the plan")
        preset_id = getattr(take, "voice_preset_revision_id", None)
        preset_digest = getattr(take, "voice_preset_digest", None)
        if (
            not isinstance(preset_id, UUID)
            or not isinstance(preset_digest, str)
            or _SHA256.fullmatch(preset_digest) is None
            or not isinstance(getattr(take, "take_digest", None), str)
            or _SHA256.fullmatch(take.take_digest) is None
        ):
            raise ValueError("TTS take voice preset lineage is invalid")
        preset_bindings.add((preset_id, preset_digest))
        _measured_duration_ms(take)
        take_ids.add(take_id)
        artifact_ids.add(artifact_id)
        take_by_cue[cue_id] = take
    if len(preset_bindings) != 1:
        raise ValueError("all Shidu TTS takes must share one voice preset revision")

    segments: list[AlignedDialogueSegment] = []
    reason_codes: set[str] = set()
    prior_end = 0
    ordered_takes: list[object] = []
    for ordinal, cue in enumerate(ordered_cues, start=1):
        take = take_by_cue.get(cue.cue_id)
        if (
            take is None
            or getattr(take, "trial_script_revision_id", None)
            != script_revision_id
            or getattr(take, "cue_key", None) != cue.cue_key
        ):
            raise ValueError("TTS take does not match exact cue lineage")
        expected_request_digest = stable_json_sha256(
            {
                "trial_script_revision_id": str(script_revision_id),
                "cue_id": str(cue.cue_id),
                "cue_key": cue.cue_key,
                "text_digest": hashlib.sha256(
                    cue.text.encode("utf-8")
                ).hexdigest(),
                "voice_preset_revision_id": str(
                    take.voice_preset_revision_id
                ),
                "voice_preset_digest": take.voice_preset_digest,
                "identity": take.requested.model_dump(mode="json"),
                "instruction_digest": take.instruction_digest,
            }
        )
        if (
            take.request_digest != expected_request_digest
            or take.requested != take.actual
        ):
            raise ValueError("TTS take request/actual lineage is inconsistent")
        ordered_takes.append(take)
        measured_ms = _measured_duration_ms(take)
        planned_ms = cue.end_ms - cue.start_ms
        delta = measured_ms - planned_ms
        if delta > policy.maximum_cue_overrun_ms:
            reason_codes.add("cue_duration_overrun")
        if -delta > policy.maximum_cue_underrun_ms:
            reason_codes.add("cue_duration_underrun")
        start_ms = max(cue.start_ms, prior_end)
        if start_ms - cue.start_ms > policy.maximum_cascade_shift_ms:
            reason_codes.add("cue_cascade_shift_exceeded")
        end_ms = start_ms + measured_ms
        if end_ms > plan.duration_ms:
            reason_codes.add("timeline_duration_exceeded")
        artifact = take.audio_artifact
        segments.append(
            AlignedDialogueSegment(
                ordinal=ordinal,
                cue_id=cue.cue_id,
                cue_key=cue.cue_key or "",
                text=cue.text,
                tts_take_id=take.take_id,
                tts_take_digest=take.take_digest,
                audio_artifact_id=artifact.artifact_id,
                audio_artifact_sha256=artifact.sha256,
                audio_artifact_bytes=artifact.byte_size,
                planned_start_ms=cue.start_ms,
                planned_end_ms=cue.end_ms,
                measured_duration_ms=measured_ms,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )
        prior_end = end_ms
    ordered_takes_tuple = tuple(ordered_takes)
    if reason_codes:
        raise _alignment_request(
            plan=plan,
            policy=policy,
            takes=ordered_takes_tuple,
            script_revision_id=script_revision_id,
            reason_codes=reason_codes,
        )

    payload = {
        "schema_version": "factory.shidu-audio-alignment.v1",
        "trial_script_revision_id": str(script_revision_id),
        "audio_plan_id": str(plan.plan_id),
        "policy_revision_id": str(policy.alignment_policy_revision_id),
        "policy_digest": policy.digest,
        "segments": [item.model_dump(mode="json") for item in segments],
        "subtitle_segments": [item.model_dump(mode="json") for item in segments],
        "duration_ms": plan.duration_ms,
        "lipsync_required": False,
    }
    digest = stable_json_sha256(payload)
    return AudioAlignmentRevision(
        audio_alignment_revision_id=uuid5(_ALIGNMENT_NAMESPACE, digest),
        trial_script_revision_id=script_revision_id,
        audio_plan_id=plan.plan_id,
        policy_revision_id=policy.alignment_policy_revision_id,
        policy_digest=policy.digest,
        segments=tuple(segments),
        subtitle_segments=tuple(segments),
        duration_ms=plan.duration_ms,
        lipsync_required=False,
        digest=digest,
    )


class DialogueCue(_FrozenModel):
    cue_id: UUID
    trial_script_revision_id: UUID | None = None
    cue_key: str | None = Field(default=None, min_length=1, max_length=160)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="Chinese", min_length=1, max_length=100)
    speaker: str = Field(default="Serena", min_length=1, max_length=100)
    instruction: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def end_follows_start(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("dialogue cue end must follow start")
        if (self.trial_script_revision_id is None) != (self.cue_key is None):
            raise ValueError(
                "trial script revision and cue key must be supplied together"
            )
        return self


class AudioPlan(_FrozenModel):
    plan_id: UUID
    visual_take_id: UUID
    visual_take_ids: tuple[UUID, ...] = ()
    duration_ms: int = Field(gt=0)
    sample_rate: int = Field(default=24000, ge=8000, le=192000)
    dialogue: tuple[DialogueCue, ...]
    ambience_prompt: str | None = Field(default=None, max_length=1000)
    sfx_prompt: str | None = Field(default=None, max_length=1000)
    music_prompt: str | None = Field(default=None, max_length=1000)
    lipsync_required: bool = False
    created_at: AwareDatetime

    @model_validator(mode="after")
    def cues_fit_timeline(self):
        ordered = sorted(self.dialogue, key=lambda item: item.start_ms)
        if any(item.end_ms > self.duration_ms for item in ordered):
            raise ValueError("dialogue cue exceeds audio plan duration")
        if any(
            current.end_ms > following.start_ms
            for current, following in zip(ordered, ordered[1:])
        ):
            raise ValueError("dialogue cues must not overlap")
        if self.visual_take_ids:
            if (
                len(self.visual_take_ids) != 6
                or len(set(self.visual_take_ids)) != 6
                or self.visual_take_ids[0] != self.visual_take_id
            ):
                raise ValueError(
                    "Shidu visual take selection must contain six unique "
                    "ordered ids led by visual_take_id"
                )
        return self


class TTSProvider(Protocol):
    def synthesize(
        self,
        *,
        cue: DialogueCue,
        voice_preset: VoicePresetRevision,
        destination: Path,
        idempotency_key: str,
    ) -> TTSTake: ...


class FinalAudioAuthorityResolver(Protocol):
    """Resolve declarations against a trusted acceptance/policy store."""

    def resolve_accepted_audio(
        self,
        *,
        project_id: UUID,
        role: str,
        declared: AcceptedAudioArtifact,
    ) -> AcceptedAudioArtifact | None: ...

    def resolve_silence_policy(
        self,
        *,
        project_id: UUID,
        role: str,
        declared: SilencePolicyRevision,
    ) -> SilencePolicyRevision | None: ...


class LegacyTTSProvider(Protocol):
    def synthesize(self, cue: DialogueCue, destination: Path) -> Path: ...


class LipsyncProvider(Protocol):
    def apply(
        self,
        *,
        video: Path,
        dialogue: Path,
        destination: Path,
    ) -> Path: ...


def validate_returned_voice_preset(
    take: object,
    voice_preset: VoicePresetRevision,
) -> None:
    """Fail closed unless a provider take reflects the exact locked preset."""

    requested = getattr(take, "requested", None)
    actual = getattr(take, "actual", None)
    expected_identity = {
        "provider": voice_preset.provider,
        "service_version": voice_preset.discovery_service_version,
        "model_id": voice_preset.model_id,
        "tool_name": voice_preset.discovery_tool_name,
        "schema_digest": voice_preset.discovery_schema_digest,
        "speaker": voice_preset.speaker,
        "language": voice_preset.language,
    }
    try:
        requested_identity = requested.model_dump(mode="json")
        actual_identity = actual.model_dump(mode="json")
    except AttributeError as exc:
        raise DeliveryPipelineError(
            "shidu.audio.returned_voice_preset_mismatch"
        ) from exc
    if (
        not voice_preset.enabled
        or getattr(take, "voice_preset_revision_id", None)
        != voice_preset.voice_preset_revision_id
        or getattr(take, "voice_preset_digest", None) != voice_preset.digest
        or getattr(take, "instruction_digest", None)
        != voice_preset.instruction_digest
        or requested_identity != expected_identity
        or actual_identity != expected_identity
    ):
        raise DeliveryPipelineError(
            "shidu.audio.returned_voice_preset_mismatch"
        )


def _probe_accepted_wav(
    path: Path,
    declared: AcceptedAudioArtifact,
) -> None:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate = handle.getframerate()
            sample_width = handle.getsampwidth()
            frame_count = handle.getnframes()
    except (OSError, EOFError, wave.Error) as exc:
        raise DeliveryPipelineError(
            "shidu.audio.accepted_wav_probe_failed"
        ) from exc
    measured_duration_ms = round(frame_count * 1000 / sample_rate)
    if (
        channels != declared.channels
        or sample_rate != declared.sample_rate
        or sample_width != 2
        or measured_duration_ms != declared.duration_ms
    ):
        raise DeliveryPipelineError(
            "shidu.audio.accepted_wav_metadata_mismatch"
        )


def resolve_final_audio_tracks(
    *,
    tracks: tuple[FinalAudioTrack, ...],
    project_id: UUID,
    duration_ms: int,
    catalog: FactoryArtifactCatalog,
    authority_resolver: FinalAudioAuthorityResolver,
    probe_wav_bytes: bool = False,
) -> tuple[
    tuple[tuple[str, Path], ...],
    dict[str, ArtifactRef],
    tuple[SilencePolicyBinding, ...],
]:
    """Resolve every final mix role through exact trusted authority."""

    tracks_by_role = {item.role: item for item in tracks}
    if (
        len(tracks_by_role) != len(tracks)
        or set(tracks_by_role) != set(_FINAL_AUDIO_ROLES)
    ):
        raise DeliveryPipelineError(
            "shidu.audio.final_track_authority_incomplete"
        )
    accepted_paths: list[tuple[str, Path]] = []
    accepted_refs: dict[str, ArtifactRef] = {}
    silence_bindings: list[SilencePolicyBinding] = []
    for role in _FINAL_AUDIO_ROLES:
        track = tracks_by_role[role]
        track.validate_for_duration(duration_ms)
        if track.artifact is not None:
            try:
                resolved = authority_resolver.resolve_accepted_audio(
                    project_id=project_id,
                    role=role,
                    declared=track.artifact,
                )
            except Exception as exc:
                raise DeliveryPipelineError(
                    "shidu.audio.final_track_authority_untrusted"
                ) from exc
            if resolved != track.artifact:
                raise DeliveryPipelineError(
                    "shidu.audio.final_track_authority_untrusted"
                )
            ref = resolved.as_artifact_ref()
            try:
                path = catalog.resolve(ref)
            except Exception as exc:
                raise DeliveryPipelineError(
                    "shidu.audio.accepted_audio_artifact_unavailable"
                ) from exc
            if probe_wav_bytes:
                _probe_accepted_wav(path, resolved)
            accepted_paths.append((role, path))
            accepted_refs[role] = ref
            continue
        policy = track.silence_policy
        assert policy is not None
        if policy.project_id != project_id:
            raise DeliveryPipelineError(
                "shidu.audio.revision_project_lineage_mismatch"
            )
        try:
            resolved_policy = authority_resolver.resolve_silence_policy(
                project_id=project_id,
                role=role,
                declared=policy,
            )
        except Exception as exc:
            raise DeliveryPipelineError(
                "shidu.audio.final_track_authority_untrusted"
            ) from exc
        if resolved_policy != policy:
            raise DeliveryPipelineError(
                "shidu.audio.final_track_authority_untrusted"
            )
        silence_bindings.append(
            SilencePolicyBinding(
                role=role,
                silence_policy_revision_id=(
                    policy.silence_policy_revision_id
                ),
                silence_policy_digest=policy.digest,
                maximum_silence_ms=policy.maximum_silence_ms,
            )
        )
    return (
        tuple(accepted_paths),
        accepted_refs,
        tuple(silence_bindings),
    )


def resolve_shidu_visual_sources(
    *,
    plan: AudioPlan,
    state: object,
    catalog: FactoryArtifactCatalog,
) -> tuple[Path, ...]:
    """Resolve exactly six accepted takes in canonical scene/clip order."""

    visual_take_ids = plan.visual_take_ids
    if len(visual_take_ids) != 6 or len(set(visual_take_ids)) != 6:
        raise DeliveryPipelineError(
            "shidu.audio.six_accepted_visual_takes_required"
        )
    if visual_take_ids[0] != plan.visual_take_id:
        raise DeliveryPipelineError(
            "shidu.audio.visual_take_order_mismatch"
        )
    visual_by_id = {
        item.visual_take_id: item for item in getattr(state, "visual_takes", ())
    }
    run_by_id = {item.run_id: item for item in getattr(state, "runs", ())}
    clip_by_id = {
        item.clip_id: item for item in getattr(state, "clips", ())
    }
    scene_by_id = {
        item.scene_id: item for item in getattr(state, "scenes", ())
    }
    revision_id = getattr(
        getattr(state, "project_revision", None),
        "revision_id",
        None,
    )
    resolved: list[tuple[tuple[int, int], UUID, Path, int]] = []
    for visual_take_id in visual_take_ids:
        visual = visual_by_id.get(visual_take_id)
        if (
            visual is None
            or visual.eligibility is not TakeEligibility.ACCEPTED
        ):
            raise DeliveryPipelineError(
                "shidu.audio.accepted_visual_take_required"
            )
        run = run_by_id.get(visual.run_id)
        clip = None if run is None else clip_by_id.get(run.clip_id)
        scene = None if clip is None else scene_by_id.get(clip.scene_id)
        request = None if run is None else getattr(run, "request", None)
        duration_seconds = getattr(request, "duration_seconds", None)
        if (
            run is None
            or clip is None
            or scene is None
            or getattr(request, "project_revision_id", None) != revision_id
            or getattr(request, "scene_id", None) != clip.scene_id
            or isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(float(duration_seconds))
            or duration_seconds <= 0
        ):
            raise DeliveryPipelineError(
                "shidu.audio.visual_take_lineage_mismatch"
            )
        try:
            visual_path = catalog.resolve(visual.raw_video_ref)
        except Exception as exc:
            raise DeliveryPipelineError(
                "shidu.audio.visual_artifact_unavailable"
            ) from exc
        resolved.append(
            (
                (scene.order, clip.order),
                visual_take_id,
                visual_path,
                round(float(duration_seconds) * 1000),
            )
        )
    order_keys = [item[0] for item in resolved]
    if len(set(order_keys)) != 6:
        raise DeliveryPipelineError(
            "shidu.audio.visual_take_lineage_mismatch"
        )
    canonical = sorted(resolved, key=lambda item: item[0])
    if tuple(item[1] for item in canonical) != visual_take_ids:
        raise DeliveryPipelineError(
            "shidu.audio.visual_take_order_mismatch"
        )
    if sum(item[3] for item in canonical) != plan.duration_ms:
        raise DeliveryPipelineError(
            "shidu.audio.visual_duration_mismatch"
        )
    return tuple(item[2] for item in canonical)


def concat_shidu_visuals(
    sources: tuple[Path, ...],
    destination: Path,
) -> Path:
    """Materialize the six accepted visual takes as one ordered video."""

    if len(sources) != 6 or len(set(sources)) != 6:
        raise DeliveryPipelineError(
            "shidu.audio.six_accepted_visual_takes_required"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    concat_filter = (
        "".join(f"[{index}:v:0]" for index in range(6))
        + "concat=n=6:v=1:a=0[v]"
    )
    _run(
        [
            "ffmpeg",
            "-y",
            *[value for path in sources for value in ("-i", str(path))],
            "-filter_complex",
            concat_filter,
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ]
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise DeliveryPipelineError(
            "shidu.audio.visual_concat_materialization_failed"
        )
    return destination


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
        )
    except OSError as exc:
        raise DeliveryPipelineError(
            f"required media executable is unavailable: {command[0]}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "")[-2000:]
        raise DeliveryPipelineError(
            f"media command failed: {command[0]}: {detail}"
        ) from exc


class Qwen3TTSCommandProvider:
    """Run Qwen3-TTS in its isolated local Python environment."""

    def __init__(
        self,
        *,
        python_executable: str | Path,
        model_path: str | Path,
        device: str = "cuda:0",
    ) -> None:
        self.python_executable = Path(python_executable)
        self.model_path = Path(model_path)
        self.device = device

    def synthesize(self, cue: DialogueCue, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request_path = destination.with_suffix(".request.json")
        atomic_write_json(
            request_path,
            {
                "model_path": str(self.model_path),
                "device": self.device,
                "text": cue.text,
                "language": cue.language,
                "speaker": cue.speaker,
                "instruction": cue.instruction or "",
                "destination": str(destination),
            },
        )
        runner = Path(__file__).with_name("qwen_tts_worker.py")
        _run(
            [
                str(self.python_executable),
                str(runner),
                "--request",
                str(request_path),
            ]
        )
        if not destination.is_file() or destination.stat().st_size <= 44:
            raise DeliveryPipelineError("Qwen3-TTS produced no usable audio")
        return destination


class FFmpegToneTTSProvider:
    """Deterministic offline smoke provider; never used as a hidden fallback."""

    def synthesize(self, cue: DialogueCue, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        duration = (cue.end_ms - cue.start_ms) / 1000
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=220:sample_rate=24000:duration={duration:.3f}",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ]
        )
        return destination


class CommandLipsyncProvider:
    """Adapter for a pinned local lipsync runner such as LatentSync."""

    def __init__(self, command_prefix: tuple[str, ...]) -> None:
        if not command_prefix:
            raise ValueError("lipsync command prefix is required")
        self.command_prefix = command_prefix

    def apply(
        self,
        *,
        video: Path,
        dialogue: Path,
        destination: Path,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                *self.command_prefix,
                "--video",
                str(video),
                "--audio",
                str(dialogue),
                "--output",
                str(destination),
            ]
        )
        if not destination.is_file():
            raise DeliveryPipelineError("lipsync runner produced no video")
        return destination


def _srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _write_srt(plan: AudioPlan, destination: Path) -> None:
    lines: list[str] = []
    for index, cue in enumerate(plan.dialogue, start=1):
        lines.extend(
            [
                str(index),
                f"{_srt_time(cue.start_ms)} --> {_srt_time(cue.end_ms)}",
                cue.text,
                "",
            ]
        )
    destination.write_text("\n".join(lines), encoding="utf-8")


def _write_aligned_srt(
    revision: AudioAlignmentRevision,
    destination: Path,
) -> None:
    lines: list[str] = []
    for segment in revision.subtitle_segments:
        lines.extend(
            [
                str(segment.ordinal),
                (
                    f"{_srt_time(segment.start_ms)} --> "
                    f"{_srt_time(segment.end_ms)}"
                ),
                segment.text,
                "",
            ]
        )
    destination.write_text("\n".join(lines), encoding="utf-8")


def _file_digest_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _validate_tts_materialization(
    *,
    take: object,
    cue: DialogueCue,
    voice_preset: VoicePresetRevision,
    destination: Path,
    idempotency_key: str,
) -> None:
    validate_returned_voice_preset(take, voice_preset)
    _validate_tts_take_digest(take)
    if (
        getattr(take, "trial_script_revision_id", None)
        != cue.trial_script_revision_id
        or getattr(take, "cue_id", None) != cue.cue_id
        or getattr(take, "cue_key", None) != cue.cue_key
        or getattr(take, "idempotency_key_digest", None)
        != hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    ):
        raise DeliveryPipelineError(
            "shidu.audio.tts_checkpoint_lineage_mismatch"
        )
    if not destination.is_file():
        raise DeliveryPipelineError(
            "shidu.audio.tts_checkpoint_reconciliation_required"
        )
    digest, size = _file_digest_and_size(destination)
    artifact = getattr(take, "audio_artifact", None)
    if (
        getattr(artifact, "sha256", None) != digest
        or getattr(artifact, "byte_size", None) != size
    ):
        raise DeliveryPipelineError(
            "shidu.audio.tts_checkpoint_reconciliation_required"
        )


def materialize_shidu_tts_take(
    *,
    provider: TTSProvider,
    cue: DialogueCue,
    voice_preset: VoicePresetRevision,
    destination: Path,
    idempotency_key: str,
) -> TTSTake:
    """Synthesize once, then recover the exact take from its checkpoint."""

    checkpoint = destination.with_suffix(".take.json")
    if destination.exists() or checkpoint.exists():
        if not destination.is_file() or not checkpoint.is_file():
            raise DeliveryPipelineError(
                "shidu.audio.tts_checkpoint_reconciliation_required"
            )
        try:
            from .qwen_tts_mcp import TTSTake as RuntimeTTSTake

            take = RuntimeTTSTake.model_validate_json(
                checkpoint.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise DeliveryPipelineError(
                "shidu.audio.tts_checkpoint_reconciliation_required"
            ) from exc
        _validate_tts_materialization(
            take=take,
            cue=cue,
            voice_preset=voice_preset,
            destination=destination,
            idempotency_key=idempotency_key,
        )
        return take
    take = provider.synthesize(
        cue=cue,
        voice_preset=voice_preset,
        destination=destination,
        idempotency_key=idempotency_key,
    )
    _validate_tts_materialization(
        take=take,
        cue=cue,
        voice_preset=voice_preset,
        destination=destination,
        idempotency_key=idempotency_key,
    )
    atomic_write_json(checkpoint, take.model_dump(mode="json"))
    return take


def persist_alignment_revision_request(
    request: AudioAlignmentRevisionRequest,
    destination: Path,
) -> None:
    """Persist an immutable request and reject conflicting replay content."""

    if destination.is_file():
        try:
            existing = AudioAlignmentRevisionRequest.model_validate_json(
                destination.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise DeliveryPipelineError(
                "shidu.audio.alignment_request_reconciliation_required"
            ) from exc
        if existing != request:
            raise DeliveryPipelineError(
                "shidu.audio.alignment_request_reconciliation_required"
            )
        return
    atomic_write_json(destination, request.model_dump(mode="json"))


def materialize_shidu_audio_mix(
    *,
    plan: AudioPlan,
    alignment: AudioAlignmentRevision,
    tts_takes: tuple[object, ...],
    tts_paths: tuple[Path, ...],
    accepted_track_paths: tuple[tuple[str, Path], ...],
    output_dir: Path,
) -> tuple[Path, Path]:
    """Place exact measured takes and mix only accepted optional tracks."""

    if (
        len(alignment.segments) != 6
        or len(tts_takes) != 6
        or len(tts_paths) != 6
    ):
        raise DeliveryPipelineError("shidu.audio.six_narration_cues_required")
    for segment, take, path in zip(
        alignment.segments,
        tts_takes,
        tts_paths,
        strict=True,
    ):
        artifact = getattr(take, "audio_artifact", None)
        if (
            segment.tts_take_id != getattr(take, "take_id", None)
            or segment.audio_artifact_id != getattr(artifact, "artifact_id", None)
            or segment.audio_artifact_sha256 != getattr(artifact, "sha256", None)
            or segment.audio_artifact_bytes != getattr(
                artifact,
                "byte_size",
                None,
            )
        ):
            raise DeliveryPipelineError(
                "shidu.audio.tts_take_lineage_incomplete"
            )
        try:
            digest, size = _file_digest_and_size(path)
        except OSError as exc:
            raise DeliveryPipelineError(
                "shidu.audio.tts_take_materialization_mismatch"
            ) from exc
        if digest != artifact.sha256 or size != artifact.byte_size:
            raise DeliveryPipelineError(
                "shidu.audio.tts_take_materialization_mismatch"
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    dialogue_path = output_dir / "dialogue.wav"
    dialogue_filters = [
        f"[{index}:a]adelay={segment.start_ms}:all=1[d{index}]"
        for index, segment in enumerate(alignment.segments)
    ]
    dialogue_filters.append(
        "".join(f"[d{index}]" for index in range(len(alignment.segments)))
        + (
            f"amix=inputs={len(alignment.segments)}:duration=longest:"
            "normalize=0,"
            f"apad=whole_dur={plan.duration_ms / 1000:.3f},"
            f"atrim=duration={plan.duration_ms / 1000:.3f}[dialogue]"
        )
    )
    _run(
        [
            "ffmpeg",
            "-y",
            *[
                value
                for path in tts_paths
                for value in ("-i", str(path))
            ],
            "-filter_complex",
            ";".join(dialogue_filters),
            "-map",
            "[dialogue]",
            "-ar",
            str(plan.sample_rate),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dialogue_path),
        ]
    )
    mix_path = output_dir / "mix.wav"
    mix_inputs = (dialogue_path, *(path for _, path in accepted_track_paths))
    mix_filters = [
        (
            f"[{index}:a]atrim=duration={plan.duration_ms / 1000:.3f},"
            f"apad=whole_dur={plan.duration_ms / 1000:.3f}[m{index}]"
        )
        for index in range(len(mix_inputs))
    ]
    mix_filters.append(
        "".join(f"[m{index}]" for index in range(len(mix_inputs)))
        + (
            f"amix=inputs={len(mix_inputs)}:duration=longest:normalize=0,"
            f"atrim=duration={plan.duration_ms / 1000:.3f}[mix]"
        )
    )
    _run(
        [
            "ffmpeg",
            "-y",
            *[
                value
                for path in mix_inputs
                for value in ("-i", str(path))
            ],
            "-filter_complex",
            ";".join(mix_filters),
            "-map",
            "[mix]",
            "-ar",
            str(plan.sample_rate),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(mix_path),
        ]
    )
    if any(
        not path.is_file() or path.stat().st_size == 0
        for path in (dialogue_path, mix_path)
    ):
        raise DeliveryPipelineError(
            "shidu.audio.mix_materialization_failed"
        )
    return dialogue_path, mix_path


def assemble_shidu_delivery(
    *,
    visual_sources: tuple[Path, ...],
    mix_path: Path,
    subtitle_path: Path,
    duration_ms: int,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    """Concat six accepted visuals, mux the accepted mix, and burn subtitles."""

    visual_concat_path = concat_shidu_visuals(
        visual_sources,
        output_dir / "visual_concat.mp4",
    )
    muxed_path = output_dir / "muxed.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(visual_concat_path),
            "-i",
            str(mix_path),
            "-filter_complex",
            (
                "[0:v]tpad=stop_mode=clone:"
                f"stop_duration={duration_ms / 1000:.3f},"
                f"trim=duration={duration_ms / 1000:.3f},"
                "setpts=PTS-STARTPTS[v]"
            ),
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            f"{duration_ms / 1000:.3f}",
            str(muxed_path),
        ]
    )
    final_path = output_dir / "final.mp4"
    burn_subtitles(muxed_path, subtitle_path, final_path)
    if any(
        not path.is_file() or path.stat().st_size == 0
        for path in (muxed_path, final_path)
    ):
        raise DeliveryPipelineError(
            "shidu.audio.final_materialization_failed"
        )
    return visual_concat_path, muxed_path, final_path


def derive_shidu_delivery_surfaces(
    *, final_path: Path, output_dir: Path
) -> tuple[Path, Path]:
    """Create distinct durable JPEG cover/share surfaces from the final video."""

    if not final_path.is_file() or final_path.stat().st_size == 0:
        raise DeliveryPipelineError("shidu.audio.final_materialization_failed")
    output_dir.mkdir(parents=True, exist_ok=True)
    cover_path = output_dir / "cover.jpg"
    share_card_path = output_dir / "share-card.jpg"
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(final_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=720:-2",
            "-q:v",
            "2",
            str(cover_path),
        ]
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(final_path),
            "-frames:v",
            "1",
            "-vf",
            (
                "scale=720:1280:force_original_aspect_ratio=decrease,"
                "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-q:v",
            "2",
            str(share_card_path),
        ]
    )
    if any(
        not path.is_file() or path.stat().st_size == 0
        for path in (cover_path, share_card_path)
    ):
        raise DeliveryPipelineError(
            "shidu.audio.delivery_surface_materialization_failed"
        )
    return cover_path, share_card_path


class LocalDeliveryPipeline:
    def __init__(
        self,
        *,
        store: FactoryStateStore,
        catalog: FactoryArtifactCatalog,
        tts: LegacyTTSProvider,
        lipsync: LipsyncProvider | None = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.tts = tts
        self.lipsync = lipsync

    def _bind(self, path: Path, *, mime: str, role: str):
        artifact = artifact_from_file(path, mime=mime)
        self.catalog.bind(
            artifact,
            path,
            role=role,
            created_at=datetime.now(timezone.utc),
        )
        return artifact

    def build(
        self,
        plan: AudioPlan,
        *,
        expected_state_version: int,
    ):
        state = self.store.load()
        if state.state_version != expected_state_version:
            raise FactoryStateError("factory state changed before delivery build")
        visual = next(
            (
                item
                for item in state.visual_takes
                if item.visual_take_id == plan.visual_take_id
            ),
            None,
        )
        if visual is None or visual.eligibility is not TakeEligibility.ACCEPTED:
            raise DeliveryPipelineError(
                "delivery build requires an accepted visual take"
            )
        run = next(item for item in state.runs if item.run_id == visual.run_id)
        if round(run.request.duration_seconds * 1000) != plan.duration_ms:
            raise DeliveryPipelineError(
                "audio plan duration must match the visual request"
            )
        source_video = self.catalog.resolve(visual.raw_video_ref)
        delivery_take_id = uuid4()
        output = (
            self.store.root
            / "artifacts"
            / "delivery"
            / str(delivery_take_id)
        )
        output.mkdir(parents=True, exist_ok=False)

        timeline_path = output / "audio_timeline.json"
        atomic_write_json(timeline_path, plan.model_dump(mode="json"))
        subtitle_path = output / "subtitles.srt"
        _write_srt(plan, subtitle_path)

        if not plan.dialogue:
            raise DeliveryPipelineError(
                "delivery build requires at least one dialogue cue"
            )
        ordered_cues = tuple(
            sorted(plan.dialogue, key=lambda item: item.start_ms)
        )
        raw_dialogue_paths: list[Path] = []
        for index, cue in enumerate(ordered_cues, start=1):
            raw_dialogue = output / f"dialogue_raw_{index:03d}.wav"
            self.tts.synthesize(cue, raw_dialogue)
            if not raw_dialogue.is_file() or raw_dialogue.stat().st_size <= 44:
                raise DeliveryPipelineError(
                    "dialogue cue produced no usable audio"
                )
            raw_dialogue_paths.append(raw_dialogue)
        dialogue_path = output / "dialogue.wav"
        filter_steps = [
            f"[{index}:a]adelay={cue.start_ms}:all=1[d{index}]"
            for index, cue in enumerate(ordered_cues)
        ]
        filter_steps.append(
            "".join(
                f"[d{index}]" for index in range(len(ordered_cues))
            )
            + (
                f"amix=inputs={len(ordered_cues)}:duration=longest:normalize=0,"
                f"apad=whole_dur={plan.duration_ms / 1000:.3f},"
                f"atrim=duration={plan.duration_ms / 1000:.3f}[dialogue]"
            )
        )
        _run(
            [
                "ffmpeg",
                "-y",
                *[
                    item
                    for path in raw_dialogue_paths
                    for item in ("-i", str(path))
                ],
                "-filter_complex",
                ";".join(filter_steps),
                "-map",
                "[dialogue]",
                "-ar",
                str(plan.sample_rate),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(dialogue_path),
            ]
        )
        duration = plan.duration_ms / 1000
        ambience_path = output / "ambience.wav"
        sfx_path = output / "sfx.wav"
        music_path = output / "music.wav"
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anoisesrc=color=pink:amplitude=0.008:r={plan.sample_rate}:d={duration:.3f}",
                "-c:a",
                "pcm_s16le",
                str(ambience_path),
            ]
        )
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={plan.sample_rate}:cl=mono:d={duration:.3f}",
                "-c:a",
                "pcm_s16le",
                str(sfx_path),
            ]
        )
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=110:sample_rate={plan.sample_rate}:duration={duration:.3f}",
                "-af",
                "volume=0.004",
                "-c:a",
                "pcm_s16le",
                str(music_path),
            ]
        )
        mix_path = output / "mix.wav"
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(dialogue_path),
                "-i",
                str(ambience_path),
                "-i",
                str(sfx_path),
                "-i",
                str(music_path),
                "-filter_complex",
                "amix=inputs=4:duration=longest:normalize=0",
                "-t",
                f"{duration:.3f}",
                "-ar",
                str(plan.sample_rate),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(mix_path),
            ]
        )

        lipsync_path = None
        composite_source = source_video
        if plan.lipsync_required:
            if self.lipsync is None:
                raise DeliveryPipelineError(
                    "audio plan requires lipsync but no local provider is configured"
                )
            lipsync_path = output / "lipsync.mp4"
            composite_source = self.lipsync.apply(
                video=source_video,
                dialogue=dialogue_path,
                destination=lipsync_path,
            )
        muxed_path = output / "muxed.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(composite_source),
                "-i",
                str(mix_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(muxed_path),
            ]
        )
        final_path = output / "final.mp4"
        burn_subtitles(muxed_path, subtitle_path, final_path)

        take = DeliveryTake(
            delivery_take_id=delivery_take_id,
            visual_take_id=visual.visual_take_id,
            audio_timeline_ref=self._bind(
                timeline_path,
                mime="application/json",
                role="audio_timeline",
            ),
            dialogue_ref=self._bind(
                dialogue_path,
                mime="audio/wav",
                role="dialogue_track",
            ),
            ambience_ref=self._bind(
                ambience_path,
                mime="audio/wav",
                role="ambience_track",
            ),
            sfx_ref=self._bind(
                sfx_path,
                mime="audio/wav",
                role="sfx_track",
            ),
            music_ref=self._bind(
                music_path,
                mime="audio/wav",
                role="music_track",
            ),
            subtitle_ref=self._bind(
                subtitle_path,
                mime="application/x-subrip",
                role="subtitle_track",
            ),
            lipsync_video_ref=(
                None
                if lipsync_path is None
                else self._bind(
                    lipsync_path,
                    mime="video/mp4",
                    role="lipsync_video",
                )
            ),
            final_composite_ref=self._bind(
                final_path,
                mime="video/mp4",
                role="final_composite",
            ),
            eligibility=DeliveryEligibility.CANDIDATE,
            created_at=datetime.now(timezone.utc),
        )
        return self.store.record_delivery_take(
            take,
            expected_state_version=expected_state_version,
        )

    def build_shidu(
        self,
        plan: AudioPlan,
        *,
        voice_preset: VoicePresetRevision,
        alignment_policy: AudioAlignmentPolicyRevision,
        final_tracks: tuple[FinalAudioTrack, ...],
        final_audio_authority: FinalAudioAuthorityResolver,
        command_idempotency_key: str,
        expected_state_version: int,
        probe_accepted_wav_bytes: bool = True,
    ):
        """Assemble a Shidu trial from exact per-cue takes and track policy.

        This path deliberately has no lipsync/fallback branch.  Every optional
        final-mix role is either a previously accepted artifact or an immutable
        bounded silence decision; no tone/noise/empty WAV is manufactured.
        """

        if not isinstance(command_idempotency_key, str) or not (
            1 <= len(command_idempotency_key.strip()) <= 180
        ):
            raise DeliveryPipelineError(
                "shidu.audio.command_idempotency_key_invalid"
            )
        if plan.lipsync_required:
            raise DeliveryPipelineError("shidu.audio.lipsync_forbidden")
        if not 50_000 <= plan.duration_ms <= 70_000:
            raise DeliveryPipelineError(
                "shidu.audio.trial_duration_outside_50_70_seconds"
            )
        if len(plan.dialogue) != 6:
            raise DeliveryPipelineError(
                "shidu.audio.six_narration_cues_required"
            )
        tracks_by_role = {item.role: item for item in final_tracks}
        if (
            len(tracks_by_role) != len(final_tracks)
            or set(tracks_by_role) != set(_FINAL_AUDIO_ROLES)
        ):
            raise DeliveryPipelineError(
                "shidu.audio.final_track_authority_incomplete"
            )
        ordered_final_tracks = tuple(
            tracks_by_role[role] for role in _FINAL_AUDIO_ROLES
        )
        for item in ordered_final_tracks:
            item.validate_for_duration(plan.duration_ms)

        state = self.store.load()
        if state.state_version != expected_state_version:
            raise FactoryStateError("factory state changed before delivery build")
        project_id = state.project_revision.project_id
        if (
            alignment_policy.project_id != project_id
            or voice_preset.project_id != project_id
            or any(
                item.silence_policy is not None
                and item.silence_policy.project_id != project_id
                for item in ordered_final_tracks
            )
        ):
            raise DeliveryPipelineError(
                "shidu.audio.revision_project_lineage_mismatch"
            )
        command_key_digest = hashlib.sha256(
            command_idempotency_key.encode("utf-8")
        ).hexdigest()
        delivery_request_digest = stable_json_sha256(
            {
                "schema_version": "factory.shidu-delivery-request.v1",
                "project_id": str(project_id),
                "audio_plan": plan.model_dump(mode="json"),
                "voice_preset_revision_id": str(
                    voice_preset.voice_preset_revision_id
                ),
                "voice_preset_digest": voice_preset.digest,
                "alignment_policy_revision_id": str(
                    alignment_policy.alignment_policy_revision_id
                ),
                "alignment_policy_digest": alignment_policy.digest,
                "final_tracks": [
                    item.model_dump(mode="json")
                    for item in ordered_final_tracks
                ],
            }
        )
        replays = tuple(
            item
            for item in state.delivery_takes
            if item.command_idempotency_key_digest == command_key_digest
        )
        if len(replays) > 1:
            raise DeliveryPipelineError(
                "shidu.audio.command_idempotency_state_conflict"
            )
        if replays:
            replay = replays[0]
            if replay.delivery_request_digest != delivery_request_digest:
                raise DeliveryPipelineError(
                    "shidu.audio.command_idempotency_conflict"
                )
            return state
        visual_sources = resolve_shidu_visual_sources(
            plan=plan,
            state=state,
            catalog=self.catalog,
        )
        (
            accepted_track_paths,
            accepted_track_refs,
            silence_bindings,
        ) = resolve_final_audio_tracks(
            tracks=ordered_final_tracks,
            project_id=project_id,
            duration_ms=plan.duration_ms,
            catalog=self.catalog,
            authority_resolver=final_audio_authority,
            probe_wav_bytes=probe_accepted_wav_bytes,
        )
        delivery_take_id = uuid5(
            _ALIGNMENT_NAMESPACE,
            f"delivery:{project_id}:{command_key_digest}",
        )
        output = (
            self.store.root / "artifacts" / "delivery" / str(delivery_take_id)
        )
        output.mkdir(parents=True, exist_ok=True)
        delivery_checkpoint = output / "delivery_take.json"
        if delivery_checkpoint.is_file():
            try:
                checkpoint_take = DeliveryTake.model_validate_json(
                    delivery_checkpoint.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise DeliveryPipelineError(
                    "shidu.audio.delivery_reconciliation_required"
                ) from exc
            if (
                checkpoint_take.delivery_take_id != delivery_take_id
                or checkpoint_take.delivery_request_digest
                != delivery_request_digest
                or checkpoint_take.command_idempotency_key_digest
                != command_key_digest
                or checkpoint_take.visual_take_ids != plan.visual_take_ids
            ):
                raise DeliveryPipelineError(
                    "shidu.audio.delivery_reconciliation_required"
                )
            checkpoint_refs = (
                checkpoint_take.audio_timeline_ref,
                checkpoint_take.dialogue_ref,
                checkpoint_take.subtitle_ref,
                checkpoint_take.final_composite_ref,
                *checkpoint_take.tts_audio_refs,
            )
            try:
                for reference in checkpoint_refs:
                    if reference is not None:
                        self.catalog.resolve(reference)
            except Exception as exc:
                raise DeliveryPipelineError(
                    "shidu.audio.delivery_reconciliation_required"
                ) from exc
            return self.store.record_delivery_take(
                checkpoint_take,
                expected_state_version=expected_state_version,
            )

        ordered_cues = tuple(
            sorted(plan.dialogue, key=lambda item: item.start_ms)
        )
        tts_takes: list[object] = []
        tts_paths: list[Path] = []
        tts_refs: list[ArtifactRef] = []
        for index, cue in enumerate(ordered_cues, start=1):
            destination = output / f"narration_{index:03d}.wav"
            take = materialize_shidu_tts_take(
                provider=self.tts,
                cue=cue,
                voice_preset=voice_preset,
                destination=destination,
                idempotency_key=(
                    f"{command_idempotency_key}:speech:{cue.cue_key}"
                ),
            )
            artifact = take.audio_artifact
            reference = ArtifactRef(
                owner=ComponentName.DRAMA_FACTORY,
                artifact_id=artifact.artifact_id,
                sha256=artifact.sha256,
                bytes=artifact.byte_size,
                mime=artifact.mime,
                version=1,
            )
            self.catalog.bind(
                reference,
                destination,
                role=f"shidu_tts_cue_{index:03d}",
                created_at=take.created_at,
            )
            tts_takes.append(take)
            tts_paths.append(destination)
            tts_refs.append(reference)

        try:
            alignment = compile_audio_alignment(
                plan=plan,
                takes=tuple(tts_takes),
                policy=alignment_policy,
            )
        except AlignmentRevisionRequired as exc:
            persist_alignment_revision_request(
                exc.request,
                output / "alignment_revision_request.json",
            )
            raise

        timeline_path = output / "audio_timeline.json"
        atomic_write_json(
            timeline_path,
            {
                "schema_version": "factory.shidu-audio-timeline.v1",
                "alignment_revision": alignment.model_dump(mode="json"),
                "final_tracks": [
                    item.model_dump(mode="json")
                    for item in ordered_final_tracks
                ],
                "speed_change_allowed": False,
            },
        )
        subtitle_path = output / "subtitles.srt"
        _write_aligned_srt(alignment, subtitle_path)

        dialogue_path, mix_path = materialize_shidu_audio_mix(
            plan=plan,
            alignment=alignment,
            tts_takes=tuple(tts_takes),
            tts_paths=tuple(tts_paths),
            accepted_track_paths=accepted_track_paths,
            output_dir=output,
        )
        _visual_concat_path, _muxed_path, final_path = (
            assemble_shidu_delivery(
                visual_sources=visual_sources,
                mix_path=mix_path,
                subtitle_path=subtitle_path,
                duration_ms=plan.duration_ms,
                output_dir=output,
            )
        )

        take = DeliveryTake(
            delivery_take_id=delivery_take_id,
            visual_take_id=plan.visual_take_id,
            visual_take_ids=plan.visual_take_ids,
            trial_script_revision_id=alignment.trial_script_revision_id,
            audio_alignment_revision_id=(
                alignment.audio_alignment_revision_id
            ),
            audio_alignment_digest=alignment.digest,
            command_idempotency_key_digest=command_key_digest,
            delivery_request_digest=delivery_request_digest,
            tts_take_ids=tuple(item.take_id for item in tts_takes),
            tts_audio_refs=tuple(tts_refs),
            silence_policy_bindings=silence_bindings,
            audio_timeline_ref=self._bind(
                timeline_path,
                mime="application/json",
                role="shidu_audio_timeline",
            ),
            dialogue_ref=self._bind(
                dialogue_path,
                mime="audio/wav",
                role="shidu_dialogue_track",
            ),
            ambience_ref=accepted_track_refs.get("ambience"),
            sfx_ref=accepted_track_refs.get("sfx"),
            music_ref=accepted_track_refs.get("music"),
            subtitle_ref=self._bind(
                subtitle_path,
                mime="application/x-subrip",
                role="shidu_subtitle_track",
            ),
            lipsync_video_ref=None,
            final_composite_ref=self._bind(
                final_path,
                mime="video/mp4",
                role="shidu_final_composite",
            ),
            eligibility=DeliveryEligibility.CANDIDATE,
            created_at=datetime.now(timezone.utc),
        )
        atomic_write_json(
            delivery_checkpoint,
            take.model_dump(mode="json"),
        )
        return self.store.record_delivery_take(
            take,
            expected_state_version=expected_state_version,
        )
