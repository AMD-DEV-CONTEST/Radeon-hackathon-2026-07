"""Fail-closed production wiring for the independent Shidu API."""

from __future__ import annotations

import hmac
import hashlib
import json
import math
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared_contracts import ArtifactRef, AtomicArtifactRef, ComponentName

from creative_hub.artifact_proxy import RemoteArtifact
from creative_hub.artifact_publication import (
    ArtifactUnavailable as PublishedArtifactUnavailable,
    ContentAddressedArtifactStore,
    PostgresArtifactRepository,
)
from creative_hub.artifacts import (
    ArtifactCorrupt,
    ArtifactMediaTypeRejected,
    ArtifactNotFound,
    ArtifactResolver,
    StoredArtifact,
    iter_file_range,
)
from creative_hub.dag_execution import DurableDagScheduler
from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import QCPromptRevisionRecord
from creative_hub.episode_compiler import compile_shidu_trial_workflow
from creative_hub.h3_workflow_compiler import (
    H3_BASE_INPUT_ROLE_ORDER,
    H3_HISTORICAL_INPUT_ROLE_ORDER,
    H3SubmissionPolicyAuthority,
    compile_h3_workflow_submission,
)
from creative_hub.runtime_bootstrap import (
    database_url,
    load_atomic_capability_registry,
)
from creative_hub.media_gateway import (
    SAFE_BROWSER_MEDIA_TYPES,
    RangeNotSatisfiable,
    parse_single_range,
)
from creative_hub.qc_policy import EvaluatorPin, FactoryQCPolicyPayload
from creative_hub.shidu.book_discovery_service import BookDiscoveryService
from creative_hub.shidu.mcp_transport import HttpMCPTransport
from creative_hub.shidu.providers import (
    CodingPlanPageReaderMCPProvider,
    CodingPlanSearchMCPProvider,
)
from creative_hub.shidu.repository import ShiduRepository
from creative_hub.shidu.trial_safety import require_trial_script_release
from creative_hub.shidu.url_security import ReaderURLGuard
from creative_hub.workflow_catalog import WorkflowMaterializer
from drama.v3.audio_pipeline import (
    AudioAlignmentPolicyRevision,
    FinalAudioTrack,
)
from drama.v3.qwen_tts_mcp import TTSContractError, VoicePresetRevision

from .services import (
    DependencyUnavailable,
    SqlAlchemyShiduService,
    WorkflowSubmission,
    WorkflowSubmitter,
)


_AUTHORITY_SCHEMA = "shidu-audio-authority-bundle.v1"
_TRIAL_SCRIPT_SCHEMA = "factory.shidu-trial-script.v1"
_FINAL_AUDIO_ROLES = ("ambience", "sfx", "music")
_MAX_AUTHORITY_BYTES = 1024 * 1024
_DEFAULT_SEARCH_MCP_ENDPOINT = "http://shidu-search-mcp:18110/invoke"
_DEFAULT_READER_MCP_ENDPOINT = "http://shidu-reader-mcp:18111/invoke"


@dataclass(frozen=True, slots=True)
class ProjectedTrialScript:
    shot_keys: tuple[str, ...]
    cue_keys: tuple[str, ...]
    shot_payloads: tuple[Mapping[str, Any], ...]
    cue_payloads: tuple[Mapping[str, Any], ...]
    digest: str


@dataclass(frozen=True, slots=True)
class AudioAuthorityBundle:
    project_id: UUID
    alignment_policy: AudioAlignmentPolicyRevision
    final_audio_tracks: tuple[FinalAudioTrack, ...]
    digest: str


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"trial script {field} is invalid")
    return value.strip()


def project_trial_script(
    *,
    script_revision_id: UUID,
    payload: Mapping[str, Any],
) -> ProjectedTrialScript:
    """Convert one validated creative script into the frozen factory shape."""

    if not isinstance(script_revision_id, UUID) or not isinstance(
        payload, Mapping
    ):
        raise ValueError("trial script projection input is invalid")
    raw_shots = payload.get("shots")
    raw_cues = payload.get("narration_cues")
    if (
        not isinstance(raw_shots, list)
        or not isinstance(raw_cues, list)
        or len(raw_shots) != 6
        or len(raw_cues) != 6
    ):
        raise ValueError("trial script projection requires six shots and cues")

    shots: list[dict[str, Any]] = []
    cues: list[dict[str, Any]] = []
    cue_keys: list[str] = []
    cursor = 0.0
    for expected, (raw_shot, raw_cue) in enumerate(
        zip(raw_shots, raw_cues, strict=True),
        start=1,
    ):
        if not isinstance(raw_shot, Mapping) or not isinstance(
            raw_cue, Mapping
        ):
            raise ValueError("trial script shot or cue is invalid")
        if raw_shot.get("ordinal") != expected:
            raise ValueError("trial script shot ordinals are invalid")
        try:
            duration = float(raw_shot["duration_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("trial script shot duration is invalid") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("trial script shot duration is invalid")

        action = _required_text(raw_shot.get("action"), "action")
        composition = _required_text(
            raw_shot.get("composition"), "composition"
        )
        camera = _required_text(
            raw_shot.get("camera_movement"), "camera_movement"
        )
        lighting = _required_text(raw_shot.get("lighting"), "lighting")
        sound = _required_text(raw_shot.get("sound"), "sound")
        state_before = _required_text(
            raw_shot.get("state_before"), "state_before"
        )
        state_after = _required_text(
            raw_shot.get("state_after"), "state_after"
        )
        unit_key = f"shot-{expected:03d}"
        shots.append(
            {
                "unit_key": unit_key,
                "shot_id": str(
                    uuid5(
                        NAMESPACE_URL,
                        f"shidu:trial-shot:{script_revision_id}:{expected}",
                    )
                ),
                "ordinal": expected,
                "prompt": (
                    f"{action}；构图：{composition}；运镜：{camera}；"
                    f"光线：{lighting}；声音：{sound}；"
                    f"状态变化：{state_before}→{state_after}"
                ),
                "generation_mode": "i2v",
            }
        )

        cue_key = _required_text(raw_cue.get("cue_key"), "cue_key")
        if cue_key in cue_keys or len(cue_key) > 160:
            raise ValueError("trial script cue keys are invalid")
        cue_keys.append(cue_key)
        text = _required_text(raw_cue.get("text"), "cue text")
        pause_after_ms = raw_cue.get("pause_after_ms", 0)
        if (
            not isinstance(pause_after_ms, int)
            or isinstance(pause_after_ms, bool)
            or not 0 <= pause_after_ms <= 10_000
        ):
            raise ValueError("trial script cue pause is invalid")
        start = cursor
        cursor += duration
        cues.append(
            {
                "cue_id": str(
                    uuid5(
                        NAMESPACE_URL,
                        f"shidu:trial-cue:{script_revision_id}:{cue_key}",
                    )
                ),
                "cue_key": cue_key,
                "text": text,
                "start_time": start,
                "end_time": cursor,
                "pause_after_ms": pause_after_ms,
            }
        )

    if not 50.0 <= cursor <= 70.0:
        raise ValueError("trial script duration must be between 50 and 70 seconds")
    frozen = {
        "schema_version": _TRIAL_SCRIPT_SCHEMA,
        "shots": shots,
        "narration_cues": cues,
    }
    serialized = json.dumps(
        frozen,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).casefold()
    if "lipsync" in serialized or "fallback" in serialized:
        raise ValueError("trial script projection contains a forbidden operation")
    return ProjectedTrialScript(
        shot_keys=tuple(item["unit_key"] for item in shots),
        cue_keys=tuple(cue_keys),
        shot_payloads=tuple(MappingProxyType(item) for item in shots),
        cue_payloads=tuple(MappingProxyType(item) for item in cues),
        digest=canonical_json_digest(frozen),
    )


def audio_authority_bundle_digest(payload: Mapping[str, Any]) -> str:
    material = dict(payload)
    material.pop("digest", None)
    return canonical_json_digest(material)


def load_audio_authority_bundle(
    path: Path | str,
    *,
    expected_project_id: UUID,
) -> AudioAuthorityBundle:
    """Load immutable operator-provisioned audio authorities from one file."""

    location = Path(path)
    try:
        if (
            location.is_symlink()
            or not location.is_file()
            or location.stat().st_size > _MAX_AUTHORITY_BYTES
        ):
            raise OSError
        raw = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("audio authority file is unreadable") from None
    if not isinstance(raw, dict) or raw.get("schema_version") != _AUTHORITY_SCHEMA:
        raise ValueError("audio authority schema is invalid")
    try:
        project_id = UUID(str(raw["project_id"]))
        digest = str(raw["digest"])
        alignment = AudioAlignmentPolicyRevision.model_validate(
            raw["alignment_policy"]
        )
        tracks = tuple(
            FinalAudioTrack.model_validate(item)
            for item in raw["final_audio_tracks"]
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("audio authority content is invalid") from None
    if project_id != expected_project_id:
        raise ValueError("audio authority project does not match deployment")
    if digest != audio_authority_bundle_digest(raw):
        raise ValueError("audio authority digest does not match content")
    if alignment.project_id != project_id:
        raise ValueError("audio authority alignment project is invalid")
    if tuple(item.role for item in tracks) != _FINAL_AUDIO_ROLES:
        raise ValueError("audio authority track roles are invalid")
    for track in tracks:
        silence = track.silence_policy
        if silence is not None and silence.project_id != project_id:
            raise ValueError("audio authority silence project is invalid")
    return AudioAuthorityBundle(
        project_id=project_id,
        alignment_policy=alignment,
        final_audio_tracks=tracks,
        digest=digest,
    )


def resolve_shidu_qc_policy(
    session: Session,
    *,
    project_id: UUID,
    capability_registry: Any,
) -> FactoryQCPolicyPayload:
    """Pin every Shidu QC stage to exact prompt and evaluator authorities."""

    if not getattr(capability_registry, "is_frozen", False):
        raise DependencyUnavailable()
    defaults = FactoryQCPolicyPayload(stages={})
    stages = {}
    for stage_name in ("keyframe", "clip", "final"):
        stage = defaults.stages[stage_name]
        op_type = f"qc.evaluate.{stage_name}"
        registrations = [
            item
            for item in capability_registry.registrations.values()
            if item.spec.op_type == op_type
        ]
        if len(registrations) != 1:
            raise DependencyUnavailable()
        registration = registrations[0]
        prompt = session.scalar(
            select(QCPromptRevisionRecord)
            .where(
                QCPromptRevisionRecord.project_id == project_id,
                QCPromptRevisionRecord.stage == stage_name,
                QCPromptRevisionRecord.prompt_key == stage.prompt_version,
            )
            .order_by(QCPromptRevisionRecord.revision.desc())
            .limit(1)
        )
        if (
            prompt is None
            or prompt.project_id != project_id
            or prompt.stage != stage_name
            or prompt.prompt_key != stage.prompt_version
            or not isinstance(prompt.revision, int)
            or prompt.revision < 1
        ):
            raise DependencyUnavailable()
        try:
            pin = EvaluatorPin(
                prompt_revision_id=prompt.id,
                prompt_digest=prompt.prompt_digest,
                rubric_digest=canonical_json_digest(
                    {
                        "stage": stage_name,
                        "rubric_version": stage.rubric_version,
                    }
                ),
                operation_spec_digest=registration.spec.spec_digest,
                implementation_digest=(
                    registration.implementation_manifest.implementation_digest
                ),
            )
        except (AttributeError, TypeError, ValueError):
            raise DependencyUnavailable() from None
        stages[stage_name] = stage.model_copy(
            update={"evaluator_pin": pin}
        )
    return FactoryQCPolicyPayload(stages=stages)


class H3AuthorityResolutionUnavailable(RuntimeError):
    """The trusted H3 authority resolver could not complete infrastructure I/O."""


def _canonical_digest_without(payload: Mapping[str, Any], field: str) -> str:
    identity = dict(payload)
    identity.pop(field, None)
    return canonical_json_digest(identity)


def h3_persisted_artifact_authority_digest(
    payload: Mapping[str, Any],
) -> str:
    """Digest one durable external-revision to artifact publication binding."""

    return _canonical_digest_without(payload, "authority_digest")


class H3PersistedArtifactAuthority(BaseModel):
    """Append-only publication receipt for one H3 authority artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["factory.shidu-h3-artifact-authority.v1"]
    external_revision_id: UUID
    external_revision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_ref: AtomicArtifactRef
    publication_fencing_token: int = Field(ge=1)
    authority_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def receipt_is_canonical(self) -> H3PersistedArtifactAuthority:
        actual = h3_persisted_artifact_authority_digest(
            self.model_dump(mode="json", exclude={"authority_digest"})
        )
        if not hmac.compare_digest(actual, self.authority_digest):
            raise ValueError("persisted H3 artifact authority digest mismatch")
        if isinstance(self.publication_fencing_token, bool):
            raise ValueError("artifact publication fencing token is invalid")
        return self


def h3_persisted_visual_identity_authority_digest(
    payload: Mapping[str, Any],
) -> str:
    """Digest one independently persisted visual-identity resolution."""

    return _canonical_digest_without(payload, "authority_digest")


class H3PersistedVisualIdentityAuthority(BaseModel):
    """Durable visual selection/synthesis authority loaded outside the request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["factory.shidu-h3-visual-authority.v1"]
    project_id: UUID
    visual_identity_mode: Literal[
        "historical_image_grounded",
        "script_synthesized",
    ]
    visual_identity_resolution_id: UUID
    visual_identity_resolution_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    basis_kind: Literal["searched_historical", "script_synthesized"]
    selected_basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified: bool
    historical: bool
    non_ai: bool
    ai_derived: bool
    trial_script_revision_id: UUID
    trial_script_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_pack_revision_id: UUID
    evidence_pack_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    appearance_spec_revision_id: UUID | None = None
    appearance_spec_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    authority_artifact: H3PersistedArtifactAuthority
    source_artifact: H3PersistedArtifactAuthority | None = None
    selected_source_artifact_id: UUID | None = None
    selected_source_content_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    selected_source_fencing_token: int | None = Field(default=None, ge=1)
    authority_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def resolution_is_canonical(self) -> H3PersistedVisualIdentityAuthority:
        actual = h3_persisted_visual_identity_authority_digest(
            self.model_dump(mode="json", exclude={"authority_digest"})
        )
        if not hmac.compare_digest(actual, self.authority_digest):
            raise ValueError("persisted H3 visual authority digest mismatch")
        authority = self.authority_artifact
        if (
            authority.artifact_ref.project_id != self.project_id
            or authority.artifact_ref.logical_role
            != "h3.visual-identity-resolution.authority"
            or authority.artifact_ref.mime_type != "application/json"
            or authority.external_revision_id
            != self.visual_identity_resolution_id
            or not hmac.compare_digest(
                authority.external_revision_digest,
                self.visual_identity_resolution_digest,
            )
        ):
            raise ValueError("visual resolution authority publication is invalid")
        source_fields = (
            self.selected_source_artifact_id,
            self.selected_source_content_digest,
            self.selected_source_fencing_token,
        )
        if self.visual_identity_mode == "historical_image_grounded":
            if (
                self.basis_kind != "searched_historical"
                or (self.verified, self.historical, self.non_ai, self.ai_derived)
                != (True, True, True, False)
                or self.source_artifact is None
                or any(value is None for value in source_fields)
                or self.appearance_spec_revision_id is not None
                or self.appearance_spec_digest is not None
            ):
                raise ValueError("historical visual identity semantics are invalid")
            source = self.source_artifact
            assert source is not None
            if (
                source.artifact_ref.project_id != self.project_id
                or source.artifact_ref.logical_role != "character.source.image"
                or source.artifact_ref.mime_type
                not in {"image/jpeg", "image/png", "image/webp"}
                or source.artifact_ref.artifact_id
                != self.selected_source_artifact_id
                or not hmac.compare_digest(
                    str(source.artifact_ref.content_digest),
                    str(self.selected_source_content_digest),
                )
                or source.publication_fencing_token
                != self.selected_source_fencing_token
                or source.external_revision_id
                != self.selected_source_artifact_id
                or not hmac.compare_digest(
                    source.external_revision_digest,
                    str(self.selected_source_content_digest),
                )
            ):
                raise ValueError("historical source publication binding is invalid")
        elif (
            self.basis_kind != "script_synthesized"
            or (self.verified, self.historical, self.non_ai, self.ai_derived)
            != (False, False, False, True)
            or self.source_artifact is not None
            or any(value is not None for value in source_fields)
            or self.appearance_spec_revision_id is None
            or self.appearance_spec_digest is None
        ):
            raise ValueError("script-synthesized visual identity semantics are invalid")
        return self


def h3_persisted_workflow_authority_record_digest(
    payload: Mapping[str, Any],
) -> str:
    """Digest the append-only authority-store row consumed by H3 submission."""

    return _canonical_digest_without(payload, "record_digest")


class H3PersistedWorkflowAuthorityRecord(BaseModel):
    """Independent durable authority-store record for one H3 submission."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["factory.shidu-h3-persisted-authorities.v1"]
    project_id: UUID
    book_id: UUID
    direction_revision_id: UUID
    direction_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_script_revision_id: UUID
    research_job_id: UUID
    research_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_pack_revision_id: UUID
    safety_release_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_authority: H3PersistedArtifactAuthority
    trial_script_authority: H3PersistedArtifactAuthority
    evidence_pack_authority: H3PersistedArtifactAuthority
    visual_identity_authority: H3PersistedVisualIdentityAuthority
    policy_authority: H3SubmissionPolicyAuthority
    record_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def record_is_canonical(self) -> H3PersistedWorkflowAuthorityRecord:
        actual = h3_persisted_workflow_authority_record_digest(
            self.model_dump(mode="json", exclude={"record_digest"})
        )
        if not hmac.compare_digest(actual, self.record_digest):
            raise ValueError("persisted H3 authority record digest mismatch")
        expected = (
            (
                self.project_authority,
                "h3.project.authority",
                self.book_id,
                self.project_authority.external_revision_digest,
            ),
            (
                self.trial_script_authority,
                "h3.trial-script.authority",
                self.trial_script_revision_id,
                self.visual_identity_authority.trial_script_digest,
            ),
            (
                self.evidence_pack_authority,
                "h3.evidence-pack.authority",
                self.evidence_pack_revision_id,
                self.visual_identity_authority.evidence_pack_digest,
            ),
        )
        for authority, role, revision_id, revision_digest in expected:
            ref = authority.artifact_ref
            if (
                ref.project_id != self.project_id
                or ref.logical_role != role
                or ref.mime_type != "application/json"
                or authority.external_revision_id != revision_id
                or not hmac.compare_digest(
                    authority.external_revision_digest,
                    revision_digest,
                )
            ):
                raise ValueError("persisted H3 authority role binding is invalid")
        visual = self.visual_identity_authority
        if (
            visual.project_id != self.project_id
            or visual.trial_script_revision_id
            != self.trial_script_revision_id
            or visual.evidence_pack_revision_id
            != self.evidence_pack_revision_id
        ):
            raise ValueError("persisted visual authority lineage is invalid")
        return self


class H3PersistedAuthorityStore(Protocol):
    """Read an append-only H3 authority record from an independent store."""

    def load_authorities(
        self,
        *,
        session: Session,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
    ) -> H3PersistedWorkflowAuthorityRecord: ...


class JsonFileH3PersistedAuthorityStore:
    """Read canonical append-only authority receipts from a durable root."""

    _MAX_RECORD_BYTES = 4 * 1024 * 1024

    def __init__(self, root: str | Path) -> None:
        configured = Path(root)
        if not configured.is_absolute():
            configured = configured.resolve()
        self._root = configured

    def authority_path(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
    ) -> Path:
        if not all(
            type(value) is UUID
            for value in (
                project_id,
                book_id,
                direction_revision_id,
                trial_script_revision_id,
            )
        ):
            raise ValueError("H3 authority store identifiers are invalid")
        return (
            self._root
            / str(project_id)
            / str(book_id)
            / str(direction_revision_id)
            / f"{trial_script_revision_id}.json"
        )

    def load_authorities(
        self,
        *,
        session: Session,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
    ) -> H3PersistedWorkflowAuthorityRecord:
        del session
        path = self.authority_path(
            project_id=project_id,
            book_id=book_id,
            direction_revision_id=direction_revision_id,
            trial_script_revision_id=trial_script_revision_id,
        )
        try:
            resolved_root = self._root.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
            if not resolved_path.is_relative_to(resolved_root):
                raise ValueError("H3 authority record escapes its durable root")
            size = resolved_path.stat().st_size
            if not 0 < size <= self._MAX_RECORD_BYTES:
                raise ValueError("H3 authority record size is invalid")
            payload = resolved_path.read_bytes()
        except FileNotFoundError as exc:
            raise H3AuthorityResolutionUnavailable() from exc
        except OSError as exc:
            raise H3AuthorityResolutionUnavailable() from exc
        try:
            return H3PersistedWorkflowAuthorityRecord.model_validate_json(
                payload,
                strict=True,
            )
        except ValueError as exc:
            raise ValueError("persisted H3 authority record is invalid") from exc


def h3_visual_identity_binding_digest(payload: Mapping[str, Any]) -> str:
    """Return the canonical identity of a visual-resolution/source binding."""

    identity = dict(payload)
    identity.pop("attestation_digest", None)
    return canonical_json_digest(identity)


class H3VisualIdentityBindingAttestation(BaseModel):
    """Resolver attestation tying visual authority to the selected source."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["factory.shidu-h3-visual-binding.v1"]
    visual_identity_mode: Literal[
        "historical_image_grounded",
        "script_synthesized",
    ]
    visual_identity_resolution_id: UUID
    visual_identity_resolution_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    authority_artifact_id: UUID
    authority_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_id: UUID | None = None
    source_artifact_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    selected_basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified: bool
    historical: bool
    non_ai: bool
    ai_derived: bool
    source_publication_fencing_token: int | None = Field(default=None, ge=1)
    appearance_spec_revision_id: UUID | None = None
    appearance_spec_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    attestation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def binding_is_complete(self) -> H3VisualIdentityBindingAttestation:
        actual = h3_visual_identity_binding_digest(
            self.model_dump(mode="json", exclude={"attestation_digest"})
        )
        if not hmac.compare_digest(actual, self.attestation_digest):
            raise ValueError("H3 visual binding attestation digest mismatch")
        has_source = (
            self.source_artifact_id is not None
            and self.source_artifact_digest is not None
        )
        if (self.source_artifact_id is None) != (
            self.source_artifact_digest is None
        ):
            raise ValueError("H3 visual binding source identity is incomplete")
        if self.visual_identity_mode == "historical_image_grounded":
            if (
                not has_source
                or (self.verified, self.historical, self.non_ai, self.ai_derived)
                != (True, True, True, False)
                or self.source_publication_fencing_token is None
                or self.appearance_spec_revision_id is not None
                or self.appearance_spec_digest is not None
            ):
                raise ValueError("historical visual binding requires a source")
        elif (
            has_source
            or (self.verified, self.historical, self.non_ai, self.ai_derived)
            != (False, False, False, True)
            or self.source_publication_fencing_token is not None
            or self.appearance_spec_revision_id is None
            or self.appearance_spec_digest is None
        ):
            raise ValueError(
                "script-synthesized visual binding requires appearance authority"
            )
        return self


def h3_authority_bundle_digest(payload: Mapping[str, Any]) -> str:
    """Return the canonical identity of one resolver-produced H3 bundle."""

    identity = dict(payload)
    identity.pop("bundle_digest", None)
    return canonical_json_digest(identity)


class H3WorkflowAuthorityBundle(BaseModel):
    """Frozen repository and visual authorities for one H3 submission.

    A resolver may return this bundle only after loading and cross-checking the
    book, direction, trial script, research job, evidence pack, safety release,
    and visual-identity resolution from durable stores.  Transport/provider
    failures must be raised as :class:`H3AuthorityResolutionUnavailable`; they
    must never be converted to ``script_synthesized``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["factory.shidu-h3-authority-bundle.v1"]
    project_id: UUID
    book_id: UUID
    book_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    direction_revision_id: UUID
    direction_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_script_revision_id: UUID
    trial_script_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    research_job_id: UUID
    research_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_pack_revision_id: UUID
    evidence_pack_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    safety_release_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    visual_identity_mode: Literal[
        "historical_image_grounded",
        "script_synthesized",
    ]
    visual_identity_resolution_id: UUID
    visual_identity_resolution_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    requested_sequence_duration_seconds: float = Field(ge=3.0, le=15.0)
    sequence_count: int = Field(ge=1, le=12)
    input_artifact_refs: tuple[AtomicArtifactRef, ...]
    visual_binding_attestation: H3VisualIdentityBindingAttestation
    policy_authority: H3SubmissionPolicyAuthority
    persisted_authority_record_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def authorities_are_canonical(self) -> H3WorkflowAuthorityBundle:
        actual = h3_authority_bundle_digest(
            self.model_dump(mode="json", exclude={"bundle_digest"})
        )
        if not hmac.compare_digest(actual, self.bundle_digest):
            raise ValueError("H3 authority bundle digest mismatch")
        if isinstance(self.sequence_count, bool):
            raise ValueError("H3 sequence count must be an integer")
        if not math.isfinite(self.requested_sequence_duration_seconds):
            raise ValueError("H3 sequence duration must be finite")

        expected_roles = (
            H3_HISTORICAL_INPUT_ROLE_ORDER
            if self.visual_identity_mode == "historical_image_grounded"
            else H3_BASE_INPUT_ROLE_ORDER
        )
        if tuple(ref.logical_role for ref in self.input_artifact_refs) != (
            expected_roles
        ):
            raise ValueError("H3 authority bundle role order is invalid")
        if any(
            ref.project_id != self.project_id
            for ref in self.input_artifact_refs
        ):
            raise ValueError("H3 authority bundle project lineage is invalid")
        artifact_ids = tuple(
            ref.artifact_id for ref in self.input_artifact_refs
        )
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("H3 authority bundle artifact identity repeats")

        refs = {ref.logical_role: ref for ref in self.input_artifact_refs}
        visual = refs["h3.visual-identity-resolution.authority"]
        binding = self.visual_binding_attestation
        if (
            binding.visual_identity_mode != self.visual_identity_mode
            or binding.visual_identity_resolution_id
            != self.visual_identity_resolution_id
            or binding.visual_identity_resolution_digest
            != self.visual_identity_resolution_digest
            or binding.authority_artifact_id != visual.artifact_id
            or not hmac.compare_digest(
                binding.authority_artifact_digest,
                str(visual.content_digest),
            )
        ):
            raise ValueError("H3 visual authority binding is invalid")

        source = refs.get("character.source.image")
        if self.visual_identity_mode == "historical_image_grounded":
            if source is None or (
                binding.source_artifact_id != source.artifact_id
                or not hmac.compare_digest(
                    str(binding.source_artifact_digest),
                    str(source.content_digest),
                )
            ):
                raise ValueError("H3 historical source binding is invalid")
        elif (
            source is not None
            or binding.source_artifact_id is not None
            or binding.source_artifact_digest is not None
        ):
            raise ValueError("H3 script synthesis must not carry a source")
        return self


class H3WorkflowAuthorityResolver(Protocol):
    """Load and verify all durable H3 submission authorities."""

    def resolve(
        self,
        *,
        session: Session,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
        requested_sequence_duration_seconds: float,
        sequence_count: int,
    ) -> H3WorkflowAuthorityBundle: ...


class PersistentH3WorkflowAuthorityResolver:
    """Cross-bind repository facts with an independent append-only authority store."""

    def __init__(
        self,
        *,
        authority_store: H3PersistedAuthorityStore,
        repository_factory: Callable[[Session], Any] = ShiduRepository,
    ) -> None:
        loader = getattr(authority_store, "load_authorities", None)
        if not callable(loader) or not callable(repository_factory):
            raise ValueError("persistent H3 authority resolver is invalid")
        self._store = authority_store
        self._repositories = repository_factory

    @staticmethod
    def _validated_record(value: object) -> H3PersistedWorkflowAuthorityRecord:
        if not isinstance(value, H3PersistedWorkflowAuthorityRecord):
            raise ValueError("persisted H3 authority store returned invalid data")
        try:
            return H3PersistedWorkflowAuthorityRecord.model_validate(
                value.model_dump(mode="python"),
                strict=True,
            )
        except ValueError as exc:
            raise ValueError("persisted H3 authority validation failed") from exc

    def resolve(
        self,
        *,
        session: Session,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
        requested_sequence_duration_seconds: float,
        sequence_count: int,
    ) -> H3WorkflowAuthorityBundle:
        repository = self._repositories(session)
        book = repository.get_book(project_id, book_id)
        (
            script,
            _methodology,
            direction,
            pack,
            _claims,
            _sources,
        ) = repository.load_trial_script_context(trial_script_revision_id)
        research = repository.get_research_job(pack.research_job_id)
        release = require_trial_script_release(script.payload)
        record = self._validated_record(
            self._store.load_authorities(
                session=session,
                project_id=project_id,
                book_id=book_id,
                direction_revision_id=direction_revision_id,
                trial_script_revision_id=trial_script_revision_id,
            )
        )

        visual = record.visual_identity_authority
        if (
            book.project_id != project_id
            or script.project_id != project_id
            or script.book_id != book.id
            or script.resonance_direction_revision_id != direction.id
            or direction.id != direction_revision_id
            or direction.project_id != project_id
            or direction.evidence_pack_revision_id != pack.id
            or pack.project_id != project_id
            or not pack.publishable
            or research.id != pack.research_job_id
            or research.project_id != project_id
            or research.book_id != book.id
            or research.status != "ready"
            or record.project_id != project_id
            or record.book_id != book.id
            or record.direction_revision_id != direction.id
            or record.trial_script_revision_id != script.id
            or record.research_job_id != research.id
            or record.evidence_pack_revision_id != pack.id
            or record.project_authority.external_revision_id != book.id
            or not hmac.compare_digest(
                record.project_authority.external_revision_digest,
                book.identity_digest,
            )
            or record.trial_script_authority.external_revision_id != script.id
            or not hmac.compare_digest(
                record.trial_script_authority.external_revision_digest,
                script.digest,
            )
            or record.evidence_pack_authority.external_revision_id != pack.id
            or not hmac.compare_digest(
                record.evidence_pack_authority.external_revision_digest,
                pack.digest,
            )
            or not hmac.compare_digest(record.direction_digest, direction.digest)
            or not hmac.compare_digest(record.research_digest, research.digest)
            or not hmac.compare_digest(
                record.safety_release_decision_digest,
                release.release_decision_digest,
            )
            or visual.trial_script_revision_id != script.id
            or not hmac.compare_digest(visual.trial_script_digest, script.digest)
            or visual.evidence_pack_revision_id != pack.id
            or not hmac.compare_digest(visual.evidence_pack_digest, pack.digest)
        ):
            raise ValueError("persisted H3 authority lineage is invalid")

        refs = (
            record.project_authority.artifact_ref,
            record.trial_script_authority.artifact_ref,
            record.evidence_pack_authority.artifact_ref,
            visual.authority_artifact.artifact_ref,
            *(
                (visual.source_artifact.artifact_ref,)
                if visual.source_artifact is not None
                else ()
            ),
        )
        source = visual.source_artifact
        binding_identity = {
            "schema_version": "factory.shidu-h3-visual-binding.v1",
            "visual_identity_mode": visual.visual_identity_mode,
            "visual_identity_resolution_id": str(
                visual.visual_identity_resolution_id
            ),
            "visual_identity_resolution_digest": (
                visual.visual_identity_resolution_digest
            ),
            "authority_artifact_id": str(
                visual.authority_artifact.artifact_ref.artifact_id
            ),
            "authority_artifact_digest": str(
                visual.authority_artifact.artifact_ref.content_digest
            ),
            "source_artifact_id": (
                str(source.artifact_ref.artifact_id)
                if source is not None
                else None
            ),
            "source_artifact_digest": (
                str(source.artifact_ref.content_digest)
                if source is not None
                else None
            ),
            "selected_basis_digest": visual.selected_basis_digest,
            "verified": visual.verified,
            "historical": visual.historical,
            "non_ai": visual.non_ai,
            "ai_derived": visual.ai_derived,
            "source_publication_fencing_token": (
                source.publication_fencing_token
                if source is not None
                else None
            ),
            "appearance_spec_revision_id": (
                str(visual.appearance_spec_revision_id)
                if visual.appearance_spec_revision_id is not None
                else None
            ),
            "appearance_spec_digest": visual.appearance_spec_digest,
        }
        binding = H3VisualIdentityBindingAttestation.model_validate(
            {
                **binding_identity,
                "visual_identity_resolution_id": (
                    visual.visual_identity_resolution_id
                ),
                "authority_artifact_id": (
                    visual.authority_artifact.artifact_ref.artifact_id
                ),
                "source_artifact_id": (
                    source.artifact_ref.artifact_id
                    if source is not None
                    else None
                ),
                "appearance_spec_revision_id": (
                    visual.appearance_spec_revision_id
                ),
                "attestation_digest": h3_visual_identity_binding_digest(
                    binding_identity
                ),
            },
            strict=True,
        )
        bundle_identity = {
            "schema_version": "factory.shidu-h3-authority-bundle.v1",
            "project_id": str(project_id),
            "book_id": str(book.id),
            "book_digest": book.identity_digest,
            "direction_revision_id": str(direction.id),
            "direction_digest": direction.digest,
            "trial_script_revision_id": str(script.id),
            "trial_script_digest": script.digest,
            "research_job_id": str(research.id),
            "research_digest": research.digest,
            "evidence_pack_revision_id": str(pack.id),
            "evidence_pack_digest": pack.digest,
            "safety_release_decision_digest": release.release_decision_digest,
            "visual_identity_mode": visual.visual_identity_mode,
            "visual_identity_resolution_id": str(
                visual.visual_identity_resolution_id
            ),
            "visual_identity_resolution_digest": (
                visual.visual_identity_resolution_digest
            ),
            "requested_sequence_duration_seconds": (
                requested_sequence_duration_seconds
            ),
            "sequence_count": sequence_count,
            "input_artifact_refs": [
                ref.model_dump(mode="json") for ref in refs
            ],
            "visual_binding_attestation": binding.model_dump(mode="json"),
            "policy_authority": record.policy_authority.model_dump(mode="json"),
            "persisted_authority_record_digest": record.record_digest,
        }
        return H3WorkflowAuthorityBundle.model_validate(
            {
                **bundle_identity,
                "project_id": project_id,
                "book_id": book.id,
                "direction_revision_id": direction.id,
                "trial_script_revision_id": script.id,
                "research_job_id": research.id,
                "evidence_pack_revision_id": pack.id,
                "visual_identity_resolution_id": (
                    visual.visual_identity_resolution_id
                ),
                "input_artifact_refs": refs,
                "visual_binding_attestation": binding,
                "policy_authority": record.policy_authority,
                "bundle_digest": h3_authority_bundle_digest(bundle_identity),
            },
            strict=True,
        )


_H3_FORBIDDEN_REQUEST_AUTHORITIES = frozenset(
    {
        "voicepresetrevisionid",
        "voiceauthority",
        "ttspolicy",
        "audioalignmentpolicyrevisionid",
        "audioauthority",
        "subtitleauthority",
        "subtitlepolicy",
    }
)


@contextmanager
def _h3_submission_transaction(
    session_factory: Callable[[], Session],
) -> Iterator[Session]:
    """Map database/infrastructure failures across the whole transaction.

    This boundary includes session creation, transaction begin, materializer
    flushes, and commit.  Contract and lineage ``ValueError`` exceptions are
    intentionally not translated so malformed authorities never masquerade as
    retryable infrastructure failures.
    """

    try:
        with session_factory() as session, session.begin():
            yield session
    except ValueError:
        raise
    except (
        H3AuthorityResolutionUnavailable,
        OperationalError,
        DBAPIError,
        ConnectionError,
        OSError,
        TimeoutError,
    ) as exc:
        raise DependencyUnavailable() from exc


class ProductionH3WorkflowSubmitter:
    """Resolve, compile, materialize, and re-attest an H3 workflow run."""

    # The public click first records an idempotent durable job.  The background
    # vertical-slice runner prepares the historical-image/FLUX authority and
    # then invokes this submitter; no GPU work is permitted before that click.
    defer_until_authority_ready = True

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        capability_registry: Any,
        authority_resolver: PersistentH3WorkflowAuthorityResolver,
        observability: object | None = None,
    ) -> None:
        if not getattr(capability_registry, "is_frozen", False):
            raise ValueError("capability registry must be frozen")
        if not isinstance(
            authority_resolver,
            PersistentH3WorkflowAuthorityResolver,
        ):
            raise ValueError("persistent H3 authority resolver is required")
        self._sessions = session_factory
        self._registry = capability_registry
        self._resolver = authority_resolver
        self._observability = observability

    @staticmethod
    def _request_authority(
        project_id: UUID,
        request: Mapping[str, Any],
    ) -> tuple[UUID, UUID, UUID, float, int, str, str, str]:
        if not isinstance(project_id, UUID) or not isinstance(request, Mapping):
            raise ValueError("H3 workflow selection is invalid")
        normalized_keys = {
            "".join(
                character
                for character in str(key).casefold()
                if character.isalnum()
            )
            for key in request
        }
        if normalized_keys & _H3_FORBIDDEN_REQUEST_AUTHORITIES:
            raise ValueError("H3 request contains a legacy audio authority")
        if (
            request.get("nativeAudio") is not True
            or request.get("subtitles") is not False
        ):
            raise ValueError("H3 request media authority is invalid")
        try:
            book_id = UUID(str(request["bookId"]))
            direction_id = UUID(str(request["directionRevisionId"]))
            script_id = UUID(str(request["trialScriptRevisionId"]))
            raw_duration = request["targetDurationSeconds"]
            raw_count = request["sequenceCount"]
            if isinstance(raw_duration, bool) or not isinstance(
                raw_duration,
                (int, float),
            ):
                raise ValueError
            duration = float(raw_duration)
            if not math.isfinite(duration) or not 3.0 <= duration <= 15.0:
                raise ValueError
            if (
                isinstance(raw_count, bool)
                or not isinstance(raw_count, int)
                or not 1 <= raw_count <= 12
            ):
                raise ValueError
            content_mode = str(request["contentMode"])
            content_label = str(request["contentLabel"]).strip()
            content_notice = str(request["contentNotice"]).strip()
            if (
                content_mode not in {"source_grounded", "ai_completed"}
                or not content_label
                or not content_notice
                or (
                    content_mode == "ai_completed"
                    and "非原文"
                    not in f"{content_label}{content_notice}"
                )
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError("H3 workflow selection is invalid") from None
        return (
            book_id,
            direction_id,
            script_id,
            duration,
            raw_count,
            content_mode,
            content_label,
            content_notice,
        )

    @staticmethod
    def _validated_bundle(
        value: object,
    ) -> H3WorkflowAuthorityBundle:
        if not isinstance(value, H3WorkflowAuthorityBundle):
            raise ValueError("H3 authority resolver returned an invalid bundle")
        try:
            return H3WorkflowAuthorityBundle.model_validate(
                value.model_dump(mode="python"),
                strict=True,
            )
        except ValueError as exc:
            raise ValueError("H3 authority bundle validation failed") from exc

    def submit(
        self,
        *,
        project_id: UUID,
        request: Mapping[str, Any],
        command_idempotency_key: str,
        created_by_actor: str,
    ) -> WorkflowSubmission:
        (
            book_id,
            direction_id,
            script_id,
            duration,
            sequence_count,
            content_mode,
            content_label,
            content_notice,
        ) = self._request_authority(project_id, request)
        if (
            not isinstance(command_idempotency_key, str)
            or not command_idempotency_key.strip()
            or not isinstance(created_by_actor, str)
            or not created_by_actor.strip()
        ):
            raise ValueError("H3 workflow command identity is invalid")

        with _h3_submission_transaction(self._sessions) as session:
            try:
                resolved = self._resolver.resolve(
                    session=session,
                    project_id=project_id,
                    book_id=book_id,
                    direction_revision_id=direction_id,
                    trial_script_revision_id=script_id,
                    requested_sequence_duration_seconds=duration,
                    sequence_count=sequence_count,
                )
            except ValueError:
                raise
            except (
                H3AuthorityResolutionUnavailable,
                OperationalError,
                DBAPIError,
                ConnectionError,
                OSError,
                TimeoutError,
            ) as exc:
                raise DependencyUnavailable() from exc
            bundle = self._validated_bundle(resolved)
            if (
                bundle.project_id != project_id
                or bundle.book_id != book_id
                or bundle.direction_revision_id != direction_id
                or bundle.trial_script_revision_id != script_id
                or bundle.requested_sequence_duration_seconds != duration
                or bundle.sequence_count != sequence_count
            ):
                raise ValueError("H3 resolved authority lineage is invalid")

            compiled = compile_h3_workflow_submission(
                project_id=project_id,
                input_artifact_refs=bundle.input_artifact_refs,
                requested_sequence_duration_seconds=duration,
                sequence_count=sequence_count,
                visual_identity_mode=bundle.visual_identity_mode,
                visual_identity_resolution_id=(
                    bundle.visual_identity_resolution_id
                ),
                visual_identity_resolution_digest=(
                    bundle.visual_identity_resolution_digest
                ),
                policy_authority=bundle.policy_authority,
            )
            input_payload = {
                **compiled.input_payload,
                "authority_bundle_digest": bundle.bundle_digest,
                "persisted_authority_record_digest": (
                    bundle.persisted_authority_record_digest
                ),
                "book_id": str(bundle.book_id),
                "book_digest": bundle.book_digest,
                "direction_revision_id": str(bundle.direction_revision_id),
                "direction_digest": bundle.direction_digest,
                "trial_script_revision_id": str(
                    bundle.trial_script_revision_id
                ),
                "trial_script_digest": bundle.trial_script_digest,
                "research_job_id": str(bundle.research_job_id),
                "research_digest": bundle.research_digest,
                "evidence_pack_revision_id": str(
                    bundle.evidence_pack_revision_id
                ),
                "evidence_pack_digest": bundle.evidence_pack_digest,
                "safety_release_decision_digest": (
                    bundle.safety_release_decision_digest
                ),
                "visual_identity_mode": bundle.visual_identity_mode,
                "visual_identity_resolution_id": str(
                    bundle.visual_identity_resolution_id
                ),
                "visual_identity_resolution_digest": (
                    bundle.visual_identity_resolution_digest
                ),
                "content_mode": content_mode,
                "content_label": content_label,
                "content_notice": content_notice,
            }
            materialized = WorkflowMaterializer(
                session=session,
                scheduler=DurableDagScheduler(
                    session,
                    budget_guard=None,
                    observability=self._observability,
                ),
                capability_registry=self._registry,
            ).materialize(
                project_id=project_id,
                definition=compiled.definition,
                command_idempotency_key=command_idempotency_key,
                input_payload=input_payload,
                policy_snapshot=compiled.policy_snapshot,
                created_by_actor=created_by_actor,
            )
            expected_operations = tuple(
                node.key for node in compiled.definition.nodes
            )
            if (
                materialized.run.project_id != project_id
                or not hmac.compare_digest(
                    str(materialized.run.input_digest),
                    canonical_json_digest(input_payload),
                )
                or not hmac.compare_digest(
                    str(materialized.run.policy_digest),
                    compiled.policy_digest,
                )
                or tuple(materialized.operations) != expected_operations
            ):
                raise DependencyUnavailable()
            return WorkflowSubmission(
                workflow_run_id=materialized.run.id,
                project_id=project_id,
                workflow_key=compiled.definition.workflow_key,
                book_id=bundle.book_id,
                trial_script_revision_id=bundle.trial_script_revision_id,
                voice_preset_revision_id=None,
                audio_alignment_policy_revision_id=None,
                visual_identity_resolution_id=(
                    bundle.visual_identity_resolution_id
                ),
                target_duration_seconds=(
                    duration * sequence_count
                ),
                sequence_count=sequence_count,
                input_authority_digest=compiled.input_authority_digest,
            )


class ProductionWorkflowSubmitter:
    """Load trusted durable inputs, compile, and materialize the real DAG."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        capability_registry: Any,
        voice_preset_revision_id: UUID,
        audio_authorities: AudioAuthorityBundle,
        observability: object | None = None,
    ) -> None:
        if not getattr(capability_registry, "is_frozen", False):
            raise ValueError("capability registry must be frozen")
        self._sessions = session_factory
        self._registry = capability_registry
        self._voice_id = voice_preset_revision_id
        self._audio = audio_authorities
        self._observability = observability

    def submit(
        self,
        *,
        project_id: UUID,
        request: Mapping[str, Any],
        command_idempotency_key: str,
        created_by_actor: str,
    ) -> WorkflowSubmission:
        try:
            book_id = UUID(str(request["bookId"]))
            direction_id = UUID(str(request["directionRevisionId"]))
            script_id = UUID(str(request["trialScriptRevisionId"]))
            content_mode = str(request["contentMode"])
            content_label = str(request["contentLabel"]).strip()
            content_notice = str(request["contentNotice"]).strip()
            if (
                content_mode not in {"source_grounded", "ai_completed"}
                or not content_label
                or not content_notice
                or (
                    content_mode == "ai_completed"
                    and "非原文" not in f"{content_label}{content_notice}"
                )
            ):
                raise ValueError("invalid content disclosure")
        except (KeyError, TypeError, ValueError):
            raise ValueError("Shidu workflow selection is invalid") from None
        if project_id != self._audio.project_id:
            raise ValueError("audio authority project does not match request")

        with self._sessions() as session, session.begin():
            repository = ShiduRepository(session)
            book = repository.get_book(project_id, book_id)
            script, _methodology, direction, pack, _claims, _sources = (
                repository.load_trial_script_context(script_id)
            )
            safety = require_trial_script_release(script.payload)
            if (
                script.project_id != project_id
                or script.book_id != book.id
                or script.resonance_direction_revision_id != direction_id
                or direction.id != direction_id
                or not pack.publishable
            ):
                raise ValueError("Shidu workflow selection lineage is invalid")
            persisted_voice = repository.get_voice_preset_revision(
                self._voice_id
            )
            created_at = persisted_voice.created_at
            if created_at.tzinfo is None:
                persisted_voice = replace(
                    persisted_voice,
                    created_at=created_at.replace(tzinfo=timezone.utc),
                )
            try:
                voice = VoicePresetRevision.from_persisted(persisted_voice)
            except TTSContractError as exc:
                raise DependencyUnavailable() from exc
            if (
                voice.project_id != project_id
                or not voice.enabled
                or safety.primary_category.value
                not in voice.applicable_book_categories
            ):
                raise ValueError("voice preset is not authorized for this book")

            projected = project_trial_script(
                script_revision_id=script.id,
                payload=script.payload,
            )
            qc_policy = resolve_shidu_qc_policy(
                session,
                project_id=project_id,
                capability_registry=self._registry,
            )
            alignment = self._audio.alignment_policy
            compiled = compile_shidu_trial_workflow(
                project_id=project_id,
                book_id=book.id,
                trial_script_revision_id=script.id,
                trial_script_digest=projected.digest,
                voice_preset_revision_id=voice.voice_preset_revision_id,
                voice_preset_digest=voice.digest,
                voice_preset_payload=voice.model_dump(mode="json"),
                audio_alignment_policy_revision_id=(
                    alignment.alignment_policy_revision_id
                ),
                audio_alignment_policy_digest=alignment.digest,
                audio_alignment_policy_payload=alignment.model_dump(
                    mode="json"
                ),
                final_audio_tracks_payload=tuple(
                    item.model_dump(mode="json")
                    for item in self._audio.final_audio_tracks
                ),
                shot_keys=projected.shot_keys,
                cue_keys=projected.cue_keys,
                shot_payloads=projected.shot_payloads,
                cue_payloads=projected.cue_payloads,
                policy_overrides={
                    "factory_qc_policy": qc_policy.model_dump(mode="json")
                },
            )
            materialized = WorkflowMaterializer(
                session=session,
                scheduler=DurableDagScheduler(
                    session,
                    budget_guard=None,
                    observability=self._observability,
                ),
                capability_registry=self._registry,
            ).materialize(
                project_id=project_id,
                definition=compiled.definition,
                command_idempotency_key=command_idempotency_key,
                input_payload={
                    "schema_version": "shidu-video-job-submission.v1",
                    "book_id": str(book.id),
                    "direction_revision_id": str(direction.id),
                    "trial_script_revision_id": str(script.id),
                    "content_mode": content_mode,
                    "content_label": content_label,
                    "content_notice": content_notice,
                    "repository_trial_script_digest": script.digest,
                    "factory_trial_script_digest": projected.digest,
                    "compiled_definition_digest": compiled.definition_digest,
                    "compiled_run_identity": compiled.run_identity,
                    "safety_release_decision_digest": (
                        safety.release_decision_digest
                    ),
                    "audio_authority_bundle_digest": self._audio.digest,
                },
                policy_snapshot=compiled.policy_snapshot,
                created_by_actor=created_by_actor,
            )
            return WorkflowSubmission(
                workflow_run_id=materialized.run.id,
                project_id=project_id,
                workflow_key=compiled.definition.workflow_key,
                book_id=book.id,
                trial_script_revision_id=script.id,
                voice_preset_revision_id=voice.voice_preset_revision_id,
                audio_alignment_policy_revision_id=(
                    alignment.alignment_policy_revision_id
                ),
            )


class _PostgresCasCatalog:
    def __init__(
        self,
        *,
        repository: Any,
        store: ContentAddressedArtifactStore,
        project_id: UUID,
    ) -> None:
        self._repository = repository
        self._store = store
        self._project_id = project_id

    def get(
        self,
        owner: ComponentName,
        artifact_id: UUID,
    ) -> StoredArtifact | None:
        if owner is not ComponentName.DRAMA_FACTORY:
            return None
        try:
            record = self._repository.get_visible(
                project_id=self._project_id,
                artifact_id=artifact_id,
            )
        except PublishedArtifactUnavailable:
            return None
        if (
            getattr(record, "artifact_id", None) != artifact_id
            or getattr(record, "project_id", None) != self._project_id
        ):
            return None
        return StoredArtifact(
            ref=ArtifactRef(
                owner=ComponentName.DRAMA_FACTORY,
                artifact_id=artifact_id,
                sha256=record.content_digest,
                bytes=record.byte_size,
                mime=record.mime_type,
                version=1,
            ),
            path=self._store.object_path(record.content_digest),
        )


class LocalCasArtifactGateway:
    """Project-scoped, digest-verifying browser gateway for Hub CAS files."""

    def __init__(
        self,
        *,
        repository: Any,
        store: ContentAddressedArtifactStore,
        project_id: UUID,
    ) -> None:
        catalog = _PostgresCasCatalog(
            repository=repository,
            store=store,
            project_id=project_id,
        )
        self._resolver = ArtifactResolver(
            owner_roots={ComponentName.DRAMA_FACTORY: store.objects_root},
            catalog=catalog,
            chunk_size=store.chunk_size,
        )

    @staticmethod
    def _headers(*, digest: str, mime: str) -> dict[str, str]:
        return {
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Type": mime,
            "ETag": f'"sha256-{digest}"',
            "X-Content-Type-Options": "nosniff",
        }

    def open(
        self,
        owner: str,
        artifact_id: UUID,
        *,
        method: str,
        headers: dict[str, str],
    ) -> RemoteArtifact:
        if method not in {"GET", "HEAD"}:
            return RemoteArtifact(404, {}, None)
        try:
            artifact = self._resolver.resolve_identity(owner, artifact_id)
        except ArtifactNotFound:
            return RemoteArtifact(404, {}, None)
        except ArtifactMediaTypeRejected:
            return RemoteArtifact(415, {}, None)
        except ArtifactCorrupt:
            return RemoteArtifact(409, {}, None)
        if artifact.ref.mime not in SAFE_BROWSER_MEDIA_TYPES:
            return RemoteArtifact(415, {}, None)

        response_headers = self._headers(
            digest=artifact.ref.sha256,
            mime=artifact.ref.mime,
        )
        etag = response_headers["ETag"]
        if headers.get("If-None-Match") == etag:
            return RemoteArtifact(304, response_headers, None)

        size = artifact.ref.bytes
        selected = None
        range_header = headers.get("Range")
        if range_header and headers.get("If-Range", etag) == etag:
            try:
                selected = parse_single_range(range_header, size)
            except RangeNotSatisfiable:
                response_headers["Content-Range"] = f"bytes */{size}"
                return RemoteArtifact(416, response_headers, None)
        if selected is None:
            start = 0
            length = size
            status = 200
        else:
            start = selected.start
            length = selected.length
            status = 206
            response_headers["Content-Range"] = (
                f"bytes {selected.start}-{selected.end}/{size}"
            )
        response_headers["Content-Length"] = str(length)
        if method == "HEAD":
            return RemoteArtifact(status, response_headers, None)

        def body() -> Iterator[bytes]:
            yield from iter_file_range(
                artifact.path,
                start=start,
                length=length,
                chunk_size=self._resolver.chunk_size,
            )

        return RemoteArtifact(status, response_headers, body())


def _required_uuid(name: str) -> UUID:
    try:
        return UUID(os.environ[name])
    except (KeyError, ValueError):
        raise RuntimeError("Shidu production adapters are not configured") from None


def _session_factory() -> Callable[[], Session]:
    try:
        url = database_url("CREATIVE_ORCHESTRATION")
        engine = create_engine(url, pool_pre_ping=True)
    except (RuntimeError, ValueError):
        raise RuntimeError("Shidu production adapters are not configured") from None
    return sessionmaker(bind=engine, expire_on_commit=False)


def _competition_runtime_proof_reader(
    *, project_id: UUID, job_authority_digest: str
) -> dict[str, Any] | None:
    """Project the current FLUX/H3 runtime-proof phase from a checkpoint."""

    from .competition_prepared_reference_backend import (
        IMPORTED_REFERENCE_SHA256,
    )

    if (
        not isinstance(project_id, UUID)
        or type(job_authority_digest) is not str
        or len(job_authority_digest) != 64
        or any(char not in "0123456789abcdef" for char in job_authority_digest)
    ):
        raise ValueError("runtime proof authority is invalid")
    root = Path(os.environ["AMD_ROOT"]).resolve(strict=True)
    target = (
        root
        / "vertical-slice"
        / "jobs"
        / job_authority_digest
        / "runner-checkpoint.json"
    )
    if not target.exists():
        return None
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("runtime proof checkpoint is unsafe")
    resolved = target.resolve(strict=True)
    resolved.relative_to(root)
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return None
    expected_logical = str(
        uuid5(NAMESPACE_URL, f"amd-three-second-prompt:{job_authority_digest}")
    )
    expected_nonce = hashlib.sha256(
        f"amd-three-second-nonce:{job_authority_digest}".encode()
    ).hexdigest()[:32]
    if (
        value.get("schemaVersion") != "amd.three-second-runner.v1"
        or value.get("logicalPromptId") != expected_logical
        or value.get("clickSubmissionNonce") != expected_nonce
    ):
        raise ValueError("runtime proof checkpoint diverges from the clicked job")
    h3 = value.get("h3")
    flux = value.get("flux")
    if isinstance(h3, dict) and h3.get("status") in {"queued", "running"}:
        phase = "h3"
        row = h3
        nonce = row.get("submissionNonce")
        if not isinstance(flux, dict):
            raise ValueError("H3 runtime proof has no imported reference authority")
        views = flux.get("views")
        reference = (
            views.get("front_three_quarter")
            if isinstance(views, dict)
            else None
        )
        if (
            not isinstance(reference, dict)
            or reference.get("status") != "succeeded"
            or reference.get("viewName") != "front_three_quarter"
            or reference.get("sourceMode") != "preuploaded_imported"
            or reference.get("generatedByCurrentFlux") is not False
            or reference.get("fluxOutputUsed") is not False
            or reference.get("outputSha256") != IMPORTED_REFERENCE_SHA256
            or type(reference.get("importAuthoritySha256")) is not str
            or len(reference["importAuthoritySha256"]) != 64
            or any(
                char not in "0123456789abcdef"
                for char in reference["importAuthoritySha256"]
            )
        ):
            raise ValueError("H3 imported reference lineage is invalid")
        reference_sha = IMPORTED_REFERENCE_SHA256
        gpu_observed = False
        process_exited = False
    elif isinstance(h3, dict) and h3:
        # Once H3 exists, a completed/failed/non-live H3 phase must never
        # fall back to an older FLUX proof.
        return None
    elif isinstance(flux, dict) and isinstance(flux.get("runtimeProof"), dict):
        row = flux["runtimeProof"]
        if row.get("status") not in {
            "queued",
            "gpu_activity_observed",
            "stopped_after_gpu_activity",
        }:
            return None
        phase = "flux"
        nonce = row.get("submissionNonce")
        activity = row.get("gpuActivity")
        gpu_observed = (
            isinstance(activity, dict)
            and activity.get("gpuActivityObserved") is True
        )
        process_exited = row.get("processExited") is True
        reference_sha = None
    else:
        return None
    prompt_id = row.get("promptId")
    queue_id = row.get("queueId")
    workflow_sha = row.get("workflowSha256")
    if (
        (
            phase == "h3"
            and nonce != expected_nonce
        )
        or (
            phase == "flux"
            and nonce
            != hashlib.sha256(
                f"{expected_nonce}:flux:runtime-proof".encode("utf-8")
            ).hexdigest()[:32]
        )
        or type(prompt_id) is not str
        or not 1 <= len(prompt_id) <= 200
        or isinstance(queue_id, bool)
        or type(queue_id) is not int
        or queue_id < 0
        or type(workflow_sha) is not str
        or len(workflow_sha) != 64
        or any(char not in "0123456789abcdef" for char in workflow_sha)
    ):
        raise ValueError("runtime proof checkpoint diverges from the clicked job")
    if phase == "flux":
        status = row.get("status")
        if (
            row.get("outputUsedByH3") is not False
            or (
                status == "stopped_after_gpu_activity"
                and row.get("vramIdleAfterStop") is not True
            )
            or (status == "queued" and (gpu_observed or process_exited))
            or (
                status == "gpu_activity_observed"
                and (not gpu_observed or process_exited)
            )
            or (
                status == "stopped_after_gpu_activity"
                and (not gpu_observed or not process_exited)
            )
        ):
            raise ValueError("FLUX runtime proof state is inconsistent")
    return {
        "phase": phase,
        "promptId": prompt_id,
        "queueId": queue_id,
        "submissionNonce": nonce,
        "workflowSha256": workflow_sha,
        "gpuActivityObserved": gpu_observed,
        "processExited": process_exited,
        "referenceSha256": reference_sha,
        "referenceSourceMode": "preuploaded_imported",
    }


def _create_book_discovery_factory():
    """Freeze the Search/Reader provider pair used by every API command."""

    search_endpoint = os.environ.get(
        "SHIDU_SEARCH_MCP_ENDPOINT",
        _DEFAULT_SEARCH_MCP_ENDPOINT,
    ).strip()
    reader_endpoint = os.environ.get(
        "SHIDU_READER_MCP_ENDPOINT",
        _DEFAULT_READER_MCP_ENDPOINT,
    ).strip()
    search_provider = CodingPlanSearchMCPProvider(
        HttpMCPTransport(search_endpoint),
        timeout_seconds=30.0,
    )
    reader_provider = CodingPlanPageReaderMCPProvider(
        HttpMCPTransport(reader_endpoint)
    )
    url_guard = ReaderURLGuard()

    def discovery_factory(repository: ShiduRepository) -> BookDiscoveryService:
        return BookDiscoveryService(
            repository=repository,
            search_provider=search_provider,
            reader_provider=reader_provider,
            url_guard=url_guard,
        )

    return discovery_factory


def create_service() -> SqlAlchemyShiduService:
    project_id = _required_uuid("SHIDU_PROJECT_ID")
    actor_id = os.environ.get("SHIDU_ACTOR_ID", "").strip()
    h3_authority_root = os.environ.get(
        "SHIDU_H3_AUTHORITY_ROOT",
        "",
    ).strip()
    if not actor_id:
        raise RuntimeError("Shidu production adapters are not configured")
    try:
        sessions = _session_factory()
        registry = load_atomic_capability_registry()
        if h3_authority_root:
            authority_store = JsonFileH3PersistedAuthorityStore(
                h3_authority_root
            )
            submitter: WorkflowSubmitter = ProductionH3WorkflowSubmitter(
                session_factory=sessions,
                capability_registry=registry,
                authority_resolver=PersistentH3WorkflowAuthorityResolver(
                    authority_store=authority_store,
                ),
            )
        else:
            voice_id = _required_uuid("SHIDU_VOICE_PRESET_REVISION_ID")
            authority_file = os.environ.get(
                "SHIDU_AUDIO_AUTHORITY_FILE",
                "",
            )
            if not authority_file:
                raise RuntimeError(
                    "Shidu production adapters are not configured"
                )
            authorities = load_audio_authority_bundle(
                authority_file,
                expected_project_id=project_id,
            )
            submitter = ProductionWorkflowSubmitter(
                session_factory=sessions,
                capability_registry=registry,
                voice_preset_revision_id=voice_id,
                audio_authorities=authorities,
            )
        from .competition_prepared_reference_backend import (
            CompetitionPreparedReferenceBackend,
        )

        prepared_backend = None
        if os.environ.get("AMD_ROOT") and os.environ.get("AMD_RELEASE_DIR"):
            prepared_backend = CompetitionPreparedReferenceBackend.from_environment(
                session_factory=sessions
            )
        return SqlAlchemyShiduService(
            session_factory=sessions,
            workflow_submitter=submitter,
            actor_id=actor_id,
            book_discovery_factory=_create_book_discovery_factory(),
            competition_reference_preparer=(
                None if prepared_backend is None else prepared_backend.prepare
            ),
            competition_reference_lookup=(
                None if prepared_backend is None else prepared_backend.lookup
            ),
            competition_reference_image_reader=(
                None if prepared_backend is None else prepared_backend.read_image
            ),
            competition_runtime_proof_reader=(
                _competition_runtime_proof_reader
                if os.environ.get("AMD_ROOT")
                else None
            ),
        )
    except (OSError, ValueError):
        raise RuntimeError("Shidu production adapters are not configured") from None


def create_artifact_gateway() -> LocalCasArtifactGateway:
    project_id = _required_uuid("SHIDU_PROJECT_ID")
    root = os.environ.get("CREATIVE_HUB_ARTIFACT_STORE_ROOT", "").strip()
    if not root:
        raise RuntimeError("Shidu production adapters are not configured")
    try:
        sessions = _session_factory()
        store = ContentAddressedArtifactStore(root)
    except (OSError, RuntimeError, ValueError):
        raise RuntimeError("Shidu production adapters are not configured") from None
    return LocalCasArtifactGateway(
        repository=PostgresArtifactRepository(sessions),
        store=store,
        project_id=project_id,
    )


__all__ = [
    "AudioAuthorityBundle",
    "H3AuthorityResolutionUnavailable",
    "H3PersistedArtifactAuthority",
    "H3PersistedAuthorityStore",
    "H3PersistedVisualIdentityAuthority",
    "H3PersistedWorkflowAuthorityRecord",
    "H3VisualIdentityBindingAttestation",
    "H3WorkflowAuthorityBundle",
    "H3WorkflowAuthorityResolver",
    "JsonFileH3PersistedAuthorityStore",
    "LocalCasArtifactGateway",
    "PersistentH3WorkflowAuthorityResolver",
    "ProductionH3WorkflowSubmitter",
    "ProductionWorkflowSubmitter",
    "ProjectedTrialScript",
    "audio_authority_bundle_digest",
    "create_artifact_gateway",
    "create_service",
    "h3_authority_bundle_digest",
    "h3_persisted_artifact_authority_digest",
    "h3_persisted_visual_identity_authority_digest",
    "h3_persisted_workflow_authority_record_digest",
    "h3_visual_identity_binding_digest",
    "load_audio_authority_bundle",
    "project_trial_script",
]
