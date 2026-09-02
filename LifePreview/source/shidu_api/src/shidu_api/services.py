"""Domain adapters and durable public projections for Shidu API."""

from __future__ import annotations

import json
import hmac
import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import text

from creative_hub.dag_models import WorkflowRunEdgeRecord
from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import (
    ArtifactLineageEdgeRecord,
    ArtifactRecordRow,
    BookRecord,
    DeliveryRevisionRecord,
    EvidencePackRevisionRecord,
    OperationAttemptRecord,
    OperationAttemptStateRecord,
    OperationRunRecord,
    ProductCommandLedgerRecord,
    QCEvaluationFactRecord,
    ReaderFeedbackRecord,
    ResearchJobRecord,
    ResonanceDirectionRevisionRecord,
    SelectionHeadRecord,
    SelectionRevisionRecord,
    TrialScriptRevisionRecord,
    VideoJobProjectionRecord,
    WorkflowRunRecord,
)
from creative_hub.shidu.book_discovery_service import BookDiscoveryDependencyError
from creative_hub.shidu.preview_service import PreviewService
from creative_hub.shidu.repository import IdempotencyConflict, ShiduRepository
from creative_hub.shidu.schemas import (
    BookDiscoveryResolution,
    CreateResearchJob,
    SelectBookDiscoveryCandidate,
)
from creative_hub.shidu.trial_safety import (
    TrialSafetyError,
    require_trial_script_release,
)
from shared_contracts import AtomicArtifactRef


PUBLIC_JOB_STATES = frozenset({
    "queued", "researching", "scripting", "rendering", "voicing",
    "composing", "succeeded", "failed",
})
RESEARCH_PIPELINE_VERSION = "shidu-research.v2-search-v4-ai-completion-v1"
H3_PRODUCT_AUTHORITY_SCHEMA = "shidu.h3-product-authority.v1"
COMPETITION_RUNNER_IMPLEMENTATION_DIGEST = hashlib.sha256(
    b"amd.three-second-runner.v1|73frames|native-audio|no-subtitles"
).hexdigest()


class ApiServiceError(RuntimeError):
    error_code = "internal_error"
    public_message = "服务内部错误"
    retryable = False
    status_code = 500


class InvalidRequest(ApiServiceError):
    error_code = "invalid_request"
    public_message = "请求参数无效"
    status_code = 422


class ResourceNotFound(ApiServiceError):
    error_code = "not_found"
    public_message = "请求的内容不存在"
    status_code = 404


class CommandConflict(ApiServiceError):
    error_code = "idempotency_conflict"
    public_message = "该请求标识已用于不同操作"
    status_code = 409


class InsufficientEvidence(ApiServiceError):
    error_code = "insufficient_evidence"
    public_message = "现有证据不足，暂时无法生成"
    status_code = 409


class DependencyUnavailable(ApiServiceError):
    error_code = "dependency_unavailable"
    public_message = "服务暂时不可用，请稍后重试"
    retryable = True
    status_code = 503


class ProjectionInvalid(ApiServiceError):
    error_code = "projection_invalid"
    public_message = "视频交付状态暂不可用"
    retryable = True
    status_code = 500


class ShiduApiService(Protocol):
    def resolve_input(self, *, project_id: UUID, raw_input: str, idempotency_key: str) -> dict[str, Any]: ...
    def select_candidate(self, *, project_id: UUID, resolution_id: UUID, candidate_id: UUID, idempotency_key: str) -> dict[str, Any]: ...
    def list_books(self, *, project_id: UUID, query: str) -> list[dict[str, Any]]: ...
    def retry_research(self, *, project_id: UUID, book_id: UUID, idempotency_key: str) -> dict[str, Any]: ...
    def director_preview(self, *, project_id: UUID, request: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def prepare_competition_reference(self, *, project_id: UUID, request: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def get_competition_prepared_reference(self, *, project_id: UUID, request: Mapping[str, Any]) -> dict[str, Any] | None: ...
    def get_competition_prepared_reference_image(self, *, project_id: UUID, request_id: UUID) -> tuple[bytes, str, str]: ...
    def create_video_job(self, *, project_id: UUID, request: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    def publish_competition_reference_preview(self, *, project_id: UUID, job_id: str, job_authority_digest: str, reference: Mapping[str, Any]) -> dict[str, Any]: ...
    def get_video_job(self, *, project_id: UUID, job_id: str) -> dict[str, Any]: ...
    def add_feedback(self, *, project_id: UUID, request: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]: ...


class WorkflowSubmitter(Protocol):
    def submit(
        self,
        *,
        project_id: UUID,
        request: Mapping[str, Any],
        command_idempotency_key: str,
        created_by_actor: str,
    ) -> WorkflowSubmission: ...


class BookDiscoveryResolver(Protocol):
    def resolve(
        self,
        *,
        project_id: UUID,
        title: str,
        command_key: str,
    ) -> BookDiscoveryResolution: ...


@dataclass(frozen=True, slots=True)
class WorkflowSubmission:
    """Trusted materializer attestation returned after authority loading."""

    workflow_run_id: UUID
    project_id: UUID
    workflow_key: str
    book_id: UUID
    trial_script_revision_id: UUID
    voice_preset_revision_id: UUID | None = None
    audio_alignment_policy_revision_id: UUID | None = None
    visual_identity_resolution_id: UUID | None = None
    target_duration_seconds: float | None = None
    sequence_count: int | None = None
    input_authority_digest: str | None = None


def _submission_pipeline(submission: WorkflowSubmission) -> str:
    """Validate mutually exclusive trial/H3 authority without coercion."""

    if type(submission) is not WorkflowSubmission or not all(
        type(value) is UUID
        for value in (
            submission.workflow_run_id,
            submission.project_id,
            submission.book_id,
            submission.trial_script_revision_id,
        )
    ):
        raise ValueError("workflow submission identity is invalid")
    if submission.workflow_key == "factory.shidu-trial.v1":
        if (
            type(submission.voice_preset_revision_id) is not UUID
            or type(submission.audio_alignment_policy_revision_id) is not UUID
            or any(
                value is not None
                for value in (
                    submission.visual_identity_resolution_id,
                    submission.target_duration_seconds,
                    submission.sequence_count,
                    submission.input_authority_digest,
                )
            )
        ):
            raise ValueError("trial workflow submission authority is invalid")
        return "shidu_trial"
    if submission.workflow_key != "factory.shidu-h3.v1":
        raise ValueError("workflow submission pipeline is unsupported")
    digest = submission.input_authority_digest
    target = submission.target_duration_seconds
    sequences = submission.sequence_count
    if (
        submission.voice_preset_revision_id is not None
        or submission.audio_alignment_policy_revision_id is not None
        or type(submission.visual_identity_resolution_id) is not UUID
        or type(target) is not float
        or not math.isfinite(target)
        or type(sequences) is not int
        or not 1 <= sequences <= 12
        or not 3.0 * sequences <= target <= 15.0 * sequences
        or type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("H3 workflow submission authority is invalid")
    return "h3_vertical_slice"


def _submission_projection_fields(
    submission: WorkflowSubmission,
) -> dict[str, Any]:
    pipeline = _submission_pipeline(submission)
    if pipeline == "shidu_trial":
        return {
            "pipelineMode": pipeline,
            "voicePresetRevisionId": str(
                submission.voice_preset_revision_id
            ),
            "audioAlignmentPolicyRevisionId": str(
                submission.audio_alignment_policy_revision_id
            ),
        }
    return {
        "pipelineMode": pipeline,
        "visualIdentityResolutionId": str(
            submission.visual_identity_resolution_id
        ),
        "targetDurationSeconds": submission.target_duration_seconds,
        "sequenceCount": submission.sequence_count,
        "inputAuthorityDigest": submission.input_authority_digest,
    }


def _h3_submission_request(
    canonical_request: Mapping[str, Any],
    disclosure: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the competition H3 media authority on the trusted server side."""

    return {
        **dict(canonical_request),
        **dict(disclosure),
        "targetDurationSeconds": 3.0,
        "sequenceCount": 1,
        "nativeAudio": True,
        "subtitles": False,
    }


def _workflow_progress_status(
    pipeline_mode: object,
    completed_nodes: set[str],
    sequence_count: object = None,
) -> str:
    if (
        type(completed_nodes) is not set
        or any(type(node) is not str for node in completed_nodes)
    ):
        raise ValueError("workflow completion authority is invalid")
    if pipeline_mode == "h3_vertical_slice":
        if type(sequence_count) is not int or not 1 <= sequence_count <= 12:
            raise ValueError("H3 sequence count is invalid")
        if "episode-ir" not in completed_nodes:
            return "scripting"
        selected = {
            f"sequence.{ordinal:03d}.select"
            for ordinal in range(1, sequence_count + 1)
        }
        if not selected.issubset(completed_nodes):
            return "rendering"
        return "composing"
    if pipeline_mode not in {None, "shidu_trial"}:
        raise ValueError("workflow pipeline mode is unsupported")
    if "trial-plan" not in completed_nodes:
        return "scripting"
    if any(
        f"clip.{index:03d}" not in completed_nodes
        for index in range(1, 7)
    ):
        return "rendering"
    if any(
        f"speech.{index:03d}" not in completed_nodes
        for index in range(1, 7)
    ):
        return "voicing"
    return "composing"


def _camel(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, tuple):
        return [_camel(item) for item in value]
    if isinstance(value, list):
        return [_camel(item) for item in value]
    if isinstance(value, dict):
        return {key: _camel(item) for key, item in value.items()}
    return value


class SqlAlchemyShiduService:
    """Thin durable adapter; route functions never reach into ORM tables."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        workflow_submitter: WorkflowSubmitter,
        actor_id: str,
        research_provider_version: str = RESEARCH_PIPELINE_VERSION,
        book_discovery_factory: Callable[[ShiduRepository], BookDiscoveryResolver] | None = None,
        competition_reference_preparer: Callable[..., dict[str, Any]] | None = None,
        competition_reference_lookup: Callable[..., dict[str, Any] | None] | None = None,
        competition_reference_image_reader: Callable[..., tuple[bytes, str, str]] | None = None,
        competition_runtime_proof_reader: Callable[..., dict[str, Any] | None] | None = None,
    ) -> None:
        if not actor_id or len(actor_id) > 100:
            raise ValueError("actor_id is required")
        self._sessions = session_factory
        self._submitter = workflow_submitter
        self._actor_id = actor_id
        self._research_provider_version = research_provider_version
        self._book_discovery_factory = book_discovery_factory
        self._competition_reference_preparer = competition_reference_preparer
        self._competition_reference_lookup = competition_reference_lookup
        self._competition_reference_image_reader = competition_reference_image_reader
        self._competition_runtime_proof_reader = competition_runtime_proof_reader

    def prepare_competition_reference(
        self,
        *,
        project_id: UUID,
        request: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if self._competition_reference_preparer is None:
            raise DependencyUnavailable()
        try:
            return self._competition_reference_preparer(
                project_id=project_id,
                request=dict(request),
                idempotency_key=idempotency_key,
            )
        except ApiServiceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRequest() from exc
        except Exception as exc:
            raise DependencyUnavailable() from exc

    def get_competition_prepared_reference(
        self, *, project_id: UUID, request: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        if self._competition_reference_lookup is None:
            return None
        try:
            return self._competition_reference_lookup(
                project_id=project_id,
                request=dict(request),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def get_competition_prepared_reference_image(
        self, *, project_id: UUID, request_id: UUID
    ) -> tuple[bytes, str, str]:
        if self._competition_reference_image_reader is None:
            raise ResourceNotFound()
        try:
            return self._competition_reference_image_reader(
                project_id=project_id,
                request_id=request_id,
            )
        except ApiServiceError:
            raise
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ResourceNotFound() from exc

    def is_ready(self) -> bool:
        """Readiness is authoritative only after a database round trip."""

        try:
            with self._sessions() as session:
                return session.execute(select(1)).scalar_one() == 1
        except Exception:
            return False

    @staticmethod
    def _child_key(parent: str, role: str) -> str:
        return f"shidu:{role}:{canonical_json_digest({'parent': parent, 'role': role})}"

    @staticmethod
    def _require_release_safety(payload: Mapping[str, Any]):
        try:
            return require_trial_script_release(payload)
        except TrialSafetyError as exc:
            raise InvalidRequest() from exc

    def _ledger_replay(
        self,
        session: Session,
        *,
        project_id: UUID,
        kind: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:shidu_command_key, 0))"
                ),
                {
                    "shidu_command_key": (
                        f"shidu-api:{project_id}:{kind}:{key}"
                    )
                },
            )
        digest = canonical_json_digest(dict(payload))
        record = session.scalar(select(ProductCommandLedgerRecord).where(
            ProductCommandLedgerRecord.scope_key == f"project:{project_id}",
            ProductCommandLedgerRecord.command_kind == kind,
            ProductCommandLedgerRecord.command_idempotency_key == key,
        ))
        if record is None:
            return None
        if record.project_id != project_id or record.payload_digest != digest:
            raise CommandConflict()
        return dict(record.result)

    def _store_ledger(
        self,
        session: Session,
        *,
        project_id: UUID,
        kind: str,
        key: str,
        payload: Mapping[str, Any],
        result: Mapping[str, Any],
        status_code: int,
    ) -> None:
        request = dict(payload)
        response = dict(result)
        session.add(ProductCommandLedgerRecord(
            project_id=project_id,
            scope_key=f"project:{project_id}",
            command_kind=kind,
            command_idempotency_key=key,
            payload=request,
            payload_digest=canonical_json_digest(request),
            result=response,
            result_digest=canonical_json_digest(response),
            status_code=status_code,
            actor_id=self._actor_id,
        ))
        session.flush()

    @staticmethod
    def _book_payload(book: Any) -> dict[str, Any]:
        return {
            "id": str(book.id),
            "title": book.title,
            "author": book.author,
            "language": book.language,
            "edition": book.edition,
            "translator": book.translator,
        }

    @staticmethod
    def _stable_result(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a recursively key-sorted JSON value for byte-stable replay."""

        return json.loads(
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    def resolve_input(self, *, project_id: UUID, raw_input: str, idempotency_key: str) -> dict[str, Any]:
        if not isinstance(raw_input, str):
            raise InvalidRequest()
        title = raw_input.strip()
        if (
            not title
            or len(title) > 60
            or "://" in title
            or title.casefold().startswith("www.")
            or "|" in title
            or "\n" in title
            or "\r" in title
        ):
            raise InvalidRequest()
        request_payload = {"title": title}
        try:
            with self._sessions() as session, session.begin():
                ledger = self._ledger_replay(
                    session,
                    project_id=project_id,
                    kind="shidu.resolve_input",
                    key=idempotency_key,
                    payload=request_payload,
                )
                if ledger is not None:
                    return self._stable_result(ledger)
                if self._book_discovery_factory is None:
                    raise DependencyUnavailable()
                repo = ShiduRepository(session)
                resolution = self._book_discovery_factory(repo).resolve(
                    project_id=project_id,
                    title=title,
                    command_key=idempotency_key,
                )
                result = self._stable_result({
                    "resolutionId": str(resolution.id),
                    "resolution": (
                        "candidates" if resolution.candidates else "unresolved"
                    ),
                    "candidates": [
                        {
                            "candidateId": str(candidate.id),
                            "title": candidate.title,
                            "author": candidate.author,
                            "language": candidate.language,
                            "edition": candidate.edition,
                            "translator": candidate.translator,
                        }
                        for candidate in resolution.candidates
                    ],
                })
                self._store_ledger(
                    session,
                    project_id=project_id,
                    kind="shidu.resolve_input",
                    key=idempotency_key,
                    payload=request_payload,
                    result=result,
                    status_code=200,
                )
                return result
        except CommandConflict:
            raise
        except DependencyUnavailable:
            raise
        except BookDiscoveryDependencyError as exc:
            raise DependencyUnavailable() from exc
        except IdempotencyConflict as exc:
            raise CommandConflict() from exc
        except IntegrityError as exc:
            raise CommandConflict() from exc
        except (TypeError, ValueError) as exc:
            raise InvalidRequest() from exc
        except Exception as exc:
            raise DependencyUnavailable() from exc

    def select_candidate(
        self,
        *,
        project_id: UUID,
        resolution_id: UUID,
        candidate_id: UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_payload = {
            "resolutionId": str(resolution_id),
            "candidateId": str(candidate_id),
        }
        try:
            with self._sessions() as session, session.begin():
                ledger = self._ledger_replay(
                    session,
                    project_id=project_id,
                    kind="shidu.select_candidate",
                    key=idempotency_key,
                    payload=request_payload,
                )
                if ledger is not None:
                    return self._stable_result(ledger)
                repo = ShiduRepository(session)
                book = repo.select_book_discovery_candidate(
                    SelectBookDiscoveryCandidate(
                        project_id=project_id,
                        input_resolution_id=resolution_id,
                        candidate_id=candidate_id,
                        command_key=self._child_key(
                            idempotency_key, "selected-book"
                        ),
                    )
                ).value
                selection = repo.get_book_discovery_resolution(
                    project_id, resolution_id
                )
                if (
                    selection.status != "RESOLVED"
                    or selection.selected_book_id != book.id
                ):
                    raise InvalidRequest()
                research = repo.create_or_reuse_research_job(
                    CreateResearchJob(
                        project_id=project_id,
                        book_id=book.id,
                        provider_version=self._research_provider_version,
                        command_key=self._child_key(
                            idempotency_key, "research"
                        ),
                    )
                ).value
                result = self._stable_result({
                    "book": self._book_payload(book),
                    "researchJobId": str(research.id),
                })
                self._store_ledger(
                    session,
                    project_id=project_id,
                    kind="shidu.select_candidate",
                    key=idempotency_key,
                    payload=request_payload,
                    result=result,
                    status_code=200,
                )
                return result
        except (CommandConflict, InvalidRequest):
            raise
        except IdempotencyConflict as exc:
            raise CommandConflict() from exc
        except IntegrityError as exc:
            raise CommandConflict() from exc
        except (TypeError, ValueError) as exc:
            raise InvalidRequest() from exc

    def list_books(self, *, project_id: UUID, query: str) -> list[dict[str, Any]]:
        normalized = query.strip().casefold()
        with self._sessions() as session:
            statement = select(BookRecord).where(BookRecord.project_id == project_id)
            if normalized:
                statement = statement.where(func.lower(BookRecord.title).contains(normalized))
            books = session.scalars(statement.order_by(BookRecord.title, BookRecord.id).limit(50)).all()
            output = []
            for book in books:
                research = session.scalar(select(ResearchJobRecord).where(
                    ResearchJobRecord.project_id == project_id,
                    ResearchJobRecord.book_id == book.id,
                ).order_by(ResearchJobRecord.created_at.desc(), ResearchJobRecord.id.desc()))
                pack = None
                directions: list[dict[str, Any]] = []
                if research is not None:
                    pack = session.scalar(select(EvidencePackRevisionRecord).where(
                        EvidencePackRevisionRecord.project_id == project_id,
                        EvidencePackRevisionRecord.research_job_id == research.id,
                    ).order_by(EvidencePackRevisionRecord.revision.desc()))
                if pack is not None and pack.publishable:
                    rows = session.scalars(select(ResonanceDirectionRevisionRecord).where(
                        ResonanceDirectionRevisionRecord.project_id == project_id,
                        ResonanceDirectionRevisionRecord.evidence_pack_revision_id == pack.id,
                    ).order_by(ResonanceDirectionRevisionRecord.publication_ordinal)).all()
                    directions = [{
                        "id": str(item.id),
                        "directionKey": item.direction_key,
                        "score": item.score,
                        "payload": dict(item.payload),
                    } for item in rows]
                output.append({
                    "id": str(book.id),
                    "title": book.title,
                    "author": book.author,
                    "language": book.language,
                    "edition": book.edition,
                    "translator": book.translator,
                    "researchStatus": "not_started" if research is None else research.status,
                    "evidenceCoverage": {} if pack is None else dict(pack.coverage),
                    "contentMode": (
                        "source_grounded"
                        if pack is None
                        else str(
                            pack.coverage.get(
                                "content_mode", "source_grounded"
                            )
                        )
                    ),
                    "directions": directions,
                })
            return output

    def retry_research(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_payload = {"bookId": str(book_id)}
        try:
            with self._sessions() as session, session.begin():
                ledger = self._ledger_replay(
                    session,
                    project_id=project_id,
                    kind="shidu.retry_research",
                    key=idempotency_key,
                    payload=request_payload,
                )
                if ledger is not None:
                    return self._stable_result(ledger)
                repo = ShiduRepository(session)
                book = repo.get_book(project_id, book_id)
                research = repo.create_or_reuse_research_job(
                    CreateResearchJob(
                        project_id=project_id,
                        book_id=book.id,
                        provider_version=self._research_provider_version,
                        command_key=self._child_key(
                            idempotency_key, "research-retry"
                        ),
                    ),
                    reuse_insufficient=False,
                ).value
                result = self._stable_result({
                    "book": self._book_payload(book),
                    "researchJobId": str(research.id),
                })
                self._store_ledger(
                    session,
                    project_id=project_id,
                    kind="shidu.retry_research",
                    key=idempotency_key,
                    payload=request_payload,
                    result=result,
                    status_code=200,
                )
                return result
        except CommandConflict:
            raise
        except IdempotencyConflict as exc:
            raise CommandConflict() from exc
        except IntegrityError as exc:
            raise CommandConflict() from exc
        except (TypeError, ValueError) as exc:
            raise ResourceNotFound() from exc

    def director_preview(self, *, project_id: UUID, request: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
        book_id = UUID(str(request["bookId"]))
        direction_id = UUID(str(request["directionRevisionId"]))
        try:
            with self._sessions() as session, session.begin():
                replay = self._ledger_replay(
                    session,
                    project_id=project_id,
                    kind="shidu.director_preview",
                    key=idempotency_key,
                    payload=request,
                )
                if replay is not None:
                    return replay
                repo = ShiduRepository(session)
                direction, pack, _, _, direction_book_id = repo.load_direction_context(direction_id)
                if direction.project_id != project_id or direction_book_id != book_id or not pack.publishable:
                    raise InsufficientEvidence()
                script = session.scalar(select(TrialScriptRevisionRecord).where(
                    TrialScriptRevisionRecord.project_id == project_id,
                    TrialScriptRevisionRecord.book_id == book_id,
                    TrialScriptRevisionRecord.resonance_direction_revision_id == direction_id,
                ).order_by(TrialScriptRevisionRecord.revision.desc()))
                if script is None:
                    raise ResourceNotFound()
                preview = PreviewService(repo).build(script.id)
                payload = _camel(preview)
                result = {
                    "bookId": str(book_id),
                    "directionRevisionId": str(direction_id),
                    "scriptRevisionId": str(preview.script_revision_id),
                    "provisionalTitle": payload["provisional_title"],
                    "experiencePromise": payload["experience_promise"],
                    "openingLine": payload["opening_line"],
                    "openingLineKind": payload["opening_line_kind"],
                    "openingLineLabel": payload["opening_line_label"],
                    "contentMode": payload["content_mode"],
                    "contentLabel": payload["content_label"],
                    "contentNotice": payload["content_notice"],
                    "emotionCurve": payload["emotion_curve"],
                    "shots": [
                        {
                            "ordinal": item["ordinal"],
                            "narrativeTask": item["narrative_task"],
                            "action": item["action"],
                            "stateTransition": item["state_transition"],
                            "durationSeconds": item["duration_seconds"],
                        }
                        for item in payload["shots"]
                    ],
                    "durationEstimateSeconds": payload["duration_estimate_seconds"],
                    "fitFor": payload["fit_for"],
                    "notFitFor": payload["not_fit_for"],
                    "sourceSummaries": payload["source_summaries"],
                    "spoilerLevel": payload["spoiler_level"],
                    "riskFlags": payload["risk_flags"],
                }
                if request.get("customQuestion"):
                    result["customQuestion"] = str(request["customQuestion"])
                self._store_ledger(
                    session,
                    project_id=project_id,
                    kind="shidu.director_preview",
                    key=idempotency_key,
                    payload=request,
                    result=result,
                    status_code=200,
                )
                return result
        except (ResourceNotFound, InsufficientEvidence):
            raise
        except IntegrityError as exc:
            raise CommandConflict() from exc
        except ValueError as exc:
            raise ResourceNotFound() from exc

    def create_video_job(self, *, project_id: UUID, request: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
        canonical_request = dict(request)
        request_digest = canonical_json_digest(canonical_request)
        try:
            with self._sessions() as session, session.begin():
                ledger = self._ledger_replay(
                    session,
                    project_id=project_id,
                    kind="shidu.create_video_job",
                    key=idempotency_key,
                    payload=canonical_request,
                )
                if ledger is not None:
                    return ledger
                replay = session.scalar(select(VideoJobProjectionRecord).where(
                    VideoJobProjectionRecord.project_id == project_id,
                    VideoJobProjectionRecord.command_idempotency_key == idempotency_key,
                ))
                if replay is not None:
                    if replay.payload.get("requestDigest") != request_digest:
                        raise CommandConflict()
                    result = self._job_payload(replay, status="queued")
                    self._store_ledger(
                        session,
                        project_id=project_id,
                        kind="shidu.create_video_job",
                        key=idempotency_key,
                        payload=canonical_request,
                        result=result,
                        status_code=202,
                    )
                    return result
                repo = ShiduRepository(session)
                book_id = UUID(str(request["bookId"]))
                direction_id = UUID(str(request["directionRevisionId"]))
                script_id = UUID(str(request["trialScriptRevisionId"]))
                book = repo.get_book(project_id, book_id)
                script = repo.get_trial_script(script_id)
                script_safety = self._require_release_safety(script.payload)
                direction, pack, _, _, direction_book_id = repo.load_direction_context(direction_id)
                if (
                    book.id != script.book_id
                    or script.project_id != project_id
                    or script.resonance_direction_revision_id != direction.id
                    or direction_book_id != book.id
                    or not pack.publishable
                ):
                    raise InvalidRequest()
                preview = PreviewService(repo).build(script.id)
                prepared_reference = None
                if self._competition_reference_lookup is not None:
                    prepared_reference = self.get_competition_prepared_reference(
                        project_id=project_id,
                        request=canonical_request,
                    )
                    if prepared_reference is None:
                        raise DependencyUnavailable()
                disclosure = {
                    "contentMode": preview.content_mode,
                    "contentLabel": preview.content_label,
                    "contentNotice": preview.content_notice,
                }
                deferred_h3 = bool(
                    getattr(
                        self._submitter,
                        "defer_until_authority_ready",
                        False,
                    )
                )
                if deferred_h3:
                    submission_fields = {
                        "pipelineMode": "h3_deferred_vertical_slice",
                        "targetDurationSeconds": 3.0,
                        "sequenceCount": 1,
                    }
                    workflow_run_id = None
                else:
                    submission = self._submitter.submit(
                        project_id=project_id,
                        request=_h3_submission_request(
                            canonical_request,
                            disclosure,
                        ),
                        command_idempotency_key=self._child_key(idempotency_key, "workflow"),
                        created_by_actor=self._actor_id,
                    )
                    try:
                        submission_fields = _submission_projection_fields(
                            submission
                        )
                    except (TypeError, ValueError) as exc:
                        raise DependencyUnavailable() from exc
                    if (
                        submission.project_id != project_id
                        or submission.book_id != book.id
                        or submission.trial_script_revision_id != script.id
                    ):
                        raise DependencyUnavailable()
                    if submission.workflow_key == "factory.shidu-trial.v1":
                        try:
                            voice = repo.get_voice_preset_revision(
                                submission.voice_preset_revision_id
                            )
                        except ValueError as exc:
                            raise DependencyUnavailable() from exc
                        if voice.project_id != project_id or not voice.enabled:
                            raise DependencyUnavailable()
                    workflow_run_id = submission.workflow_run_id
                external_id = "shidu_" + uuid5(
                    NAMESPACE_URL, f"{project_id}:{idempotency_key}:{request_digest}"
                ).hex
                payload = {
                    **canonical_request,
                    **disclosure,
                    **submission_fields,
                    "requestDigest": request_digest,
                    "researchJobId": str(pack.research_job_id),
                    "safetyDecisionDigest": (
                        script_safety.release_decision_digest
                    ),
                }
                if prepared_reference is not None:
                    payload["competitionPreparedReference"] = {
                        "requestId": prepared_reference["requestId"],
                        "artifactSha256": prepared_reference["reference"]["sha256"],
                        "sourceMode": prepared_reference["sourceMode"],
                        "importAuthoritySha256": prepared_reference[
                            "importAuthoritySha256"
                        ],
                    }
                if workflow_run_id is not None:
                    payload["workflowRunId"] = str(workflow_run_id)
                record = VideoJobProjectionRecord(
                    project_id=project_id,
                    book_id=book.id,
                    trial_script_revision_id=script.id,
                    external_job_id=external_id,
                    status="queued",
                    payload=payload,
                    command_idempotency_key=idempotency_key,
                )
                session.add(record)
                session.flush()
                result = self._job_payload(record, status="queued")
                self._store_ledger(
                    session,
                    project_id=project_id,
                    kind="shidu.create_video_job",
                    key=idempotency_key,
                    payload=canonical_request,
                    result=result,
                    status_code=202,
                )
                return result
        except (CommandConflict, InvalidRequest):
            raise
        except IdempotencyConflict as exc:
            raise CommandConflict() from exc
        except IntegrityError as exc:
            raise CommandConflict() from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRequest() from exc

    def materialize_deferred_video_job(
        self,
        *,
        project_id: UUID,
        job_id: str,
    ) -> WorkflowSubmission:
        """Bind a clicked deferred job to the real production H3 submitter.

        Visual identity preparation runs before this method and persists the
        exact authority file consumed by ``ProductionH3WorkflowSubmitter``.
        The child idempotency key makes restart/retry safe without duplicating
        the workflow run.
        """

        with self._sessions() as session:
            record = session.scalar(
                select(VideoJobProjectionRecord).where(
                    VideoJobProjectionRecord.project_id == project_id,
                    VideoJobProjectionRecord.external_job_id == job_id,
                )
            )
            if record is None:
                raise ResourceNotFound()
            payload = dict(record.payload)
            existing_workflow = payload.get("workflowRunId")
            if existing_workflow is not None:
                return self._replay_materialized_h3_submission(
                    session,
                    project_id=project_id,
                    record=record,
                    payload=payload,
                )
            if (
                payload.get("pipelineMode") != "h3_deferred_vertical_slice"
                or payload.get("targetDurationSeconds") != 3.0
                or payload.get("sequenceCount") != 1
            ):
                raise InvalidRequest()
            request = {
                "bookId": str(record.book_id),
                "directionRevisionId": str(payload["directionRevisionId"]),
                "trialScriptRevisionId": str(record.trial_script_revision_id),
            }
            disclosure = {
                key: payload[key]
                for key in ("contentMode", "contentLabel", "contentNotice")
            }
            command_key = self._child_key(
                record.command_idempotency_key,
                "workflow",
            )

        submission = self._submitter.submit(
            project_id=project_id,
            request=_h3_submission_request(request, disclosure),
            command_idempotency_key=command_key,
            created_by_actor=self._actor_id,
        )
        try:
            projection_fields = _submission_projection_fields(submission)
        except (TypeError, ValueError) as exc:
            raise DependencyUnavailable() from exc
        if (
            submission.project_id != project_id
            or submission.book_id != UUID(request["bookId"])
            or submission.trial_script_revision_id
            != UUID(request["trialScriptRevisionId"])
            or submission.workflow_key != "factory.shidu-h3.v1"
        ):
            raise DependencyUnavailable()

        with self._sessions() as session, session.begin():
            record = session.scalar(
                select(VideoJobProjectionRecord)
                .where(
                    VideoJobProjectionRecord.project_id == project_id,
                    VideoJobProjectionRecord.external_job_id == job_id,
                )
                .with_for_update()
            )
            if record is None:
                raise ResourceNotFound()
            current = dict(record.payload)
            replay_workflow = current.get("workflowRunId")
            if replay_workflow is not None:
                if replay_workflow != str(submission.workflow_run_id):
                    raise CommandConflict()
                return submission
            if current.get("pipelineMode") != "h3_deferred_vertical_slice":
                raise CommandConflict()
            current.update(projection_fields)
            current["workflowRunId"] = str(submission.workflow_run_id)
            record.payload = current
            record.status = "queued"
            session.flush()
        return submission

    def publish_competition_reference_preview(
        self,
        *,
        project_id: UUID,
        job_id: str,
        job_authority_digest: str,
        reference: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Attach the one CAS-backed AI character image to the public job.

        This is an idempotent projection of an already committed artifact.  It
        never reads the local FLUX path and never starts or schedules GPU work.
        """

        from .competition_vertical_slice_worker import ClickedDeferredVideoJob

        try:
            raw = json.loads(
                json.dumps(
                    dict(reference),
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            if type(raw) is not dict:
                raise ValueError("reference must be a standard JSON object")
            artifact = AtomicArtifactRef.model_validate_json(
                json.dumps(raw["artifactRef"], separators=(",", ":")),
                strict=True,
            )
            expected_fields = {
                "viewName",
                "artifactRef",
                "publicationFencingToken",
                "sourcePath",
                "sha256",
                "promptSha256",
                "seed",
                "workflowSha256",
                "compiledWorkflowSha256",
                "generationAttemptOrdinal",
                "technicalFailureReceiptSha256",
                "remoteName",
                "mimeType",
                "format",
                "width",
                "height",
                "frameCount",
                "byteSize",
                "sourceMode",
                "generatedByCurrentFlux",
                "fluxOutputUsed",
                "importAuthoritySha256",
                "fluxProofPromptId",
                "fluxProofQueueId",
            }
            attempt = raw["generationAttemptOrdinal"]
            failure_receipt = raw["technicalFailureReceiptSha256"]
            if (
                set(raw) != expected_fields
                or raw["viewName"] != "front_three_quarter"
                or artifact.project_id != project_id
                or artifact.logical_role
                != "character.reference.competition-front-three-quarter"
                or str(artifact.content_digest) != raw["sha256"]
                or artifact.mime_type != raw["mimeType"]
                or artifact.byte_size != raw["byteSize"]
                or raw["mimeType"] not in {"image/png", "image/jpeg", "image/webp"}
                or {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
                    raw["format"]
                )
                != raw["mimeType"]
                or raw["frameCount"] != 1
                or type(raw["width"]) is not int
                or type(raw["height"]) is not int
                or raw["width"] < 256
                or raw["height"] < 256
                or raw["sourceMode"] != "preuploaded_imported"
                or raw["generatedByCurrentFlux"] is not False
                or raw["fluxOutputUsed"] is not False
                or type(raw["fluxProofPromptId"]) is not str
                or not raw["fluxProofPromptId"]
                or isinstance(raw["fluxProofQueueId"], bool)
                or type(raw["fluxProofQueueId"]) is not int
                or raw["fluxProofQueueId"] < 0
                or type(attempt) is not int
                or attempt not in {0, 1}
                or (attempt == 0 and failure_receipt is not None)
                or (
                    attempt == 1
                    and (
                        type(failure_receipt) is not str
                        or len(failure_receipt) != 64
                    )
                )
                or any(
                    type(raw[name]) is not str
                    or len(raw[name]) != 64
                    or any(char not in "0123456789abcdef" for char in raw[name])
                    for name in (
                        "sha256",
                        "promptSha256",
                        "workflowSha256",
                        "compiledWorkflowSha256",
                        "importAuthoritySha256",
                    )
                )
            ):
                raise ValueError("competition reference authority is invalid")
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRequest() from exc

        with self._sessions() as session, session.begin():
            record = session.scalar(
                select(VideoJobProjectionRecord)
                .where(
                    VideoJobProjectionRecord.project_id == project_id,
                    VideoJobProjectionRecord.external_job_id == job_id,
                )
                .with_for_update()
            )
            if record is None:
                raise ResourceNotFound()
            clicked = ClickedDeferredVideoJob.from_projection_record(record)
            if clicked.authority_digest != job_authority_digest:
                raise CommandConflict()
            identity = {
                "schemaVersion": "amd.competition-imported-reference-preview.v1",
                "jobAuthorityDigest": job_authority_digest,
                "referenceProfile": "competition-imported-single-view-v1",
                "sourceMode": "preuploaded_imported",
                "requiredImages": 1,
                "viewName": "front_three_quarter",
                "owner": "drama_factory",
                "artifactId": str(artifact.artifact_id),
                "artifactSha256": raw["sha256"],
                "promptSha256": raw["promptSha256"],
                "seed": raw["seed"],
                "workflowSha256": raw["workflowSha256"],
                "compiledWorkflowSha256": raw["compiledWorkflowSha256"],
                "generationAttemptOrdinal": attempt,
                "technicalFailureReceiptSha256": failure_receipt,
                "mimeType": raw["mimeType"],
                "width": raw["width"],
                "height": raw["height"],
                "generatedByCurrentFlux": False,
                "fluxOutputUsed": False,
                "importAuthoritySha256": raw["importAuthoritySha256"],
                "fluxProofPromptId": raw["fluxProofPromptId"],
                "fluxProofQueueId": raw["fluxProofQueueId"],
                "label": "Preuploaded imported asset",
            }
            preview = {
                **identity,
                "referenceDigest": canonical_json_digest(identity),
            }
            payload = dict(record.payload)
            replay = payload.get("competitionCharacterReference")
            if replay is not None and replay != preview:
                raise CommandConflict()
            payload["competitionCharacterReference"] = preview
            record.payload = payload
            session.flush()
            return preview

    @staticmethod
    def _replay_materialized_h3_submission(
        session: Session,
        *,
        project_id: UUID,
        record: VideoJobProjectionRecord,
        payload: Mapping[str, Any],
    ) -> WorkflowSubmission:
        """Re-attest a previously attached H3 workflow after restart."""

        try:
            workflow_run_id = UUID(str(payload["workflowRunId"]))
            visual_resolution_id = UUID(
                str(payload["visualIdentityResolutionId"])
            )
            target = payload["targetDurationSeconds"]
            sequence_count = payload["sequenceCount"]
            input_authority_digest = payload["inputAuthorityDigest"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CommandConflict() from exc
        if (
            payload.get("pipelineMode") != "h3_vertical_slice"
            or type(target) is not float
            or target != 3.0
            or type(sequence_count) is not int
            or sequence_count != 1
            or not isinstance(input_authority_digest, str)
            or len(input_authority_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in input_authority_digest
            )
        ):
            raise CommandConflict()
        run = session.scalar(
            select(WorkflowRunRecord).where(
                WorkflowRunRecord.id == workflow_run_id,
                WorkflowRunRecord.project_id == project_id,
            )
        )
        if run is None or run.project_id != project_id:
            raise CommandConflict()
        authority = run.input_payload
        structured = (
            authority.get("structured_inputs")
            if isinstance(authority, dict)
            else None
        )
        if (
            not isinstance(authority, dict)
            or not isinstance(structured, dict)
            or authority.get("book_id") != str(record.book_id)
            or authority.get("trial_script_revision_id")
            != str(record.trial_script_revision_id)
            or authority.get("visual_identity_resolution_id")
            != str(visual_resolution_id)
            or structured.get("requested_sequence_duration_seconds") != 3.0
            or structured.get("sequence_count") != 1
            or structured.get("native_audio") is not True
            or structured.get("subtitles") is not False
            or structured.get("input_authority_digest")
            != input_authority_digest
        ):
            raise CommandConflict()
        return WorkflowSubmission(
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            workflow_key="factory.shidu-h3.v1",
            book_id=record.book_id,
            trial_script_revision_id=record.trial_script_revision_id,
            visual_identity_resolution_id=visual_resolution_id,
            target_duration_seconds=target,
            sequence_count=sequence_count,
            input_authority_digest=input_authority_digest,
        )

    @staticmethod
    def _job_payload(
        record: VideoJobProjectionRecord,
        *,
        status: str,
        artifact_refs: Mapping[str, Any] | None = None,
        h3_projection: Mapping[str, Any] | None = None,
        competition_vertical_slice_ref: Mapping[str, Any] | None = None,
        h3_runtime_proof: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "jobId": record.external_job_id,
            "bookId": str(record.book_id),
            "status": status,
        }
        disclosure = {
            key: record.payload.get(key)
            for key in ("contentMode", "contentLabel", "contentNotice")
        }
        if all(isinstance(value, str) and value for value in disclosure.values()):
            payload.update(disclosure)
        character_reference = record.payload.get("competitionCharacterReference")
        if character_reference is not None:
            if not isinstance(character_reference, Mapping):
                raise ProjectionInvalid()
            payload["competitionCharacterReference"] = dict(character_reference)
        if artifact_refs is not None:
            payload["artifactRefs"] = dict(artifact_refs)
        if h3_projection is not None:
            if artifact_refs is not None or competition_vertical_slice_ref is not None:
                raise ProjectionInvalid()
            payload["_h3Projection"] = dict(h3_projection)
        if competition_vertical_slice_ref is not None:
            if artifact_refs is not None or h3_projection is not None:
                raise ProjectionInvalid()
            payload["competitionVerticalSliceRef"] = dict(
                competition_vertical_slice_ref
            )
        if h3_runtime_proof is not None:
            payload["_h3RuntimeProof"] = dict(h3_runtime_proof)
        return payload

    def get_video_job(self, *, project_id: UUID, job_id: str) -> dict[str, Any]:
        with self._sessions() as session:
            record = session.scalar(select(VideoJobProjectionRecord).where(
                VideoJobProjectionRecord.project_id == project_id,
                VideoJobProjectionRecord.external_job_id == job_id,
            ))
            if record is None:
                raise ResourceNotFound()
            if record.status == "failed":
                return self._job_payload(record, status="failed")
            if (
                record.status == "processing"
                and self._competition_runtime_proof_reader is not None
            ):
                worker_state = record.payload.get("competitionWorker")
                if (
                    isinstance(worker_state, dict)
                    and worker_state.get("status") == "active"
                ):
                    try:
                        from .competition_vertical_slice_worker import (
                            ClickedDeferredVideoJob,
                        )

                        clicked = ClickedDeferredVideoJob.from_projection_record(
                            record
                        )
                        runtime_proof = self._competition_runtime_proof_reader(
                            project_id=project_id,
                            job_authority_digest=clicked.authority_digest,
                        )
                    except (OSError, TypeError, ValueError, RuntimeError) as exc:
                        raise ProjectionInvalid() from exc
                    if runtime_proof is not None:
                        return self._job_payload(
                            record,
                            status="rendering",
                            h3_runtime_proof=runtime_proof,
                        )
            workflow_id = record.payload.get("workflowRunId")
            if not workflow_id:
                return self._job_payload(record, status="queued")
            research_id = record.payload.get("researchJobId")
            if not research_id:
                raise ProjectionInvalid()
            research = session.scalar(select(ResearchJobRecord).where(
                ResearchJobRecord.project_id == project_id,
                ResearchJobRecord.id == UUID(str(research_id)),
            ))
            if research is None or research.book_id != record.book_id:
                raise ProjectionInvalid()
            if research.status in {"insufficient", "failed"}:
                return self._job_payload(record, status="failed")
            if research.status != "ready":
                return self._job_payload(record, status="researching")
            run = session.scalar(select(WorkflowRunRecord).where(
                WorkflowRunRecord.project_id == project_id,
                WorkflowRunRecord.id == UUID(str(workflow_id)),
            ))
            competition_envelope = record.payload.get(
                "competitionVerticalSlice"
            )
            if run is not None and competition_envelope is not None:
                competition_ref = self._trusted_competition_vertical_slice(
                    session,
                    project_id=project_id,
                    workflow_run_id=run.id,
                    job_id=record.external_job_id,
                    video_job_projection_id=record.id,
                    delivery_revision_id=record.payload.get(
                        "competitionVerticalSliceDeliveryId"
                    ),
                    delivery_revision_digest=record.payload.get(
                        "competitionVerticalSliceDeliveryDigest"
                    ),
                    envelope=competition_envelope,
                )
                return self._job_payload(
                    record,
                    status="succeeded",
                    competition_vertical_slice_ref=competition_ref,
                )
            if run is None or run.status == "DRAFT":
                return self._job_payload(record, status="queued")
            if run.status in {"FAILED", "BLOCKED", "CANCELLED"}:
                return self._job_payload(record, status="failed")
            delivery = next((item for item in session.scalars(
                select(DeliveryRevisionRecord).where(DeliveryRevisionRecord.project_id == project_id)
                .order_by(DeliveryRevisionRecord.revision.desc())
            ).all() if item.payload.get("workflow_run_id") == str(run.id)), None)
            if delivery is not None:
                if delivery.payload.get("schema_version") == H3_PRODUCT_AUTHORITY_SCHEMA:
                    h3_projection = self._trusted_h3_projection(
                        session,
                        project_id=project_id,
                        workflow_run_id=run.id,
                        job=record,
                        delivery=delivery,
                    )
                    return self._job_payload(
                        record,
                        status="succeeded",
                        h3_projection=h3_projection,
                    )
                refs = self._trusted_delivery_artifacts(
                    session,
                    project_id=project_id,
                    workflow_run_id=run.id,
                    delivery=delivery,
                )
                return self._job_payload(
                    record,
                    status="succeeded",
                    artifact_refs=refs,
                )
            if run.status == "WAITING_HUMAN":
                return self._job_payload(record, status="failed")
            operations = session.scalars(select(OperationRunRecord).where(
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.workflow_run_id == run.id,
            )).all()
            complete = {item.node_key for item in operations if item.status == "SUCCEEDED"}
            try:
                status = _workflow_progress_status(
                    record.payload.get("pipelineMode"),
                    complete,
                    record.payload.get("sequenceCount"),
                )
            except ValueError as exc:
                raise ProjectionInvalid() from exc
            return self._job_payload(record, status=status)

    @staticmethod
    def _trusted_competition_vertical_slice(
        session: Session,
        *,
        project_id: UUID,
        workflow_run_id: UUID,
        job_id: str,
        video_job_projection_id: UUID,
        delivery_revision_id: object,
        delivery_revision_digest: object,
        envelope: object,
    ) -> dict[str, dict[str, Any]]:
        required = {
            "schemaVersion",
            "artifactId",
            "artifactDigest",
            "byteSize",
            "mimeType",
            "logicalRole",
            "requestedDurationSeconds",
            "frameCount",
            "fps",
            "nativeAudio",
            "subtitles",
            "actualDurationSeconds",
            "actualFrameCount",
            "actualFps",
            "actualVideoStreams",
            "actualAudioStreams",
            "actualSubtitleStreams",
            "mediaWarnings",
            "runnerResultDigest",
            "envelopeDigest",
        }
        if not isinstance(envelope, dict) or set(envelope) != required:
            raise ProjectionInvalid()
        identity = dict(envelope)
        envelope_digest = identity.pop("envelopeDigest", None)
        actual_duration = envelope.get("actualDurationSeconds")
        actual_frame_count = envelope.get("actualFrameCount")
        actual_fps = envelope.get("actualFps")
        media_warnings = envelope.get("mediaWarnings")
        expected_warnings: list[str] = []
        if type(actual_frame_count) is int and actual_frame_count != 73:
            expected_warnings.append(
                "ACTUAL_FRAME_COUNT_DEVIATES_FROM_REQUESTED_73"
            )
        if (
            isinstance(actual_fps, (int, float))
            and not isinstance(actual_fps, bool)
            and not math.isclose(float(actual_fps), 24.0, rel_tol=0.0, abs_tol=0.01)
        ):
            expected_warnings.append("ACTUAL_FPS_DEVIATES_FROM_REQUESTED_24")
        if (
            isinstance(actual_duration, (int, float))
            and not isinstance(actual_duration, bool)
            and not math.isclose(
                float(actual_duration), 73 / 24, rel_tol=0.0, abs_tol=0.25
            )
        ):
            expected_warnings.append(
                "ACTUAL_DURATION_DEVIATES_FROM_EXPECTED_73_OVER_24"
            )
        if (
            envelope.get("schemaVersion")
            != "amd.competition-vertical-slice.v1"
            or envelope.get("requestedDurationSeconds") != 3.0
            or envelope.get("frameCount") != 73
            or envelope.get("fps") != 24
            or envelope.get("nativeAudio") is not True
            or envelope.get("subtitles") is not False
            or isinstance(actual_duration, bool)
            or not isinstance(actual_duration, (int, float))
            or not 2.8 <= float(actual_duration) <= 3.5
            or type(actual_frame_count) is not int
            or not 65 <= actual_frame_count <= 90
            or isinstance(actual_fps, bool)
            or not isinstance(actual_fps, (int, float))
            or not 20.0 <= float(actual_fps) <= 30.0
            or not math.isclose(
                actual_frame_count / float(actual_fps),
                float(actual_duration),
                rel_tol=0.0,
                abs_tol=0.35,
            )
            or type(envelope.get("actualVideoStreams")) is not int
            or envelope["actualVideoStreams"] != 1
            or type(envelope.get("actualAudioStreams")) is not int
            or envelope["actualAudioStreams"] < 1
            or type(envelope.get("actualSubtitleStreams")) is not int
            or envelope["actualSubtitleStreams"] != 0
            or media_warnings != expected_warnings
            or envelope.get("mimeType") != "video/mp4"
            or envelope.get("logicalRole") != "final_episode"
            or type(envelope.get("byteSize")) is not int
            or envelope["byteSize"] <= 0
            or not isinstance(envelope_digest, str)
            or canonical_json_digest(identity) != envelope_digest
        ):
            raise ProjectionInvalid()
        try:
            artifact_id = UUID(str(envelope["artifactId"]))
        except (TypeError, ValueError) as exc:
            raise ProjectionInvalid() from exc
        artifact_digest = envelope.get("artifactDigest")
        runner_digest = envelope.get("runnerResultDigest")
        if not all(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
            for value in (artifact_digest, runner_digest)
        ):
            raise ProjectionInvalid()
        try:
            delivery_id = UUID(str(delivery_revision_id))
        except (TypeError, ValueError) as exc:
            raise ProjectionInvalid() from exc
        if (
            not isinstance(delivery_revision_digest, str)
            or len(delivery_revision_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in delivery_revision_digest
            )
        ):
            raise ProjectionInvalid()
        delivery = session.scalar(
            select(DeliveryRevisionRecord).where(
                DeliveryRevisionRecord.id == delivery_id,
                DeliveryRevisionRecord.project_id == project_id,
            )
        )
        expected_delivery = {
            "schema_version": "amd.competition-vertical-slice-delivery.v1",
            "workflow_run_id": str(workflow_run_id),
            "video_job_projection_id": str(video_job_projection_id),
            "job_id": job_id,
            "envelope": envelope,
        }
        if (
            delivery is None
            or delivery.project_id != project_id
            or delivery.digest != delivery_revision_digest
            or canonical_json_digest(expected_delivery)
            != delivery_revision_digest
            or delivery.payload != expected_delivery
            or delivery.created_by_actor != "amd.competition-vertical-slice"
        ):
            raise ProjectionInvalid()
        artifact = session.scalar(
            select(ArtifactRecordRow).where(
                ArtifactRecordRow.id == artifact_id,
                ArtifactRecordRow.project_id == project_id,
                ArtifactRecordRow.status == "COMMITTED",
            )
        )
        if (
            artifact is None
            or artifact.project_id != project_id
            or artifact.content_digest != artifact_digest
            or artifact.byte_size != envelope["byteSize"]
            or artifact.mime_type != "video/mp4"
            or artifact.logical_role != "final_episode"
            or artifact.status != "COMMITTED"
        ):
            raise ProjectionInvalid()
        operation = session.scalar(
            select(OperationRunRecord).where(
                OperationRunRecord.id == artifact.operation_run_id,
                OperationRunRecord.project_id == project_id,
            )
        )
        if (
            operation is None
            or operation.project_id != project_id
            or operation.workflow_run_id != workflow_run_id
            or operation.node_key != "sequence.001.execute"
            or operation.op_type != "h3.sequence.execute"
            or operation.status != "SUCCEEDED"
            or operation.accepted_attempt_id != artifact.operation_attempt_id
            or artifact.publication_key
            != f"competition-three-second:{job_id}"
        ):
            raise ProjectionInvalid()
        attempt = session.scalar(
            select(OperationAttemptRecord).where(
                OperationAttemptRecord.id == artifact.operation_attempt_id,
                OperationAttemptRecord.project_id == project_id,
                OperationAttemptRecord.operation_run_id == operation.id,
            )
        )
        state = session.scalar(
            select(OperationAttemptStateRecord).where(
                OperationAttemptStateRecord.attempt_id
                == artifact.operation_attempt_id,
                OperationAttemptStateRecord.project_id == project_id,
            )
        )
        workflow = session.scalar(
            select(WorkflowRunRecord).where(
                WorkflowRunRecord.id == workflow_run_id,
                WorkflowRunRecord.project_id == project_id,
            )
        )
        structured_inputs = (
            workflow.input_payload.get("structured_inputs")
            if workflow is not None and isinstance(workflow.input_payload, dict)
            else None
        )
        input_authority_digest = (
            structured_inputs.get("input_authority_digest")
            if isinstance(structured_inputs, dict)
            else None
        )
        execution_authority_sha = attempt.request_payload.get(
            "h3ExecutionAuthoritySha256"
        ) if attempt is not None else None
        if (
            attempt is None
            or state is None
            or workflow is None
            or attempt.worker_id != "amd.competition-vertical-slice"
            or attempt.implementation_digest
            != COMPETITION_RUNNER_IMPLEMENTATION_DIGEST
            or attempt.request_payload.get("jobId") != job_id
            or attempt.request_payload.get("runnerResultDigest")
            != runner_digest
            or attempt.request_payload.get("inputAuthorityDigest")
            != input_authority_digest
            or not isinstance(input_authority_digest, str)
            or len(input_authority_digest) != 64
            or not isinstance(execution_authority_sha, str)
            or len(execution_authority_sha) != 64
            or any(
                character not in "0123456789abcdef"
                for digest in (input_authority_digest, execution_authority_sha)
                for character in digest
            )
            or attempt.request_payload.get("resultSha256") != artifact_digest
            or attempt.request_payload.get("requestedDurationSeconds") != 3.0
            or attempt.request_payload.get("frameCount") != 73
            or attempt.request_payload.get("fps") != 24
            or attempt.request_payload.get("nativeAudio") is not True
            or attempt.request_payload.get("subtitles") is not False
            or attempt.request_payload.get("actualMedia")
            != {
                "durationSeconds": float(actual_duration),
                "frameCount": actual_frame_count,
                "fps": float(actual_fps),
                "videoStreams": 1,
                "audioStreams": envelope["actualAudioStreams"],
                "subtitleStreams": 0,
                "warnings": expected_warnings,
            }
            or state.status != "SUCCEEDED"
            or state.stage != "COMMITTED"
        ):
            raise ProjectionInvalid()
        return {
            "owner": "drama_factory",
            "artifactId": str(artifact_id),
            "requestedDurationSeconds": 3.0,
            "frameCount": 73,
            "fps": 24,
            "nativeAudio": True,
            "subtitles": False,
            "actualDurationSeconds": float(actual_duration),
            "actualFrameCount": actual_frame_count,
            "actualFps": float(actual_fps),
            "mediaWarnings": expected_warnings,
        }

    @staticmethod
    def _trusted_h3_projection(
        session: Session,
        *,
        project_id: UUID,
        workflow_run_id: UUID,
        job: VideoJobProjectionRecord,
        delivery: DeliveryRevisionRecord,
    ) -> dict[str, Any]:
        payload = delivery.payload
        required_payload_keys = {
            "schema_version",
            "workflow_run_id",
            "video_job_projection_id",
            "authority",
            "asset_authorities",
        }
        if (
            delivery.project_id != project_id
            or job.project_id != project_id
            or not isinstance(payload, dict)
            or set(payload) != required_payload_keys
            or payload.get("schema_version") != H3_PRODUCT_AUTHORITY_SCHEMA
            or payload.get("workflow_run_id") != str(workflow_run_id)
            or payload.get("video_job_projection_id") != str(job.id)
        ):
            raise ProjectionInvalid()
        authority = payload.get("authority")
        declared_assets = payload.get("asset_authorities")
        if not isinstance(authority, dict) or not isinstance(declared_assets, dict):
            raise ProjectionInvalid()
        authority_digest = canonical_json_digest(authority)
        if not hmac.compare_digest(authority_digest, delivery.digest):
            raise ProjectionInvalid()

        expected_assets: dict[str, tuple[str, str | None]] = {}

        def declare_asset(
            raw_asset_id: Any,
            *,
            kind: str,
            expected_digest: Any = None,
        ) -> None:
            try:
                asset_id = str(UUID(str(raw_asset_id)))
            except (TypeError, ValueError) as exc:
                raise ProjectionInvalid() from exc
            digest = None if expected_digest is None else str(expected_digest)
            if digest is not None and (
                len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ProjectionInvalid()
            previous = expected_assets.setdefault(asset_id, (kind, digest))
            if previous != (kind, digest):
                raise ProjectionInvalid()

        try:
            episode = authority["episode"]
            for sequence in episode["sequence_plans"]:
                for binding in sequence["reference_bindings"]:
                    for view in binding["reference_set"]["views"]:
                        declare_asset(
                            view["asset_id"],
                            kind="reference",
                            expected_digest=view["image_digest"],
                        )
            assembly = authority["delivery"]["assembly_manifest"]
            declare_asset(assembly["playback_asset_id"], kind="video")
            declare_asset(assembly["download_asset_id"], kind="video")
            delivery_digest = str(authority["delivery"]["delivery_digest"])
        except (KeyError, TypeError) as exc:
            raise ProjectionInvalid() from exc
        if (
            not expected_assets
            or len(delivery_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in delivery_digest
            )
            or set(declared_assets) != set(expected_assets)
        ):
            raise ProjectionInvalid()

        artifact_ids = tuple(UUID(value) for value in expected_assets)
        artifacts = session.scalars(
            select(ArtifactRecordRow).where(
                ArtifactRecordRow.project_id == project_id,
                ArtifactRecordRow.id.in_(artifact_ids),
                ArtifactRecordRow.status == "COMMITTED",
            )
        ).all()
        stored_assets = {str(item.id): item for item in artifacts}
        if set(stored_assets) != set(expected_assets):
            raise ProjectionInvalid()

        public_refs: dict[str, dict[str, str]] = {}
        authority_keys = {
            "owner",
            "artifact_id",
            "artifact_digest",
            "byte_size",
            "mime_type",
            "logical_role",
        }
        for asset_id, (kind, expected_digest) in expected_assets.items():
            declared = declared_assets.get(asset_id)
            stored = stored_assets[asset_id]
            if (
                not isinstance(declared, dict)
                or set(declared) != authority_keys
                or declared.get("owner") != "drama_factory"
                or declared.get("artifact_id") != asset_id
                or declared.get("artifact_digest") != stored.content_digest
                or declared.get("byte_size") != stored.byte_size
                or declared.get("mime_type") != stored.mime_type
                or declared.get("logical_role") != stored.logical_role
                or stored.project_id != project_id
                or stored.status != "COMMITTED"
                or type(stored.byte_size) is not int
                or stored.byte_size <= 0
            ):
                raise ProjectionInvalid()
            if kind == "reference":
                if (
                    stored.content_digest != expected_digest
                    or stored.mime_type not in {
                        "image/jpeg",
                        "image/png",
                        "image/webp",
                    }
                    or not stored.logical_role.startswith("character.reference.")
                ):
                    raise ProjectionInvalid()
                purpose = "reference"
            else:
                if (
                    stored.mime_type != "video/mp4"
                    or stored.logical_role != "final_episode"
                ):
                    raise ProjectionInvalid()
                purpose = "video"
            public_refs[asset_id] = {
                "owner": "drama_factory",
                "artifact_id": asset_id,
                "purpose": purpose,
            }

        return {
            "authority": authority,
            "delivery_record": {
                "delivery_record_id": str(delivery.id),
                "project_id": str(project_id),
                "delivery_digest": delivery_digest,
                "authority_digest": authority_digest,
            },
            "asset_refs": public_refs,
        }

    @staticmethod
    def _trusted_delivery_artifacts(
        session: Session,
        *,
        project_id: UUID,
        workflow_run_id: UUID,
        delivery: DeliveryRevisionRecord,
    ) -> dict[str, dict[str, str]]:
        payload = dict(delivery.payload)
        if canonical_json_digest(payload) != delivery.digest:
            raise ProjectionInvalid()
        try:
            final_artifact_id = UUID(str(payload["final_artifact_id"]))
            final_digest = str(payload["final_artifact_digest"])
            machine_gate_key = str(payload["machine_gate_key"])
            machine_selection_id = UUID(
                str(payload["machine_selection_revision_id"])
            )
            qc_outcome = payload["qc_outcome"]
            repair_chain = payload["repair_chain"]
            authorities = payload["public_artifacts"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectionInvalid() from exc
        accepted = session.scalar(
            select(SelectionRevisionRecord)
            .join(
                SelectionHeadRecord,
                SelectionHeadRecord.id
                == SelectionRevisionRecord.selection_head_id,
            )
            .where(
                SelectionRevisionRecord.id == machine_selection_id,
                SelectionRevisionRecord.project_id == project_id,
                SelectionRevisionRecord.artifact_id == final_artifact_id,
                SelectionRevisionRecord.artifact_digest == final_digest,
                SelectionRevisionRecord.decision == "SELECTED",
                SelectionHeadRecord.project_id == project_id,
                SelectionHeadRecord.workflow_run_id == workflow_run_id,
                SelectionHeadRecord.selection_key == machine_gate_key,
                SelectionHeadRecord.selection_key == "final-gate",
                SelectionHeadRecord.status == "SEALED",
                SelectionHeadRecord.current_revision
                == SelectionRevisionRecord.revision,
            )
        )
        expected = {
            "video": ("video/mp4", "final_episode", "video"),
            "subtitle": (
                "application/x-subrip",
                "subtitle_track",
                "subtitle",
            ),
            "cover": ("image/jpeg", "cover_image", "cover"),
            "share_card": ("image/jpeg", "share_card", "shareCard"),
        }
        if accepted is None or not isinstance(authorities, dict) or set(
            authorities
        ) != set(expected):
            raise ProjectionInvalid()
        if not isinstance(qc_outcome, dict) or not isinstance(
            repair_chain, list
        ) or not repair_chain:
            raise ProjectionInvalid()
        try:
            evaluation_id = UUID(str(qc_outcome["evaluation_id"]))
            evaluation_digest = str(qc_outcome["evaluation_digest"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectionInvalid() from exc
        if (
            qc_outcome.get("selection_decision") != "SELECTED"
            or accepted.payload.get("evaluation_id")
            != str(evaluation_id)
            or accepted.payload.get("evaluation_digest")
            != evaluation_digest
        ):
            raise ProjectionInvalid()
        evaluation = session.scalar(
            select(QCEvaluationFactRecord).where(
                QCEvaluationFactRecord.id == evaluation_id,
                QCEvaluationFactRecord.project_id == project_id,
                QCEvaluationFactRecord.workflow_run_id == workflow_run_id,
                QCEvaluationFactRecord.stage == "final",
                QCEvaluationFactRecord.gate_key == "final-gate",
                QCEvaluationFactRecord.artifact_id == final_artifact_id,
                QCEvaluationFactRecord.artifact_digest == final_digest,
                QCEvaluationFactRecord.artifact_operation_run_id
                == accepted.selected_operation_run_id,
                QCEvaluationFactRecord.artifact_operation_attempt_id
                == accepted.selected_attempt_id,
                QCEvaluationFactRecord.evaluation_digest
                == evaluation_digest,
                QCEvaluationFactRecord.judgment == "PASS",
            )
        )
        if (
            evaluation is None
            or qc_outcome.get("judgment") != evaluation.judgment
            or qc_outcome.get("quality_score") != evaluation.quality_score
            or qc_outcome.get("confidence") != evaluation.confidence
            or qc_outcome.get("unresolved_defects")
            != evaluation.defects
            or not any(
                isinstance(item, dict)
                and item.get("evaluation_id") == str(evaluation.id)
                and item.get("evaluation_digest")
                == evaluation.evaluation_digest
                for item in repair_chain
            )
        ):
            raise ProjectionInvalid()
        selected_operation = session.scalar(
            select(OperationRunRecord).where(
                OperationRunRecord.id
                == accepted.selected_operation_run_id,
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.workflow_run_id == workflow_run_id,
                OperationRunRecord.node_key == "assemble",
                OperationRunRecord.op_type == "final.assemble",
                OperationRunRecord.status == "SUCCEEDED",
                OperationRunRecord.accepted_attempt_id
                == accepted.selected_attempt_id,
            )
        )
        if selected_operation is None:
            raise ProjectionInvalid()
        final_gate = session.scalar(
            select(OperationRunRecord).where(
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.workflow_run_id == workflow_run_id,
                OperationRunRecord.node_key == "final-gate",
                OperationRunRecord.op_type == "qc.gate.final",
                OperationRunRecord.status == "SUCCEEDED",
            )
        )
        if final_gate is None:
            raise ProjectionInvalid()
        final_edge = session.scalar(
            select(WorkflowRunEdgeRecord.id).where(
                WorkflowRunEdgeRecord.project_id == project_id,
                WorkflowRunEdgeRecord.workflow_run_id == workflow_run_id,
                WorkflowRunEdgeRecord.upstream_operation_run_id
                == selected_operation.id,
                WorkflowRunEdgeRecord.downstream_operation_run_id
                == final_gate.id,
            )
        )
        if final_edge is None:
            raise ProjectionInvalid()
        ids: dict[str, UUID] = {}
        for key, authority in authorities.items():
            if not isinstance(authority, dict):
                raise ProjectionInvalid()
            try:
                ids[key] = UUID(str(authority["artifact_id"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectionInvalid() from exc
        rows = {
            item.id: item
            for item in session.scalars(select(ArtifactRecordRow).where(
                ArtifactRecordRow.project_id == project_id,
                ArtifactRecordRow.id.in_(tuple(ids.values())),
                ArtifactRecordRow.status == "COMMITTED",
            )).all()
        }
        refs: dict[str, dict[str, str]] = {}
        for key, (mime_type, logical_role, public_key) in expected.items():
            authority = authorities[key]
            artifact = rows.get(ids[key])
            if (
                artifact is None
                or authority.get("owner") != "drama_factory"
                or authority.get("artifact_digest")
                != artifact.content_digest
                or authority.get("byte_size") != artifact.byte_size
                or authority.get("mime_type") != mime_type
                or authority.get("logical_role") != logical_role
                or artifact.mime_type != mime_type
                or artifact.logical_role != logical_role
            ):
                raise ProjectionInvalid()
            refs[public_key] = {
                "owner": "drama_factory",
                "artifactId": str(artifact.id),
            }
        video = authorities["video"]
        subtitle_id = ids["subtitle"]
        subtitle_edge = session.scalar(
            select(ArtifactLineageEdgeRecord.id).where(
                ArtifactLineageEdgeRecord.project_id == project_id,
                ArtifactLineageEdgeRecord.output_artifact_id
                == final_artifact_id,
                ArtifactLineageEdgeRecord.input_artifact_id == subtitle_id,
                ArtifactLineageEdgeRecord.role == "subtitle_track",
            )
        )
        if (
            ids["video"] != final_artifact_id
            or video.get("artifact_digest") != final_digest
            or rows[ids["video"]].operation_run_id
            != accepted.selected_operation_run_id
            or rows[ids["video"]].operation_attempt_id
            != accepted.selected_attempt_id
            or rows[ids["cover"]].operation_run_id
            != accepted.selected_operation_run_id
            or rows[ids["cover"]].operation_attempt_id
            != accepted.selected_attempt_id
            or rows[ids["share_card"]].operation_run_id
            != accepted.selected_operation_run_id
            or rows[ids["share_card"]].operation_attempt_id
            != accepted.selected_attempt_id
            or subtitle_edge is None
        ):
            raise ProjectionInvalid()
        return refs

    def add_feedback(self, *, project_id: UUID, request: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
        payload = dict(request)
        digest = canonical_json_digest(payload)
        try:
            with self._sessions() as session, session.begin():
                ledger = self._ledger_replay(
                    session,
                    project_id=project_id,
                    kind="shidu.add_feedback",
                    key=idempotency_key,
                    payload=payload,
                )
                if ledger is not None:
                    return ledger
                replay = session.scalar(select(ReaderFeedbackRecord).where(
                    ReaderFeedbackRecord.project_id == project_id,
                    ReaderFeedbackRecord.command_idempotency_key == idempotency_key,
                ))
                if replay is not None:
                    if replay.digest != digest:
                        raise CommandConflict()
                    result = {"feedbackId": str(replay.id), "accepted": True}
                    self._store_ledger(
                        session,
                        project_id=project_id,
                        kind="shidu.add_feedback",
                        key=idempotency_key,
                        payload=payload,
                        result=result,
                        status_code=200,
                    )
                    return result
                repo = ShiduRepository(session)
                book_id = UUID(str(request["bookId"]))
                direction_id = UUID(str(request["directionRevisionId"]))
                moment_id = request.get("momentRevisionId")
                if moment_id is not None and UUID(str(moment_id)) != direction_id:
                    raise InvalidRequest()
                repo.get_book(project_id, book_id)
                direction, pack, _, _, direction_book_id = repo.load_direction_context(direction_id)
                if direction.project_id != project_id or direction_book_id != book_id or not pack.publishable:
                    raise InvalidRequest()
                wants = request.get("wantsToRead")
                rating = 5 if wants is True else 1 if wants is False else None
                record = ReaderFeedbackRecord(
                    project_id=project_id,
                    book_id=book_id,
                    rating=rating,
                    payload=payload,
                    digest=digest,
                    command_idempotency_key=idempotency_key,
                )
                session.add(record)
                session.flush()
                result = {"feedbackId": str(record.id), "accepted": True}
                self._store_ledger(
                    session,
                    project_id=project_id,
                    kind="shidu.add_feedback",
                    key=idempotency_key,
                    payload=payload,
                    result=result,
                    status_code=200,
                )
                return result
        except (CommandConflict, InvalidRequest):
            raise
        except IntegrityError as exc:
            raise CommandConflict() from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRequest() from exc


__all__ = [
    "ApiServiceError", "CommandConflict", "DependencyUnavailable",
    "InsufficientEvidence", "InvalidRequest", "ProjectionInvalid",
    "PUBLIC_JOB_STATES", "ResourceNotFound", "ShiduApiService",
    "SqlAlchemyShiduService", "WorkflowSubmitter",
    "WorkflowSubmission",
]
