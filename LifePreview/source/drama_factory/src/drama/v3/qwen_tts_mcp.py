"""Strict Qwen3-TTS CustomVoice MCP boundary for Shidu narration.

The transport is injected deliberately.  Live MCP discovery/calling belongs to
the runtime composition root; this module never guesses a server, tool, schema,
speaker, or fallback provider when that live boundary is unavailable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Mapping, Protocol
from uuid import UUID, uuid5

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .audio_pipeline import DialogueCue
from .audio_quality import AudioQualityAnalyzer, AudioQualityResult


QWEN_TTS_PROVIDER_ID = "qwen3-tts-custom-voice-mcp"
QWEN_TTS_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
QWEN_TTS_TOOL_NAME = "qwen_tts.custom_voice"
QWEN_TTS_SCHEMA_DIGEST = (
    "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa"
)
DEFAULT_CHINESE_SPEAKERS = frozenset({"Serena", "Uncle_Fu"})
POLICY_GATED_CHINESE_SPEAKERS = frozenset({"Vivian", "Dylan"})
PHASE_TWO_CHINESE_SPEAKERS = (
    DEFAULT_CHINESE_SPEAKERS | POLICY_GATED_CHINESE_SPEAKERS
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TAKE_NAMESPACE = UUID("c47fd721-f1dd-47f5-81e4-398d15d9b3f2")
_CLONE_TERMS = ("voice clone", "reference audio", "clone", "克隆", "参考音频")
_MAX_TOTAL_RETRY_COUNT = 3


def _quality_retry_idempotency_key(
    idempotency_key: str,
    quality_retry_count: int,
) -> str:
    suffix = f":quality-retry:{quality_retry_count}"
    candidate = f"{idempotency_key}{suffix}"
    if len(candidate) <= 255:
        return candidate
    key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"tts:{key_digest}{suffix}"


class TTSContractError(RuntimeError):
    """The discovered or requested CustomVoice contract is not safe to call."""


class TTSInvocationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        classification: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.retryable = retryable


class TTSOutputRejected(TTSInvocationError):
    def __init__(self, defect_codes: tuple[str, ...]) -> None:
        super().__init__(
            "Qwen3-TTS output failed the pinned audio quality contract",
            classification="audio_qc_rejected",
            retryable=True,
        )
        self.defect_codes = defect_codes


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _canonical_digest(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _instruction_digest(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


class TTSServiceCapabilities(_FrozenModel):
    service_version: str = Field(min_length=1, max_length=100)
    model_id: Literal["Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"]
    tool_name: Literal["qwen_tts.custom_voice"]
    schema_digest: Literal[
        "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa"
    ]
    speakers: tuple[str, ...] = Field(min_length=1, max_length=100)

    @field_validator("service_version")
    @classmethod
    def service_version_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("service version must not be blank")
        return value

    @field_validator("speakers")
    @classmethod
    def speakers_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value) or len(set(value)) != len(value):
            raise ValueError("discovered speaker names must be unique and nonblank")
        return value


class VoicePresetRevision(_FrozenModel):
    voice_preset_revision_id: UUID
    project_id: UUID
    preset_key: str = Field(min_length=1, max_length=160)
    revision: int = Field(ge=1)
    provider: Literal["qwen3-tts-custom-voice-mcp"] = QWEN_TTS_PROVIDER_ID
    model_id: Literal[
        "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    ] = QWEN_TTS_MODEL_ID
    model_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    speaker: str = Field(min_length=1, max_length=100)
    language: Literal["Chinese"] = "Chinese"
    instruction: str | None = Field(default=None, max_length=300)
    instruction_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    applicable_book_categories: tuple[str, ...] = Field(max_length=32)
    default_gender: Literal["female", "male", "neutral"]
    enabled: bool
    discovery_service_version: str = Field(min_length=1, max_length=100)
    discovery_tool_name: Literal["qwen_tts.custom_voice"]
    discovery_schema_digest: Literal[
        "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa"
    ]
    discovered_speakers: tuple[str, ...] = Field(min_length=1, max_length=100)
    policy_allowed_speakers: tuple[str, ...] = Field(min_length=1, max_length=4)
    created_at: AwareDatetime
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("instruction")
    @classmethod
    def instruction_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        folded = value.casefold()
        if any(term in folded for term in _CLONE_TERMS):
            raise ValueError("instruction cannot request reference audio or voice cloning")
        return value

    @field_validator("applicable_book_categories")
    @classmethod
    def categories_are_unique(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("applicable book categories must be unique and nonblank")
        return normalized

    @field_validator("discovered_speakers", "policy_allowed_speakers")
    @classmethod
    def speaker_sets_are_unique(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(not item.strip() for item in value) or len(set(value)) != len(value):
            raise ValueError("voice preset speaker snapshots must be unique and nonblank")
        return value

    @model_validator(mode="after")
    def digest_matches_content(self):
        if (
            not DEFAULT_CHINESE_SPEAKERS.issubset(self.discovered_speakers)
            or not DEFAULT_CHINESE_SPEAKERS.issubset(
                self.policy_allowed_speakers
            )
            or not set(self.policy_allowed_speakers).issubset(
                PHASE_TWO_CHINESE_SPEAKERS
            )
            or self.speaker not in self.discovered_speakers
            or self.speaker not in self.policy_allowed_speakers
        ):
            raise ValueError("voice preset speaker discovery/policy is inconsistent")
        if self.digest != self.content_digest(
            project_id=self.project_id,
            preset_key=self.preset_key,
            revision=self.revision,
            model_digest=self.model_digest,
            speaker=self.speaker,
            language=self.language,
            instruction=self.instruction,
            instruction_digest=self.instruction_digest,
            applicable_book_categories=self.applicable_book_categories,
            default_gender=self.default_gender,
            enabled=self.enabled,
            discovery_service_version=self.discovery_service_version,
            discovery_tool_name=self.discovery_tool_name,
            discovery_schema_digest=self.discovery_schema_digest,
            discovered_speakers=self.discovered_speakers,
            policy_allowed_speakers=self.policy_allowed_speakers,
        ):
            raise ValueError("voice preset digest does not match immutable content")
        if self.instruction_digest != _instruction_digest(self.instruction):
            raise ValueError("voice preset instruction digest is inconsistent")
        return self

    @staticmethod
    def content_digest(
        *,
        project_id: UUID,
        preset_key: str,
        revision: int,
        model_digest: str,
        speaker: str,
        language: str,
        instruction: str | None,
        instruction_digest: str,
        applicable_book_categories: tuple[str, ...],
        default_gender: str,
        enabled: bool,
        discovery_service_version: str,
        discovery_tool_name: str,
        discovery_schema_digest: str,
        discovered_speakers: tuple[str, ...],
        policy_allowed_speakers: tuple[str, ...],
    ) -> str:
        return _canonical_digest(
            {
                "project_id": str(project_id),
                "preset_key": preset_key,
                "revision": revision,
                "provider": QWEN_TTS_PROVIDER_ID,
                "model_id": QWEN_TTS_MODEL_ID,
                "model_digest": model_digest,
                "speaker": speaker,
                "language": language,
                "instruction_digest": instruction_digest,
                "enabled": enabled,
                "discovery_service_version": discovery_service_version,
                "discovery_tool_name": discovery_tool_name,
                "discovery_schema_digest": discovery_schema_digest,
                "payload": {
                    "schema_version": "shidu-voice-preset.v1",
                    "instruction": instruction,
                    "applicable_book_categories": list(
                        applicable_book_categories
                    ),
                    "default_gender": default_gender,
                    "discovered_speakers": list(discovered_speakers),
                    "policy_allowed_speakers": list(policy_allowed_speakers),
                },
            }
        )

    @classmethod
    def create(cls, **values: object) -> VoicePresetRevision:
        created_at = values.get("created_at")
        if not isinstance(created_at, datetime):
            raise ValueError("voice preset created_at is required")
        instruction_digest = _instruction_digest(values.get("instruction"))
        digest = cls.content_digest(
            project_id=values["project_id"],
            preset_key=values["preset_key"],
            revision=values["revision"],
            model_digest=values["model_digest"],
            speaker=values["speaker"],
            language=values.get("language", "Chinese"),
            instruction=values.get("instruction"),
            instruction_digest=instruction_digest,
            applicable_book_categories=values["applicable_book_categories"],
            default_gender=values["default_gender"],
            enabled=values["enabled"],
            discovery_service_version=values["discovery_service_version"],
            discovery_tool_name=values["discovery_tool_name"],
            discovery_schema_digest=values["discovery_schema_digest"],
            discovered_speakers=values["discovered_speakers"],
            policy_allowed_speakers=values["policy_allowed_speakers"],
        )
        return cls(
            **values,
            instruction_digest=instruction_digest,
            digest=digest,
        )

    @classmethod
    def from_persisted(cls, value: object) -> VoicePresetRevision:
        try:
            payload = dict(getattr(value, "payload"))
            return cls(
                voice_preset_revision_id=getattr(value, "id"),
                project_id=getattr(value, "project_id"),
                preset_key=getattr(value, "preset_key"),
                revision=getattr(value, "revision"),
                provider=getattr(value, "provider"),
                model_id=getattr(value, "model_id"),
                model_digest=getattr(value, "model_digest"),
                speaker=getattr(value, "speaker"),
                language=getattr(value, "language"),
                instruction=payload["instruction"],
                instruction_digest=getattr(value, "instruction_digest"),
                applicable_book_categories=tuple(
                    payload["applicable_book_categories"]
                ),
                default_gender=payload["default_gender"],
                enabled=getattr(value, "enabled"),
                discovery_service_version=getattr(
                    value, "discovery_service_version"
                ),
                discovery_tool_name=getattr(value, "discovery_tool_name"),
                discovery_schema_digest=getattr(
                    value, "discovery_schema_digest"
                ),
                discovered_speakers=tuple(payload["discovered_speakers"]),
                policy_allowed_speakers=tuple(
                    payload["policy_allowed_speakers"]
                ),
                created_at=getattr(value, "created_at"),
                digest=getattr(value, "digest"),
            )
        except (AttributeError, KeyError, TypeError, ValidationError) as exc:
            raise TTSContractError(
                "persisted voice preset revision contract is invalid"
            ) from exc


class TTSInvocationIdentity(_FrozenModel):
    provider: Literal["qwen3-tts-custom-voice-mcp"]
    service_version: str = Field(min_length=1, max_length=100)
    model_id: Literal["Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"]
    tool_name: Literal["qwen_tts.custom_voice"]
    schema_digest: Literal[
        "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa"
    ]
    speaker: str = Field(min_length=1, max_length=100)
    language: Literal["Chinese"]


class AudioArtifactRef(_FrozenModel):
    artifact_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=44)
    mime: Literal["audio/wav"] = "audio/wav"


class TTSTake(_FrozenModel):
    take_id: UUID
    trial_script_revision_id: UUID
    cue_id: UUID
    cue_key: str = Field(min_length=1, max_length=160)
    voice_preset_revision_id: UUID
    voice_preset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested: TTSInvocationIdentity
    actual: TTSInvocationIdentity
    instruction_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_artifact: AudioArtifactRef
    audio_quality: AudioQualityResult
    retry_count: int = Field(ge=0, le=3)
    error_classification: None = None
    idempotency_key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lipsync_required: Literal[False] = False
    take_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class QwenTTSMCPTransport(Protocol):
    """Live implementations discover first, then call the discovered tool.

    A transport must return recorded response bytes and actual identity.  This
    protocol intentionally exposes neither a guessed default server nor a
    subprocess/Edge-TTS/tone fallback.
    """

    def discover(self) -> Mapping[str, object]: ...

    def call_custom_voice(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        idempotency_key: str,
        timeout_seconds: float,
    ) -> Mapping[str, object]: ...


class Qwen3TTSMCPProvider:
    def __init__(
        self,
        *,
        transport: QwenTTSMCPTransport,
        policy_allowed_speakers: tuple[str, ...] = ("Serena", "Uncle_Fu"),
        analyzer: AudioQualityAnalyzer | None = None,
        maximum_duration_overrun_seconds: float | None = None,
        timeout_seconds: float = 120.0,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
            or timeout_seconds > 600
        ):
            raise ValueError("TTS timeout must be finite and bounded")
        if maximum_duration_overrun_seconds is not None and (
            isinstance(maximum_duration_overrun_seconds, bool)
            or not isinstance(maximum_duration_overrun_seconds, (int, float))
            or not math.isfinite(float(maximum_duration_overrun_seconds))
            or maximum_duration_overrun_seconds < 0
            or maximum_duration_overrun_seconds > 5
        ):
            raise ValueError("TTS duration overrun must be finite and bounded")
        try:
            raw_capabilities = dict(transport.discover())
        except Exception as exc:
            raise TTSContractError("TTS discovery service is unavailable") from exc
        self.capabilities = self._parse_capabilities(raw_capabilities)
        allowed = frozenset(policy_allowed_speakers)
        if (
            not DEFAULT_CHINESE_SPEAKERS.issubset(allowed)
            or not allowed.issubset(PHASE_TWO_CHINESE_SPEAKERS)
        ):
            raise TTSContractError("TTS speaker policy is invalid")
        self._policy_allowed_speakers = allowed
        self._transport = transport
        self._analyzer = analyzer or AudioQualityAnalyzer()
        self._maximum_duration_overrun_seconds = (
            None
            if maximum_duration_overrun_seconds is None
            else float(maximum_duration_overrun_seconds)
        )
        self._timeout_seconds = float(timeout_seconds)
        self._clock = clock

    @staticmethod
    def _parse_capabilities(payload: dict[str, object]) -> TTSServiceCapabilities:
        checks = (
            (payload.get("service_version"), "service"),
            (payload.get("model_id") == QWEN_TTS_MODEL_ID, "model"),
            (payload.get("tool_name") == QWEN_TTS_TOOL_NAME, "tool"),
            (payload.get("schema_digest") == QWEN_TTS_SCHEMA_DIGEST, "schema"),
        )
        if not isinstance(checks[0][0], str) or not checks[0][0].strip():
            raise TTSContractError("TTS discovery service version is invalid")
        for valid, label in checks[1:]:
            if not valid:
                raise TTSContractError(f"TTS discovery {label} contract mismatch")
        try:
            capabilities = TTSServiceCapabilities.model_validate(payload)
        except ValidationError as exc:
            raise TTSContractError("TTS discovery contract is invalid") from exc
        if not DEFAULT_CHINESE_SPEAKERS.issubset(capabilities.speakers):
            raise TTSContractError("TTS discovery required speaker contract mismatch")
        return capabilities

    def synthesize(
        self,
        *,
        cue: DialogueCue,
        voice_preset: VoicePresetRevision,
        destination: Path,
        idempotency_key: str,
    ) -> TTSTake:
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 255:
            raise TTSContractError("TTS idempotency key is required and bounded")
        destination = Path(destination)
        if destination.suffix.lower() != ".wav" or destination.exists():
            raise TTSContractError("TTS destination must be a new WAV target")
        self._validate_binding(cue, voice_preset)

        arguments: dict[str, object] = {
            "text": cue.text,
            "language": voice_preset.language,
            "speaker": voice_preset.speaker,
            "instruct": voice_preset.instruction or "",
            "model_id": QWEN_TTS_MODEL_ID,
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        planned_duration_seconds = (cue.end_ms - cue.start_ms) / 1000
        quality_retry_count = 0
        while True:
            invocation_key = (
                idempotency_key
                if quality_retry_count == 0
                else _quality_retry_idempotency_key(
                    idempotency_key,
                    quality_retry_count,
                )
            )
            response = self._invoke_custom_voice(
                arguments=arguments,
                idempotency_key=invocation_key,
            )
            actual = self._validate_response_identity(
                response,
                voice_preset,
            )
            upstream_retry_count = response.get("retry_count", 0)
            if (
                isinstance(upstream_retry_count, bool)
                or not isinstance(upstream_retry_count, int)
                or not 0 <= upstream_retry_count <= _MAX_TOTAL_RETRY_COUNT
                or response.get("error_classification") is not None
            ):
                raise TTSContractError(
                    "TTS retry/error result contract mismatch"
                )
            audio_bytes = self._audio_bytes(response)
            temporary = destination.with_name(
                f".{destination.name}."
                f"{uuid5(_TAKE_NAMESPACE, invocation_key)}.partial"
            )
            if temporary.exists():
                raise TTSContractError(
                    "TTS temporary destination already exists"
                )
            try:
                temporary.write_bytes(audio_bytes)
                quality = self._analyzer.inspect(
                    temporary,
                    planned_duration_seconds=planned_duration_seconds,
                )
                if not quality.accepted:
                    raise TTSOutputRejected(quality.defect_codes)
                if (
                    self._maximum_duration_overrun_seconds is not None
                    and quality.duration_seconds - planned_duration_seconds
                    > self._maximum_duration_overrun_seconds
                ):
                    raise TTSOutputRejected(("duration_overrun",))
                retry_count = quality_retry_count + upstream_retry_count
                if retry_count > _MAX_TOTAL_RETRY_COUNT:
                    temporary.unlink(missing_ok=True)
                    destination.unlink(missing_ok=True)
                    raise TTSContractError(
                        "TTS combined retry count exceeds the contract"
                    )
                audio_digest = hashlib.sha256(audio_bytes).hexdigest()
                os.replace(temporary, destination)
                break
            except TTSOutputRejected:
                temporary.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                if (
                    quality_retry_count >= _MAX_TOTAL_RETRY_COUNT
                    or quality_retry_count + upstream_retry_count
                    >= _MAX_TOTAL_RETRY_COUNT
                ):
                    raise
                quality_retry_count += 1
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                raise TTSInvocationError(
                    "Qwen3-TTS audio artifact could not be materialized",
                    classification="artifact_write_failed",
                    retryable=True,
                ) from exc

        requested = TTSInvocationIdentity(
            provider=QWEN_TTS_PROVIDER_ID,
            service_version=self.capabilities.service_version,
            model_id=QWEN_TTS_MODEL_ID,
            tool_name=QWEN_TTS_TOOL_NAME,
            schema_digest=QWEN_TTS_SCHEMA_DIGEST,
            speaker=voice_preset.speaker,
            language=voice_preset.language,
        )
        request_digest = _canonical_digest(
            {
                "trial_script_revision_id": str(cue.trial_script_revision_id),
                "cue_id": str(cue.cue_id),
                "cue_key": cue.cue_key,
                "text_digest": hashlib.sha256(cue.text.encode("utf-8")).hexdigest(),
                "voice_preset_revision_id": str(voice_preset.voice_preset_revision_id),
                "voice_preset_digest": voice_preset.digest,
                "identity": requested.model_dump(mode="json"),
                "instruction_digest": voice_preset.instruction_digest,
            }
        )
        key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        artifact_id = uuid5(_TAKE_NAMESPACE, f"artifact:{key_digest}:{audio_digest}")
        take_id = uuid5(_TAKE_NAMESPACE, f"take:{key_digest}:{request_digest}:{audio_digest}")
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise TTSContractError("TTS clock must return an aware timestamp")
        artifact = AudioArtifactRef(
            artifact_id=artifact_id,
            sha256=audio_digest,
            byte_size=len(audio_bytes),
        )
        take_payload = {
            "take_id": str(take_id),
            "trial_script_revision_id": str(cue.trial_script_revision_id),
            "cue_id": str(cue.cue_id),
            "cue_key": cue.cue_key,
            "voice_preset_revision_id": str(voice_preset.voice_preset_revision_id),
            "voice_preset_digest": voice_preset.digest,
            "request_digest": request_digest,
            "requested": requested.model_dump(mode="json"),
            "actual": actual.model_dump(mode="json"),
            "instruction_digest": voice_preset.instruction_digest,
            "audio_artifact": artifact.model_dump(mode="json"),
            "audio_quality": quality.model_dump(mode="json"),
            "retry_count": retry_count,
            "error_classification": None,
            "idempotency_key_digest": key_digest,
            "lipsync_required": False,
            "created_at": created_at.isoformat(),
        }
        return TTSTake(
            take_id=take_id,
            trial_script_revision_id=cue.trial_script_revision_id,
            cue_id=cue.cue_id,
            cue_key=cue.cue_key,
            voice_preset_revision_id=voice_preset.voice_preset_revision_id,
            voice_preset_digest=voice_preset.digest,
            request_digest=request_digest,
            requested=requested,
            actual=actual,
            instruction_digest=voice_preset.instruction_digest,
            audio_artifact=artifact,
            audio_quality=quality,
            retry_count=retry_count,
            idempotency_key_digest=key_digest,
            take_digest=_canonical_digest(take_payload),
            created_at=created_at,
        )

    def _invoke_custom_voice(
        self,
        *,
        arguments: dict[str, object],
        idempotency_key: str,
    ) -> dict[str, object]:
        try:
            return dict(
                self._transport.call_custom_voice(
                    tool_name=self.capabilities.tool_name,
                    arguments=arguments,
                    idempotency_key=idempotency_key,
                    timeout_seconds=self._timeout_seconds,
                )
            )
        except TimeoutError as exc:
            raise TTSInvocationError(
                "Qwen3-TTS MCP request timed out",
                classification="transport_timeout",
                retryable=True,
            ) from exc
        except (ConnectionError, OSError) as exc:
            raise TTSInvocationError(
                "Qwen3-TTS MCP service is unavailable",
                classification="transport_unavailable",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise TTSInvocationError(
                "Qwen3-TTS MCP invocation failed",
                classification="provider_error",
                retryable=False,
            ) from exc

    def _validate_binding(
        self, cue: DialogueCue, voice_preset: VoicePresetRevision
    ) -> None:
        if voice_preset.speaker not in self._policy_allowed_speakers:
            raise TTSContractError("voice preset speaker is blocked by project policy")
        if voice_preset.speaker not in self.capabilities.speakers:
            raise TTSContractError("voice preset speaker was not discovered")
        if voice_preset.speaker not in PHASE_TWO_CHINESE_SPEAKERS:
            raise TTSContractError("voice preset speaker is outside Phase 2 policy")
        if voice_preset.model_id != QWEN_TTS_MODEL_ID:
            raise TTSContractError("voice preset model contract mismatch")
        if voice_preset.provider != QWEN_TTS_PROVIDER_ID:
            raise TTSContractError("voice preset provider contract mismatch")
        if (
            voice_preset.discovery_service_version
            != self.capabilities.service_version
        ):
            raise TTSContractError("voice preset discovery service contract mismatch")
        if (
            voice_preset.discovery_tool_name != self.capabilities.tool_name
            or voice_preset.discovery_schema_digest
            != self.capabilities.schema_digest
        ):
            raise TTSContractError("voice preset discovery tool/schema contract mismatch")
        if set(voice_preset.discovered_speakers) != set(
            self.capabilities.speakers
        ):
            raise TTSContractError("voice preset discovered speaker snapshot is stale")
        if set(voice_preset.policy_allowed_speakers) != set(
            self._policy_allowed_speakers
        ):
            raise TTSContractError("voice preset speaker policy does not match provider policy")
        if not voice_preset.enabled:
            raise TTSContractError("voice preset revision is disabled")
        if cue.trial_script_revision_id is None or cue.cue_key is None:
            raise TTSContractError("TTS cue requires an exact trial script revision and cue key")
        if (
            cue.speaker != voice_preset.speaker
            or cue.language != voice_preset.language
            or (cue.instruction or None) != voice_preset.instruction
        ):
            raise TTSContractError("TTS cue and voice preset contract mismatch")
        try:
            VoicePresetRevision.model_validate(voice_preset.model_dump())
            DialogueCue.model_validate(cue.model_dump())
        except ValidationError as exc:
            raise TTSContractError("TTS cue or voice preset revision is invalid") from exc

    def _validate_response_identity(
        self,
        response: dict[str, object],
        preset: VoicePresetRevision,
    ) -> TTSInvocationIdentity:
        expected = {
            "provider": QWEN_TTS_PROVIDER_ID,
            "service_version": self.capabilities.service_version,
            "model_id": QWEN_TTS_MODEL_ID,
            "tool_name": QWEN_TTS_TOOL_NAME,
            "schema_digest": QWEN_TTS_SCHEMA_DIGEST,
            "speaker": preset.speaker,
            "language": preset.language,
        }
        for field, value in expected.items():
            if response.get(field) != value:
                raise TTSContractError(f"TTS actual {field.replace('_', ' ')} contract mismatch")
        try:
            return TTSInvocationIdentity.model_validate(expected)
        except ValidationError as exc:
            raise TTSContractError("TTS actual identity contract is invalid") from exc

    @staticmethod
    def _audio_bytes(response: dict[str, object]) -> bytes:
        raw = response.get("audio_bytes")
        if isinstance(raw, bytes):
            audio = raw
        else:
            encoded = response.get("audio_base64")
            if not isinstance(encoded, str) or not encoded:
                raise TTSContractError("TTS response does not contain WAV bytes")
            try:
                audio = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise TTSContractError("TTS response WAV encoding is invalid") from exc
        if len(audio) > 100 * 1024 * 1024:
            raise TTSContractError("TTS response WAV size is invalid")
        return audio


__all__ = [
    "AudioArtifactRef",
    "QWEN_TTS_MODEL_ID",
    "QWEN_TTS_PROVIDER_ID",
    "QWEN_TTS_SCHEMA_DIGEST",
    "QWEN_TTS_TOOL_NAME",
    "Qwen3TTSMCPProvider",
    "QwenTTSMCPTransport",
    "TTSContractError",
    "TTSInvocationError",
    "TTSInvocationIdentity",
    "TTSOutputRejected",
    "TTSTake",
    "TTSServiceCapabilities",
    "VoicePresetRevision",
]
