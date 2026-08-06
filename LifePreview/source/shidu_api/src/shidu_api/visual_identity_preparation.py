"""Deterministic CPU-only preparation of historical visual H3 authorities.

The preparer deliberately accepts narrow repository, provider and CAS ports.
Network clients and database sessions remain outside this module, which makes
provider failure classification and the final append-only authority write
observable at one trust boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from shared_contracts import AtomicArtifactRef, RetentionClass

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.h3_workflow_compiler import H3SubmissionPolicyAuthority

from .deployment import (
    H3PersistedArtifactAuthority,
    H3PersistedVisualIdentityAuthority,
    H3PersistedWorkflowAuthorityRecord,
    JsonFileH3PersistedAuthorityStore,
    h3_persisted_artifact_authority_digest,
    h3_persisted_visual_identity_authority_digest,
    h3_persisted_workflow_authority_record_digest,
)


_DIGEST_CHARS = frozenset("0123456789abcdef")
_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_RETRYABLE_STAGES = frozenset({"search", "fetch", "glm_validation"})
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_uuid(value: object, field_name: str) -> UUID:
    if type(value) is not UUID:
        raise ValueError(f"{field_name} must be a UUID")
    return value


def _require_digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _DIGEST_CHARS for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_text(value: object, field_name: str, *, limit: int) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be text")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > limit:
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _json_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    try:
        encoded = _canonical_bytes(dict(value))
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} must be canonical JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    _reject_secret_fields(decoded)
    return decoded


def _reject_secret_fields(value: object) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                if str(key).casefold() in _SECRET_KEYS:
                    raise ValueError("public authority JSON contains a secret field")
                stack.append(item)
        elif isinstance(current, list):
            stack.extend(current)


def _value(authority: object, name: str) -> object:
    if isinstance(authority, Mapping):
        if name not in authority:
            raise ValueError(f"provider authority is missing {name}")
        return authority[name]
    if not hasattr(authority, name):
        raise ValueError(f"provider authority is missing {name}")
    return getattr(authority, name)


def _project_authority(
    authority: object,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> dict[str, Any]:
    projected = {name: _value(authority, name) for name in required}
    for name in optional:
        try:
            projected[name] = _value(authority, name)
        except ValueError:
            pass
    return _json_mapping(projected, "provider authority")


@dataclass(frozen=True, slots=True)
class VisualPreparationSnapshot:
    project_id: UUID
    book_id: UUID
    book_identity_digest: str
    direction_revision_id: UUID
    direction_digest: str
    trial_script_revision_id: UUID
    trial_script_digest: str
    research_job_id: UUID
    research_digest: str
    evidence_pack_revision_id: UUID
    evidence_pack_digest: str
    safety_release_decision_digest: str
    character_name: str
    age_stage: str
    historical_context: str
    project_authority_payload: Mapping[str, Any]
    trial_script_authority_payload: Mapping[str, Any]
    evidence_pack_authority_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "project_id",
            "book_id",
            "direction_revision_id",
            "trial_script_revision_id",
            "research_job_id",
            "evidence_pack_revision_id",
        ):
            _require_uuid(getattr(self, name), name)
        for name in (
            "book_identity_digest",
            "direction_digest",
            "trial_script_digest",
            "research_digest",
            "evidence_pack_digest",
            "safety_release_decision_digest",
        ):
            _require_digest(getattr(self, name), name)
        object.__setattr__(
            self, "character_name", _require_text(self.character_name, "character_name", limit=120)
        )
        object.__setattr__(
            self, "age_stage", _require_text(self.age_stage, "age_stage", limit=80)
        )
        object.__setattr__(
            self,
            "historical_context",
            _require_text(self.historical_context, "historical_context", limit=1200),
        )
        for name in (
            "project_authority_payload",
            "trial_script_authority_payload",
            "evidence_pack_authority_payload",
        ):
            object.__setattr__(self, name, _json_mapping(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class QualifiedHistoricalCandidate:
    candidate_id: str
    sanitized_bytes: bytes
    mime_type: str
    sanitized_sha256: str
    search_authority: Mapping[str, Any]
    candidate_authority: Mapping[str, Any]
    fetch_authority: Mapping[str, Any]
    glm_authority: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _require_text(self.candidate_id, "candidate_id", limit=160)
        )
        if type(self.sanitized_bytes) is not bytes or not self.sanitized_bytes:
            raise ValueError("sanitized image bytes are invalid")
        if self.mime_type not in _MIME_TYPES:
            raise ValueError("sanitized image MIME type is invalid")
        _require_digest(self.sanitized_sha256, "sanitized_sha256")
        if _sha256_bytes(self.sanitized_bytes) != self.sanitized_sha256:
            raise ValueError("sanitized image digest mismatch")
        for name in (
            "search_authority",
            "candidate_authority",
            "fetch_authority",
            "glm_authority",
        ):
            object.__setattr__(self, name, _json_mapping(getattr(self, name), name))
        if (
            self.glm_authority.get("qualified") is not True
            or self.glm_authority.get("vision_verdict") != "passed"
            or self.glm_authority.get("license_policy_passed") is not True
        ):
            raise ValueError("historical candidate is not qualified")

    @property
    def selected_basis_digest(self) -> str:
        return canonical_json_digest(
            {
                "candidate_id": self.candidate_id,
                "sanitized_sha256": self.sanitized_sha256,
                "mime_type": self.mime_type,
                "search_authority": dict(self.search_authority),
                "candidate_authority": dict(self.candidate_authority),
                "fetch_authority": dict(self.fetch_authority),
                "glm_authority": dict(self.glm_authority),
            }
        )


@dataclass(frozen=True, slots=True)
class VisualDiscoveryOutcome:
    status: Literal["qualified", "zero_qualified"]
    selected: QualifiedHistoricalCandidate | None
    rejected_count: int

    def __post_init__(self) -> None:
        if type(self.rejected_count) is not int or self.rejected_count < 0:
            raise ValueError("rejected_count is invalid")
        if (self.status == "qualified") != isinstance(
            self.selected, QualifiedHistoricalCandidate
        ):
            raise ValueError("discovery status and selected candidate disagree")


class VisualPreparationRetryableError(RuntimeError):
    """Infrastructure failed; this must never be treated as zero results."""

    def __init__(self, failed_stage: str, safe_error_code: str) -> None:
        if failed_stage not in _RETRYABLE_STAGES:
            raise ValueError("retryable visual preparation stage is invalid")
        self.failed_stage = failed_stage
        self.safe_error_code = _require_text(
            safe_error_code, "safe_error_code", limit=100
        )
        super().__init__(f"visual preparation retryable failure: {failed_stage}")


class VisualPreparationContractError(ValueError):
    """A provider or persistence result violated its frozen contract."""


@dataclass(frozen=True, slots=True)
class VisualPreparationAttempt:
    project_id: UUID
    operation_run_id: UUID
    attempt_id: UUID
    attempt_number: int
    fencing_token: int

    def __post_init__(self) -> None:
        for name in ("project_id", "operation_run_id", "attempt_id"):
            _require_uuid(getattr(self, name), name)
        if type(self.attempt_number) is not int or self.attempt_number < 1:
            raise ValueError("attempt_number is invalid")
        if type(self.fencing_token) is not int or self.fencing_token < 1:
            raise ValueError("fencing_token is invalid")


@dataclass(frozen=True, slots=True)
class PublishedVisualArtifact:
    artifact_ref: AtomicArtifactRef
    publication_fencing_token: int

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_ref, AtomicArtifactRef):
            raise ValueError("published artifact reference is invalid")
        if (
            type(self.publication_fencing_token) is not int
            or self.publication_fencing_token < 1
        ):
            raise ValueError("publication fencing token is invalid")


@dataclass(frozen=True, slots=True)
class VisualPreparationResult:
    status: Literal["prepared", "reused", "zero_qualified"]
    record: H3PersistedWorkflowAuthorityRecord | None


@dataclass(frozen=True, slots=True)
class VisualSourcePreparationResult:
    status: Literal["source_prepared", "reused", "zero_qualified"]
    source_artifact: PublishedVisualArtifact | None


@dataclass(frozen=True, slots=True)
class FluxReferenceArtifactSet:
    """Already-generated CAS references; this module never starts FLUX."""

    front: PublishedVisualArtifact
    three_quarter_left: PublishedVisualArtifact
    profile_left: PublishedVisualArtifact

    def __post_init__(self) -> None:
        expected = (
            ("front", self.front, "character.reference.front"),
            (
                "three_quarter_left",
                self.three_quarter_left,
                "character.reference.three-quarter-left",
            ),
            (
                "profile_left",
                self.profile_left,
                "character.reference.profile-left",
            ),
        )
        artifact_ids: list[UUID] = []
        for _view, published, role in expected:
            if not isinstance(published, PublishedVisualArtifact):
                raise ValueError("FLUX reference publication is invalid")
            ref = published.artifact_ref
            if ref.logical_role != role or ref.mime_type not in _MIME_TYPES:
                raise ValueError("FLUX reference role or MIME type is invalid")
            artifact_ids.append(ref.artifact_id)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("FLUX reference artifacts must be unique")

    def ordered(self) -> tuple[tuple[str, PublishedVisualArtifact], ...]:
        return (
            ("front", self.front),
            ("three_quarter_left", self.three_quarter_left),
            ("profile_left", self.profile_left),
        )


class VisualPreparationSnapshotSource(Protocol):
    def load(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
    ) -> VisualPreparationSnapshot: ...


class ShiduRepositorySnapshotSource:
    """Production snapshot adapter over one transaction-bound ShiduRepository."""

    def __init__(self, repository: Any) -> None:
        required = (
            "get_book",
            "load_trial_script_context",
            "get_research_job",
        )
        if any(not callable(getattr(repository, name, None)) for name in required):
            raise ValueError("Shidu repository adapter is invalid")
        self._repository = repository

    def load(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
    ) -> VisualPreparationSnapshot:
        from creative_hub.shidu.trial_safety import require_trial_script_release

        book = self._repository.get_book(project_id, book_id)
        loaded = self._repository.load_trial_script_context(
            trial_script_revision_id
        )
        if not isinstance(loaded, tuple) or len(loaded) != 6:
            raise VisualPreparationContractError(
                "trial script context is invalid"
            )
        script, _methodology, direction, pack, claims, _sources = loaded
        research = self._repository.get_research_job(pack.research_job_id)
        release = require_trial_script_release(script.payload)
        if (
            book.id != book_id
            or book.project_id != project_id
            or script.id != trial_script_revision_id
            or script.project_id != project_id
            or script.book_id != book_id
            or script.resonance_direction_revision_id != direction_revision_id
            or direction.id != direction_revision_id
            or direction.project_id != project_id
            or direction.evidence_pack_revision_id != pack.id
            or pack.project_id != project_id
            or pack.publishable is not True
            or research.id != pack.research_job_id
            or research.project_id != project_id
            or research.book_id != book_id
            or research.status != "ready"
        ):
            raise VisualPreparationContractError(
                "Shidu visual preparation lineage is invalid"
            )
        direction_payload = dict(direction.payload)
        character_name = direction_payload.get("character_name") or book.title
        age_stage = direction_payload.get("age_stage") or "adult"
        claim_rows = [
            {
                "claim_id": str(claim.id),
                "claim_type": claim.claim_type,
                "normalized_claim": claim.normalized_claim,
                "confidence": claim.confidence,
                "digest": claim.digest,
            }
            for claim in claims
        ]
        context = "；".join(
            str(row["normalized_claim"]) for row in claim_rows[:8]
        )
        if not context:
            context = f"{book.title}；{direction.direction_key}"
        return VisualPreparationSnapshot(
            project_id=project_id,
            book_id=book_id,
            book_identity_digest=book.identity_digest,
            direction_revision_id=direction.id,
            direction_digest=direction.digest,
            trial_script_revision_id=script.id,
            trial_script_digest=script.digest,
            research_job_id=research.id,
            research_digest=research.digest,
            evidence_pack_revision_id=pack.id,
            evidence_pack_digest=pack.digest,
            safety_release_decision_digest=release.release_decision_digest,
            character_name=str(character_name),
            age_stage=str(age_stage),
            historical_context=context[:1200],
            project_authority_payload={
                "schema_version": "visual-prep.project.v1",
                "project_id": str(project_id),
                "book_id": str(book.id),
                "book_identity_digest": book.identity_digest,
                "title": book.title,
                "author": book.author,
                "language": book.language,
                "edition": book.edition,
                "translator": book.translator,
            },
            trial_script_authority_payload={
                "schema_version": "visual-prep.script.v1",
                "project_id": str(project_id),
                "trial_script_revision_id": str(script.id),
                "trial_script_digest": script.digest,
                "direction_revision_id": str(direction.id),
                "evidence_pack_revision_id": str(pack.id),
                "payload": script.payload,
            },
            evidence_pack_authority_payload={
                "schema_version": "visual-prep.evidence.v1",
                "project_id": str(project_id),
                "research_job_id": str(research.id),
                "research_digest": research.digest,
                "evidence_pack_revision_id": str(pack.id),
                "evidence_pack_digest": pack.digest,
                "publishable": True,
                "claims": claim_rows,
            },
        )


class HistoricalImageDiscovery(Protocol):
    def discover(self, snapshot: VisualPreparationSnapshot) -> VisualDiscoveryOutcome: ...


class QcPolicyAuthoritySource(Protocol):
    def load(self, *, project_id: UUID) -> H3SubmissionPolicyAuthority: ...


class ResolvedShiduQcPolicySource:
    """Pin policy exclusively through ``resolve_shidu_qc_policy``."""

    def __init__(self, *, session: Any, capability_registry: Any) -> None:
        self._session = session
        self._capability_registry = capability_registry

    def load(self, *, project_id: UUID) -> H3SubmissionPolicyAuthority:
        from .deployment import resolve_shidu_qc_policy

        policy = resolve_shidu_qc_policy(
            self._session,
            project_id=project_id,
            capability_registry=self._capability_registry,
        )
        policy_digest = canonical_json_digest(policy.model_dump(mode="json"))
        revision_id = uuid5(
            NAMESPACE_URL,
            f"shidu:resolved-qc-policy:{project_id}:{policy_digest}",
        )
        identity = {
            "schema_version": "factory.shidu-h3-policy-authority.v1",
            "authority_revision_id": str(revision_id),
            "factory_qc_policy": policy.model_dump(mode="json"),
        }
        return H3SubmissionPolicyAuthority.model_validate(
            {
                **identity,
                "authority_revision_id": revision_id,
                "factory_qc_policy": policy,
                "authority_digest": canonical_json_digest(identity),
            },
            strict=True,
        )


class VisualAuthorityPublisher(Protocol):
    def begin_or_reuse(
        self, *, project_id: UUID, input_digest: str
    ) -> VisualPreparationAttempt: ...

    def publish(
        self,
        *,
        attempt: VisualPreparationAttempt,
        publication_key: str,
        body: bytes,
        mime_type: str,
        logical_role: str,
        expected_digest: str,
    ) -> PublishedVisualArtifact: ...


class ArtifactPublicationServiceAdapter:
    """Production CAS port backed by ``ArtifactPublicationService``.

    The injected attempt source is responsible for creating or reusing the
    dedicated Postgres visual-prep workflow/operation/attempt fence.
    """

    def __init__(self, *, service: Any, attempts: Any) -> None:
        if not callable(getattr(service, "publish", None)) or not callable(
            getattr(attempts, "begin_or_reuse", None)
        ):
            raise ValueError("visual publication adapter dependencies are invalid")
        self._service = service
        self._attempts = attempts

    def begin_or_reuse(
        self, *, project_id: UUID, input_digest: str
    ) -> VisualPreparationAttempt:
        value = self._attempts.begin_or_reuse(
            project_id=project_id,
            input_digest=input_digest,
        )
        if not isinstance(value, VisualPreparationAttempt):
            raise VisualPreparationContractError("attempt source returned invalid data")
        return value

    def publish(
        self,
        *,
        attempt: VisualPreparationAttempt,
        publication_key: str,
        body: bytes,
        mime_type: str,
        logical_role: str,
        expected_digest: str,
    ) -> PublishedVisualArtifact:
        record = self._service.publish(
            project_id=attempt.project_id,
            operation_run_id=attempt.operation_run_id,
            attempt_id=attempt.attempt_id,
            attempt_number=attempt.attempt_number,
            fencing_token=attempt.fencing_token,
            publication_key=publication_key,
            stream=BytesIO(body),
            mime_type=mime_type,
            logical_role=logical_role,
            retention_class=RetentionClass.CANON,
            expected_digest=expected_digest,
            expected_size=len(body),
        )
        try:
            ref = AtomicArtifactRef(
                artifact_id=record.artifact_id,
                project_id=record.project_id,
                content_digest=record.content_digest,
                mime_type=record.mime_type,
                byte_size=record.byte_size,
                logical_role=record.logical_role,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise VisualPreparationContractError(
                "artifact publication returned invalid data"
            ) from exc
        return PublishedVisualArtifact(
            artifact_ref=ref,
            publication_fencing_token=attempt.fencing_token,
        )


class WikimediaGlmHistoricalDiscovery:
    """Wikimedia search -> secure fetch -> GLM Vision, with no AI fallback."""

    def __init__(
        self,
        *,
        provider: Any,
        fetcher: Any,
        vision: Any,
        query_factory: Callable[..., Any] | None = None,
        vision_request_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not callable(getattr(provider, "search", None)):
            raise ValueError("image search provider is invalid")
        if not callable(getattr(fetcher, "fetch", None)):
            raise ValueError("secure image fetcher is invalid")
        if not callable(getattr(vision, "evaluate", None)):
            raise ValueError("GLM Vision provider is invalid")
        self._provider = provider
        self._fetcher = fetcher
        self._vision = vision
        self._query_factory = query_factory or self._default_query_factory
        self._vision_request_factory = (
            vision_request_factory or self._default_vision_request_factory
        )

    @staticmethod
    def _default_query_factory(**values: Any) -> Any:
        from creative_hub.visual_identity.image_provider import ControlledImageQuery

        return ControlledImageQuery(**values)

    @staticmethod
    def _default_vision_request_factory(**values: Any) -> Any:
        from creative_hub.visual_identity.glm_vision import GlmVisionRequest

        return GlmVisionRequest(**values)

    @staticmethod
    def _raise_retryable(exc: Exception, default_stage: str) -> None:
        stage = getattr(exc, "failed_stage", None)
        if stage not in _RETRYABLE_STAGES:
            return
        code = getattr(exc, "safe_error_code", "provider_unavailable")
        raise VisualPreparationRetryableError(str(stage), str(code)) from exc

    def discover(self, snapshot: VisualPreparationSnapshot) -> VisualDiscoveryOutcome:
        query_text = f"{snapshot.character_name} historical portrait"
        plan_identity = {
            "schema_version": "visual-prep.query-plan.v1",
            "project_id": str(snapshot.project_id),
            "book_id": str(snapshot.book_id),
            "trial_script_revision_id": str(snapshot.trial_script_revision_id),
            "query_text": query_text,
        }
        plan_sha256 = canonical_json_digest(plan_identity)
        query = self._query_factory(
            plan_id=f"visual-prep-{snapshot.trial_script_revision_id.hex}",
            plan_sha256=plan_sha256,
            query_ordinal=1,
            query_text=query_text,
        )
        try:
            search = self._provider.search(query)
        except Exception as exc:
            self._raise_retryable(exc, "search")
            raise VisualPreparationContractError("image search contract failed") from exc

        try:
            receipt = _project_authority(
                search.receipt,
                ("receipt_sha256", "status", "result_count"),
                (
                    "plan_id",
                    "plan_sha256",
                    "query_ordinal",
                    "query_text",
                    "search_service",
                    "search_tool",
                    "search_schema_revision",
                    "request_sha256",
                    "response_sha256",
                    "completed_at",
                ),
            )
            candidates = tuple(search.candidates)
        except (AttributeError, TypeError, ValueError) as exc:
            raise VisualPreparationContractError("image search result is invalid") from exc
        if (
            receipt["status"] != "terminal_succeeded"
            or receipt["result_count"] != len(candidates)
        ):
            raise VisualPreparationContractError("image search receipt is incomplete")

        rejected = 0
        for candidate in sorted(candidates, key=lambda item: int(_value(item, "search_rank"))):
            candidate_authority = _project_authority(
                candidate,
                (
                    "candidate_id",
                    "search_rank",
                    "image_url",
                    "locator_sha256",
                    "candidate_sha256",
                    "license_status",
                    "license_reference",
                    "attribution",
                ),
                (
                    "source_page_url",
                    "source_domain",
                    "creator",
                    "publication_date",
                    "search_receipt_sha256",
                    "search_request_sha256",
                    "search_response_sha256",
                ),
            )
            try:
                fetched = self._fetcher.fetch(
                    candidate_authority["candidate_id"],
                    candidate_authority["image_url"],
                    candidate_authority["locator_sha256"],
                )
            except Exception as exc:
                self._raise_retryable(exc, "fetch")
                if type(exc).__name__ == "ImageFetchSecurityError":
                    rejected += 1
                    continue
                raise VisualPreparationContractError("image fetch contract failed") from exc
            fetch_authority = _project_authority(
                fetched,
                (
                    "candidate_id",
                    "canonical_url",
                    "canonical_locator_sha256",
                    "raw_sha256",
                    "sanitized_sha256",
                    "magic_mime_type",
                    "fetch_sha256",
                ),
                (
                    "approved_ip_addresses",
                    "resolved_peer_ip",
                    "redirects_observed",
                    "connect_approved_only",
                    "credentials_forbidden",
                    "http_status",
                    "declared_mime_type",
                    "raw_byte_size",
                    "fully_decoded",
                    "width_px",
                    "height_px",
                    "decoded_pixels",
                    "frame_count",
                    "artifact_id",
                    "request_sha256",
                    "response_sha256",
                ),
            )
            if (
                fetch_authority["candidate_id"] != candidate_authority["candidate_id"]
                or fetch_authority["canonical_url"] != candidate_authority["image_url"]
                or fetch_authority["canonical_locator_sha256"]
                != candidate_authority["locator_sha256"]
            ):
                raise VisualPreparationContractError("fetched image lineage mismatch")
            try:
                sanitized_bytes = _value(fetched, "sanitized_bytes")
                if type(sanitized_bytes) is not bytes:
                    raise TypeError("sanitized_bytes")
                request = self._vision_request_factory(
                    candidate_id=candidate_authority["candidate_id"],
                    raw_sha256=fetch_authority["raw_sha256"],
                    sanitized_sha256=fetch_authority["sanitized_sha256"],
                    mime_type=fetch_authority["magic_mime_type"],
                    sanitized_bytes=sanitized_bytes,
                    character_name=snapshot.character_name,
                    age_stage=snapshot.age_stage,
                    historical_context=snapshot.historical_context,
                    license_status=candidate_authority["license_status"],
                )
                evaluated = self._vision.evaluate(request)
            except Exception as exc:
                self._raise_retryable(exc, "glm_validation")
                raise VisualPreparationContractError("GLM Vision contract failed") from exc
            glm_authority = _project_authority(
                evaluated,
                (
                    "candidate_id",
                    "qualified",
                    "vision_verdict",
                    "license_policy_passed",
                    "rejection_codes",
                    "attestation_sha256",
                ),
                (
                    "glm_provider",
                    "glm_model",
                    "prompt_revision",
                    "prompt_sha256",
                    "policy_revision",
                    "policy_sha256",
                    "schema_revision",
                    "input_manifest_sha256",
                    "request_sha256",
                    "response_sha256",
                    "single_person",
                    "face_visible",
                    "identity_match",
                    "age_match",
                    "historical_source_match",
                    "watermark_or_text_absent",
                    "quality_passed",
                ),
            )
            if glm_authority["candidate_id"] != candidate_authority["candidate_id"]:
                raise VisualPreparationContractError("GLM candidate lineage mismatch")
            if glm_authority["qualified"] is not True:
                rejected += 1
                continue
            selected = QualifiedHistoricalCandidate(
                candidate_id=candidate_authority["candidate_id"],
                sanitized_bytes=sanitized_bytes,
                mime_type=fetch_authority["magic_mime_type"],
                sanitized_sha256=fetch_authority["sanitized_sha256"],
                search_authority={"query_plan": plan_identity, "receipt": receipt},
                candidate_authority=candidate_authority,
                fetch_authority=fetch_authority,
                glm_authority=glm_authority,
            )
            return VisualDiscoveryOutcome(
                status="qualified", selected=selected, rejected_count=rejected
            )
        return VisualDiscoveryOutcome(
            status="zero_qualified", selected=None, rejected_count=rejected
        )


def _persisted_artifact(
    published: PublishedVisualArtifact,
    *,
    external_revision_id: UUID,
    external_revision_digest: str,
) -> H3PersistedArtifactAuthority:
    identity = {
        "schema_version": "factory.shidu-h3-artifact-authority.v1",
        "external_revision_id": str(external_revision_id),
        "external_revision_digest": external_revision_digest,
        "artifact_ref": published.artifact_ref.model_dump(mode="json"),
        "publication_fencing_token": published.publication_fencing_token,
    }
    return H3PersistedArtifactAuthority.model_validate(
        {
            **identity,
            "external_revision_id": external_revision_id,
            "artifact_ref": published.artifact_ref,
            "authority_digest": h3_persisted_artifact_authority_digest(identity),
        },
        strict=True,
    )


def _load_existing(path: Path) -> H3PersistedWorkflowAuthorityRecord | None:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    if not path.is_file() or not 0 < size <= 4 * 1024 * 1024:
        raise VisualPreparationContractError("persisted authority file is invalid")
    try:
        return H3PersistedWorkflowAuthorityRecord.model_validate_json(
            path.read_bytes(), strict=True
        )
    except (OSError, ValueError) as exc:
        raise VisualPreparationContractError("persisted authority record is invalid") from exc


def _write_append_only(path: Path, record: H3PersistedWorkflowAuthorityRecord) -> None:
    body = _canonical_bytes(record.model_dump(mode="json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing(path)
    if existing is not None:
        if existing != record:
            raise VisualPreparationContractError("authority path already has other content")
        return
    # Keep the temporary basename short enough for legacy Windows MAX_PATH;
    # it remains same-directory so the final hard-link publication is atomic.
    temporary = path.with_name(f".vp-{uuid4().hex}.partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = _load_existing(path)
            if existing != record:
                raise VisualPreparationContractError(
                    "authority path won a conflicting publication race"
                )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _source_state_path(authority_path: Path) -> Path:
    # The UUID hex form keeps this durable sibling below legacy Windows
    # MAX_PATH while remaining collision-free inside the direction directory.
    return authority_path.with_name(f"{UUID(authority_path.stem).hex}.vs.json")


def _load_source_state(path: Path) -> dict[str, Any] | None:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    if not path.is_file() or not 0 < size <= 2 * 1024 * 1024:
        raise VisualPreparationContractError("visual source state is invalid")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise VisualPreparationContractError("visual source state is invalid") from exc
    if not isinstance(value, dict):
        raise VisualPreparationContractError("visual source state is invalid")
    _reject_secret_fields(value)
    supplied = value.get("state_digest")
    identity = dict(value)
    identity.pop("state_digest", None)
    if (
        value.get("schema_version")
        != "visual-prep.historical-source-state.v1"
        or not isinstance(supplied, str)
        or supplied != canonical_json_digest(identity)
    ):
        raise VisualPreparationContractError(
            "visual source state digest is invalid"
        )
    return value


def _write_source_state(path: Path, payload: Mapping[str, Any]) -> None:
    body = _canonical_bytes(_json_mapping(payload, "visual source state"))
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_source_state(path)
    if existing is not None:
        if _canonical_bytes(existing) != body:
            raise VisualPreparationContractError(
                "visual source state already has other content"
            )
        return
    temporary = path.with_name(f".vs-{uuid4().hex}.partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = _load_source_state(path)
            if existing is None or _canonical_bytes(existing) != body:
                raise VisualPreparationContractError(
                    "visual source state won a conflicting publication race"
                )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class HistoricalVisualIdentityPreparer:
    """Publish one qualified historical image and its frozen H3 authorities."""

    def __init__(
        self,
        *,
        snapshots: VisualPreparationSnapshotSource,
        discovery: HistoricalImageDiscovery,
        policies: QcPolicyAuthoritySource,
        publisher: VisualAuthorityPublisher,
        authority_store: JsonFileH3PersistedAuthorityStore,
    ) -> None:
        self._snapshots = snapshots
        self._discovery = discovery
        self._policies = policies
        self._publisher = publisher
        self._store = authority_store

    def prepare_source(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
    ) -> VisualSourcePreparationResult:
        """CPU phase A: select and persist one qualified historical source."""

        path = self._authority_path(
            project_id, book_id, direction_revision_id, trial_script_revision_id
        )
        existing_record = _load_existing(path)
        if existing_record is not None:
            source = existing_record.visual_identity_authority.source_artifact
            assert source is not None
            return VisualSourcePreparationResult(
                status="reused",
                source_artifact=PublishedVisualArtifact(
                    artifact_ref=source.artifact_ref,
                    publication_fencing_token=source.publication_fencing_token,
                ),
            )
        state_path = _source_state_path(path)
        existing_state = _load_source_state(state_path)
        if existing_state is not None:
            expected_ids = {
                "project_id": str(project_id),
                "book_id": str(book_id),
                "direction_revision_id": str(direction_revision_id),
                "trial_script_revision_id": str(trial_script_revision_id),
            }
            if any(
                existing_state.get(name) != value
                for name, value in expected_ids.items()
            ):
                raise VisualPreparationContractError(
                    "visual source state key mismatch"
                )
            return VisualSourcePreparationResult(
                status="reused",
                source_artifact=self._source_from_state(existing_state),
            )

        snapshot = self._load_snapshot(
            project_id, book_id, direction_revision_id, trial_script_revision_id
        )
        outcome = self._discovery.discover(snapshot)
        if not isinstance(outcome, VisualDiscoveryOutcome):
            raise VisualPreparationContractError(
                "visual discovery returned invalid data"
            )
        if outcome.status == "zero_qualified":
            return VisualSourcePreparationResult(
                status="zero_qualified", source_artifact=None
            )
        selected = outcome.selected
        assert selected is not None
        policy = self._load_policy(project_id)
        input_digest = self._input_digest(snapshot, selected, policy)
        attempt = self._begin_attempt(project_id, input_digest)
        source = self._publish(
            attempt,
            input_digest=input_digest,
            ordinal=0,
            body=selected.sanitized_bytes,
            mime_type=selected.mime_type,
            role="character.source.image",
            expected_digest=selected.sanitized_sha256,
        )
        state = {
            "schema_version": "visual-prep.historical-source-state.v1",
            "project_id": str(project_id),
            "book_id": str(book_id),
            "direction_revision_id": str(direction_revision_id),
            "trial_script_revision_id": str(trial_script_revision_id),
            "snapshot_digests": {
                "book": snapshot.book_identity_digest,
                "direction": snapshot.direction_digest,
                "script": snapshot.trial_script_digest,
                "research": snapshot.research_digest,
                "evidence": snapshot.evidence_pack_digest,
                "safety": snapshot.safety_release_decision_digest,
            },
            "input_digest": input_digest,
            "operation_run_id": str(attempt.operation_run_id),
            "attempt_id": str(attempt.attempt_id),
            "attempt_number": attempt.attempt_number,
            "fencing_token": attempt.fencing_token,
            "source_artifact_ref": source.artifact_ref.model_dump(mode="json"),
            "source_publication_fencing_token": source.publication_fencing_token,
            "selected_basis_digest": selected.selected_basis_digest,
            "selection": {
                "qualified": True,
                "candidate_id": selected.candidate_id,
                "search_authority": dict(selected.search_authority),
                "candidate_authority": dict(selected.candidate_authority),
                "fetch_authority": dict(selected.fetch_authority),
                "glm_authority": dict(selected.glm_authority),
            },
            "policy_authority": policy.model_dump(mode="json"),
        }
        state["state_digest"] = canonical_json_digest(state)
        _write_source_state(state_path, state)
        return VisualSourcePreparationResult(
            status="source_prepared", source_artifact=source
        )

    def finalize_with_flux_references(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
        flux_references: FluxReferenceArtifactSet,
    ) -> VisualPreparationResult:
        """CPU phase B: bind external FLUX CAS refs; never start a GPU."""

        if not isinstance(flux_references, FluxReferenceArtifactSet):
            raise VisualPreparationContractError("FLUX reference set is invalid")
        path = self._authority_path(
            project_id, book_id, direction_revision_id, trial_script_revision_id
        )
        existing = _load_existing(path)
        if existing is not None:
            existing_reference_rows = [
                {
                    "view": view,
                    "artifact_ref": published.artifact_ref.model_dump(mode="json"),
                    "publication_fencing_token": published.publication_fencing_token,
                }
                for view, published in flux_references.ordered()
            ]
            expected_resolution_id = uuid5(
                NAMESPACE_URL,
                f"shidu:visual-prep:{project_id}:{trial_script_revision_id}:"
                f"{existing.visual_identity_authority.selected_basis_digest}:"
                f"{canonical_json_digest(existing_reference_rows)}",
            )
            if (
                existing.visual_identity_authority.visual_identity_resolution_id
                != expected_resolution_id
            ):
                raise VisualPreparationContractError(
                    "persisted authority belongs to different FLUX references"
                )
            return VisualPreparationResult(status="reused", record=existing)
        state = _load_source_state(_source_state_path(path))
        if state is None:
            raise VisualPreparationContractError(
                "qualified historical source must be prepared first"
            )
        expected_ids = {
            "project_id": str(project_id),
            "book_id": str(book_id),
            "direction_revision_id": str(direction_revision_id),
            "trial_script_revision_id": str(trial_script_revision_id),
        }
        if any(state.get(name) != value for name, value in expected_ids.items()):
            raise VisualPreparationContractError("visual source state key mismatch")
        snapshot = self._load_snapshot(
            project_id, book_id, direction_revision_id, trial_script_revision_id
        )
        expected_digests = {
            "book": snapshot.book_identity_digest,
            "direction": snapshot.direction_digest,
            "script": snapshot.trial_script_digest,
            "research": snapshot.research_digest,
            "evidence": snapshot.evidence_pack_digest,
            "safety": snapshot.safety_release_decision_digest,
        }
        if state.get("snapshot_digests") != expected_digests:
            raise VisualPreparationContractError("visual source state is stale")
        try:
            policy = H3SubmissionPolicyAuthority.model_validate_json(
                _canonical_bytes(state["policy_authority"]), strict=True
            )
            input_digest = _require_digest(state["input_digest"], "input_digest")
        except (KeyError, TypeError, ValueError) as exc:
            raise VisualPreparationContractError(
                "visual source policy or input identity is invalid"
            ) from exc
        attempt = self._begin_attempt(project_id, input_digest)
        persisted_attempt = (
            str(attempt.operation_run_id),
            str(attempt.attempt_id),
            attempt.attempt_number,
            attempt.fencing_token,
        )
        if persisted_attempt != (
            state.get("operation_run_id"),
            state.get("attempt_id"),
            state.get("attempt_number"),
            state.get("fencing_token"),
        ):
            raise VisualPreparationContractError(
                "visual preparation attempt fence changed"
            )
        source = self._source_from_state(state)
        if source.artifact_ref.project_id != project_id or any(
            published.artifact_ref.project_id != project_id
            for _view, published in flux_references.ordered()
        ):
            raise VisualPreparationContractError(
                "source or FLUX artifact project mismatch"
            )
        project = self._publish_json(
            attempt, input_digest, 1, snapshot.project_authority_payload, "h3.project.authority"
        )
        script = self._publish_json(
            attempt,
            input_digest,
            2,
            snapshot.trial_script_authority_payload,
            "h3.trial-script.authority",
        )
        evidence = self._publish_json(
            attempt,
            input_digest,
            3,
            snapshot.evidence_pack_authority_payload,
            "h3.evidence-pack.authority",
        )

        selected_basis_digest = _require_digest(
            state.get("selected_basis_digest"), "selected_basis_digest"
        )
        reference_artifacts = [
            {
                "view": view,
                "artifact_ref": published.artifact_ref.model_dump(mode="json"),
                "publication_fencing_token": published.publication_fencing_token,
            }
            for view, published in flux_references.ordered()
        ]
        reference_set_digest = canonical_json_digest(reference_artifacts)
        resolution_id = uuid5(
            NAMESPACE_URL,
            f"shidu:visual-prep:{project_id}:{trial_script_revision_id}:"
            f"{selected_basis_digest}:{reference_set_digest}",
        )
        resolution_identity = {
            "schema_version": "visual-prep.historical-resolution.v1",
            "resolution_id": str(resolution_id),
            "project_id": str(project_id),
            "trial_script_revision_id": str(trial_script_revision_id),
            "trial_script_digest": snapshot.trial_script_digest,
            "evidence_pack_revision_id": str(snapshot.evidence_pack_revision_id),
            "evidence_pack_digest": snapshot.evidence_pack_digest,
            "visual_identity_mode": "historical_image_grounded",
            "basis_kind": "searched_historical",
            "selected_basis_digest": selected_basis_digest,
            "source_artifact_ref": source.artifact_ref.model_dump(mode="json"),
            "source_publication_fencing_token": source.publication_fencing_token,
            "selection": state["selection"],
            "reference_artifacts": reference_artifacts,
            "reference_set_digest": reference_set_digest,
        }
        resolution_digest = canonical_json_digest(resolution_identity)
        resolution_payload = {
            **resolution_identity,
            "resolution_digest": resolution_digest,
        }
        visual_artifact = self._publish_json(
            attempt,
            input_digest,
            4,
            resolution_payload,
            "h3.visual-identity-resolution.authority",
        )

        project_authority = _persisted_artifact(
            project,
            external_revision_id=book_id,
            external_revision_digest=snapshot.book_identity_digest,
        )
        script_authority = _persisted_artifact(
            script,
            external_revision_id=trial_script_revision_id,
            external_revision_digest=snapshot.trial_script_digest,
        )
        evidence_authority = _persisted_artifact(
            evidence,
            external_revision_id=snapshot.evidence_pack_revision_id,
            external_revision_digest=snapshot.evidence_pack_digest,
        )
        source_authority = _persisted_artifact(
            source,
            external_revision_id=source.artifact_ref.artifact_id,
            external_revision_digest=str(source.artifact_ref.content_digest),
        )
        resolution_authority = _persisted_artifact(
            visual_artifact,
            external_revision_id=resolution_id,
            external_revision_digest=resolution_digest,
        )
        visual_identity = {
            "schema_version": "factory.shidu-h3-visual-authority.v1",
            "project_id": str(project_id),
            "visual_identity_mode": "historical_image_grounded",
            "visual_identity_resolution_id": str(resolution_id),
            "visual_identity_resolution_digest": resolution_digest,
            "basis_kind": "searched_historical",
            "selected_basis_digest": selected_basis_digest,
            "verified": True,
            "historical": True,
            "non_ai": True,
            "ai_derived": False,
            "trial_script_revision_id": str(trial_script_revision_id),
            "trial_script_digest": snapshot.trial_script_digest,
            "evidence_pack_revision_id": str(snapshot.evidence_pack_revision_id),
            "evidence_pack_digest": snapshot.evidence_pack_digest,
            "appearance_spec_revision_id": None,
            "appearance_spec_digest": None,
            "authority_artifact": resolution_authority.model_dump(mode="json"),
            "source_artifact": source_authority.model_dump(mode="json"),
            "selected_source_artifact_id": str(source.artifact_ref.artifact_id),
            "selected_source_content_digest": str(source.artifact_ref.content_digest),
            "selected_source_fencing_token": source.publication_fencing_token,
        }
        visual = H3PersistedVisualIdentityAuthority.model_validate(
            {
                **visual_identity,
                "project_id": project_id,
                "visual_identity_resolution_id": resolution_id,
                "trial_script_revision_id": trial_script_revision_id,
                "evidence_pack_revision_id": snapshot.evidence_pack_revision_id,
                "authority_artifact": resolution_authority,
                "source_artifact": source_authority,
                "selected_source_artifact_id": source.artifact_ref.artifact_id,
                "authority_digest": h3_persisted_visual_identity_authority_digest(
                    visual_identity
                ),
            },
            strict=True,
        )
        record_identity = {
            "schema_version": "factory.shidu-h3-persisted-authorities.v1",
            "project_id": str(project_id),
            "book_id": str(book_id),
            "direction_revision_id": str(direction_revision_id),
            "direction_digest": snapshot.direction_digest,
            "trial_script_revision_id": str(trial_script_revision_id),
            "research_job_id": str(snapshot.research_job_id),
            "research_digest": snapshot.research_digest,
            "evidence_pack_revision_id": str(snapshot.evidence_pack_revision_id),
            "safety_release_decision_digest": snapshot.safety_release_decision_digest,
            "project_authority": project_authority.model_dump(mode="json"),
            "trial_script_authority": script_authority.model_dump(mode="json"),
            "evidence_pack_authority": evidence_authority.model_dump(mode="json"),
            "visual_identity_authority": visual.model_dump(mode="json"),
            "policy_authority": policy.model_dump(mode="json"),
        }
        record = H3PersistedWorkflowAuthorityRecord.model_validate(
            {
                **record_identity,
                "project_id": project_id,
                "book_id": book_id,
                "direction_revision_id": direction_revision_id,
                "trial_script_revision_id": trial_script_revision_id,
                "research_job_id": snapshot.research_job_id,
                "evidence_pack_revision_id": snapshot.evidence_pack_revision_id,
                "project_authority": project_authority,
                "trial_script_authority": script_authority,
                "evidence_pack_authority": evidence_authority,
                "visual_identity_authority": visual,
                "policy_authority": policy,
                "record_digest": h3_persisted_workflow_authority_record_digest(
                    record_identity
                ),
            },
            strict=True,
        )
        _write_append_only(path, record)
        return VisualPreparationResult(status="prepared", record=record)

    def prepare(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
        flux_references: FluxReferenceArtifactSet,
    ) -> VisualPreparationResult:
        """Convenience wrapper preserving the explicit A then B boundary."""

        source = self.prepare_source(
            project_id=project_id,
            book_id=book_id,
            direction_revision_id=direction_revision_id,
            trial_script_revision_id=trial_script_revision_id,
        )
        if source.status == "zero_qualified":
            return VisualPreparationResult(status="zero_qualified", record=None)
        return self.finalize_with_flux_references(
            project_id=project_id,
            book_id=book_id,
            direction_revision_id=direction_revision_id,
            trial_script_revision_id=trial_script_revision_id,
            flux_references=flux_references,
        )

    def _authority_path(
        self,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
    ) -> Path:
        for name, value in (
            ("project_id", project_id),
            ("book_id", book_id),
            ("direction_revision_id", direction_revision_id),
            ("trial_script_revision_id", trial_script_revision_id),
        ):
            _require_uuid(value, name)
        return self._store.authority_path(
            project_id=project_id,
            book_id=book_id,
            direction_revision_id=direction_revision_id,
            trial_script_revision_id=trial_script_revision_id,
        )

    def _load_snapshot(
        self,
        project_id: UUID,
        book_id: UUID,
        direction_revision_id: UUID,
        trial_script_revision_id: UUID,
    ) -> VisualPreparationSnapshot:
        snapshot = self._snapshots.load(
            project_id=project_id,
            book_id=book_id,
            direction_revision_id=direction_revision_id,
            trial_script_revision_id=trial_script_revision_id,
        )
        if not isinstance(snapshot, VisualPreparationSnapshot) or (
            snapshot.project_id,
            snapshot.book_id,
            snapshot.direction_revision_id,
            snapshot.trial_script_revision_id,
        ) != (
            project_id,
            book_id,
            direction_revision_id,
            trial_script_revision_id,
        ):
            raise VisualPreparationContractError(
                "repository snapshot lineage mismatch"
            )
        return snapshot

    def _load_policy(self, project_id: UUID) -> H3SubmissionPolicyAuthority:
        policy = self._policies.load(project_id=project_id)
        try:
            return H3SubmissionPolicyAuthority.model_validate(
                policy.model_dump(mode="python"), strict=True
            )
        except (AttributeError, ValueError) as exc:
            raise VisualPreparationContractError(
                "QC policy authority is invalid"
            ) from exc

    @staticmethod
    def _input_digest(
        snapshot: VisualPreparationSnapshot,
        selected: QualifiedHistoricalCandidate,
        policy: H3SubmissionPolicyAuthority,
    ) -> str:
        return canonical_json_digest(
            {
                "schema_version": "visual-prep.input.v1",
                "project_id": str(snapshot.project_id),
                "book_id": str(snapshot.book_id),
                "book_identity_digest": snapshot.book_identity_digest,
                "direction_revision_id": str(snapshot.direction_revision_id),
                "direction_digest": snapshot.direction_digest,
                "trial_script_revision_id": str(snapshot.trial_script_revision_id),
                "trial_script_digest": snapshot.trial_script_digest,
                "research_digest": snapshot.research_digest,
                "evidence_pack_digest": snapshot.evidence_pack_digest,
                "safety_release_decision_digest": snapshot.safety_release_decision_digest,
                "selected_basis_digest": selected.selected_basis_digest,
                "policy_authority_digest": policy.authority_digest,
            }
        )

    def _begin_attempt(
        self, project_id: UUID, input_digest: str
    ) -> VisualPreparationAttempt:
        attempt = self._publisher.begin_or_reuse(
            project_id=project_id, input_digest=input_digest
        )
        if (
            not isinstance(attempt, VisualPreparationAttempt)
            or attempt.project_id != project_id
        ):
            raise VisualPreparationContractError(
                "visual preparation attempt is invalid"
            )
        return attempt

    @staticmethod
    def _source_from_state(
        state: Mapping[str, Any]
    ) -> PublishedVisualArtifact:
        try:
            ref = AtomicArtifactRef.model_validate_json(
                _canonical_bytes(state["source_artifact_ref"]), strict=True
            )
            fence = state["source_publication_fencing_token"]
            return PublishedVisualArtifact(
                artifact_ref=ref,
                publication_fencing_token=fence,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VisualPreparationContractError(
                "persisted source artifact authority is invalid"
            ) from exc

    def _publish_json(
        self,
        attempt: VisualPreparationAttempt,
        input_digest: str,
        ordinal: int,
        payload: Mapping[str, Any],
        role: str,
    ) -> PublishedVisualArtifact:
        body = _canonical_bytes(_json_mapping(payload, role))
        return self._publish(
            attempt,
            input_digest=input_digest,
            ordinal=ordinal,
            body=body,
            mime_type="application/json",
            role=role,
            expected_digest=_sha256_bytes(body),
        )

    def _publish(
        self,
        attempt: VisualPreparationAttempt,
        *,
        input_digest: str,
        ordinal: int,
        body: bytes,
        mime_type: str,
        role: str,
        expected_digest: str,
    ) -> PublishedVisualArtifact:
        result = self._publisher.publish(
            attempt=attempt,
            publication_key=f"visual-prep.v1:{input_digest}:{ordinal:02d}:{role}",
            body=body,
            mime_type=mime_type,
            logical_role=role,
            expected_digest=expected_digest,
        )
        if not isinstance(result, PublishedVisualArtifact):
            raise VisualPreparationContractError("publisher returned invalid data")
        ref = result.artifact_ref
        if (
            ref.project_id != attempt.project_id
            or ref.content_digest != expected_digest
            or ref.mime_type != mime_type
            or ref.logical_role != role
            or ref.byte_size != len(body)
            or result.publication_fencing_token != attempt.fencing_token
        ):
            raise VisualPreparationContractError("published artifact receipt mismatch")
        return result


__all__ = [
    "ArtifactPublicationServiceAdapter",
    "FluxReferenceArtifactSet",
    "HistoricalVisualIdentityPreparer",
    "PublishedVisualArtifact",
    "QualifiedHistoricalCandidate",
    "ResolvedShiduQcPolicySource",
    "ShiduRepositorySnapshotSource",
    "VisualDiscoveryOutcome",
    "VisualPreparationAttempt",
    "VisualPreparationContractError",
    "VisualPreparationResult",
    "VisualPreparationRetryableError",
    "VisualPreparationSnapshot",
    "VisualSourcePreparationResult",
    "WikimediaGlmHistoricalDiscovery",
]
