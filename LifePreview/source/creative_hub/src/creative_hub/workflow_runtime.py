"""Integration adapters for catalog workflows.

This module contains no alternate queue, object catalog, provider state
machine, quality engine, or review store.  It binds the existing T4/T5/T10/T11
authorities to the T9 atomic capability boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import UUID

from shared_contracts import (
    AtomicArtifactRef,
    OperationRequest,
    PersistentArtifactRef,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .artifact_publication import (
    ArtifactConflict,
    ArtifactRecord,
    ArtifactPublicationRepository,
    ArtifactPublicationService,
    ArtifactStatus,
    ArtifactUnavailable,
    ContentAddressedArtifactStore,
    H3ArtifactBatchManifestEntry,
    build_h3_batch_manifest_digest,
    build_h3_batch_publication_key,
)
from .db.models import (
    ArtifactLineageEdgeRecord,
    ArtifactRecordRow,
    HumanReviewTaskRecord,
    OperationAttemptRecord,
    OperationRunRecord,
    QCCandidateVersionRecord,
    QCEvaluationFactRecord,
    SelectionHeadRecord,
    SelectionRevisionRecord,
)
from .gate_engine import GateEngine, SelectionSealer
from .lineage import (
    ArtifactLineageGraph,
    ArtifactLineageUnavailable,
    LineageInput,
)
from .qc_repository import QualityRepository
from .quality import (
    CandidateVersion,
    GateOutcome,
    GateOutcomeKind,
    GatePolicySnapshot,
    RepairProposal,
)


class ProducedArtifact(Protocol):
    payload: bytes
    mime_type: str
    logical_role: str
    retention_class: Any


class HumanReviewSink(Protocol):
    """Historical extension point; the retained Shidu runtime passes none."""

    def open_for_gate(self, **kwargs): ...


AttemptIdentity = Callable[[OperationRequest], tuple[int, int]]


class _PublicationBatchState(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"


class PublicationArtifactBatch:
    """One request-bound set of artifacts with atomic catalog visibility."""

    __slots__ = (
        "_lock",
        "_project_id",
        "_publication",
        "_staging_tokens",
        "_state",
        "refs",
    )

    def __init__(
        self,
        *,
        publication: ArtifactPublicationService,
        project_id: UUID,
        staging_tokens: tuple[UUID, ...],
        refs: tuple[PersistentArtifactRef, ...],
        committed: bool = False,
    ) -> None:
        self._publication = publication
        self._project_id = project_id
        self._staging_tokens = staging_tokens
        self.refs = refs
        self._state = (
            _PublicationBatchState.COMMITTED
            if committed
            else _PublicationBatchState.PENDING
        )
        self._lock = RLock()

    def commit(self) -> None:
        with self._lock:
            if self._state is _PublicationBatchState.COMMITTED:
                return
            if self._state is _PublicationBatchState.ROLLED_BACK:
                raise ArtifactUnavailable(
                    "artifact publication batch was rolled back and is unavailable"
                )
            self._publication.finalize_batch(
                project_id=self._project_id,
                staging_tokens=self._staging_tokens,
            )
            self._state = _PublicationBatchState.COMMITTED

    def rollback(self) -> None:
        with self._lock:
            if self._state in {
                _PublicationBatchState.COMMITTED,
                _PublicationBatchState.ROLLED_BACK,
            }:
                return
            records = self._publication.abort_batch(
                project_id=self._project_id,
                staging_tokens=self._staging_tokens,
            )
            self._state = (
                _PublicationBatchState.COMMITTED
                if all(
                    record.status is ArtifactStatus.COMMITTED
                    for record in records
                )
                else _PublicationBatchState.ROLLED_BACK
            )


class PublicationArtifactGateway:
    """T9 artifact gateway backed by T5 publication and lineage."""

    def __init__(
        self,
        *,
        publication: ArtifactPublicationService,
        repository: ArtifactPublicationRepository,
        store: ContentAddressedArtifactStore,
        lineage: ArtifactLineageGraph,
        attempt_identity: AttemptIdentity,
    ) -> None:
        self.publication = publication
        self.repository = repository
        self.store = store
        self.lineage = lineage
        self.attempt_identity = attempt_identity

    def read_bytes(self, artifact: AtomicArtifactRef, /) -> bytes:
        record = self.repository.get_visible(
            project_id=artifact.project_id,
            artifact_id=artifact.artifact_id,
        )
        if (
            record.content_digest != artifact.content_digest
            or record.byte_size != artifact.byte_size
            or record.mime_type != artifact.mime_type
        ):
            raise ArtifactLineageUnavailable(
                "artifact identity changed before capability execution"
            )
        path = self.store.object_path(record.content_digest)
        return Path(path).read_bytes()

    def stage_batch(
        self,
        artifacts: tuple[ProducedArtifact, ...],
        /,
        *,
        request: OperationRequest,
        created_at: datetime,
    ) -> PublicationArtifactBatch:
        if not isinstance(request, OperationRequest):
            raise TypeError("artifact batch requires OperationRequest")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("artifact batch created_at must be timezone-aware")
        produced = tuple(artifacts)
        if not produced:
            raise ValueError("artifact publication batch cannot be empty")
        manifest_entries = tuple(
            H3ArtifactBatchManifestEntry(
                content_digest=_content_digest(bytes(artifact.payload)),
                byte_size=len(bytes(artifact.payload)),
                mime_type=artifact.mime_type,
                logical_role=artifact.logical_role,
                retention_class=artifact.retention_class,
            )
            for artifact in produced
        )
        manifest_digest = build_h3_batch_manifest_digest(manifest_entries)
        batch_count = len(produced)

        attempt_number, fencing_token = self.attempt_identity(request)
        records: list[ArtifactRecord] = []
        staging_locators: list[str] = []
        batch_created_at = created_at
        try:
            for ordinal, artifact in enumerate(produced):
                payload = bytes(artifact.payload)
                digest = _content_digest(payload)
                claim = self.publication.begin(
                    project_id=request.project_id,
                    operation_run_id=request.operation_run_id,
                    attempt_id=request.operation_attempt_id,
                    attempt_number=attempt_number,
                    fencing_token=fencing_token,
                    publication_key=build_h3_batch_publication_key(
                        manifest_digest=manifest_digest,
                        count=batch_count,
                        ordinal=ordinal,
                    ),
                    now=batch_created_at,
                )
                if ordinal == 0:
                    # A partial-prefix replay must use the first persisted
                    # batch member's timestamp for every missing member.
                    batch_created_at = claim.created_at
                try:
                    staged = self.publication.stage(
                        claim=claim,
                        stream=(payload,),
                        mime_type=artifact.mime_type,
                        expected_digest=digest,
                        expected_size=len(payload),
                    )
                except Exception:
                    self._remember_registered_record(
                        project_id=request.project_id,
                        staging_token=claim.staging_token,
                        records=records,
                    )
                    raise
                staging_locators.append(staged.staging_locator)
                try:
                    record = self.publication.register(
                        claim=claim,
                        staged=staged,
                        logical_role=artifact.logical_role,
                        retention_class=artifact.retention_class,
                        now=claim.created_at,
                    )
                except Exception:
                    self._remember_registered_record(
                        project_id=request.project_id,
                        staging_token=claim.staging_token,
                        records=records,
                    )
                    raise
                records.append(record)
        except Exception:
            self._abandon_staged_batch(
                project_id=request.project_id,
                records=records,
                staging_locators=staging_locators,
            )
            raise

        try:
            return self._build_publication_batch(
                produced=produced,
                records=records,
                request=request,
                attempt_number=attempt_number,
                fencing_token=fencing_token,
                staging_locators=staging_locators,
            )
        except Exception:
            self._abandon_staged_batch(
                project_id=request.project_id,
                records=records,
                staging_locators=staging_locators,
            )
            raise

    def _build_publication_batch(
        self,
        *,
        produced: tuple[ProducedArtifact, ...],
        records: list[ArtifactRecord],
        request: OperationRequest,
        attempt_number: int,
        fencing_token: int,
        staging_locators: list[str],
    ) -> PublicationArtifactBatch:
        statuses = {record.status for record in records}
        committed = statuses == {ArtifactStatus.COMMITTED}
        if statuses not in (
            {ArtifactStatus.PENDING},
            {ArtifactStatus.COMMITTED},
        ):
            if ArtifactStatus.TOMBSTONED in statuses:
                raise ArtifactUnavailable(
                    "artifact publication batch is unavailable"
                )
            raise ArtifactConflict(
                "artifact publication batch has mixed visibility"
            )

        refs: list[PersistentArtifactRef] = []
        persisted_created_at = records[0].created_at
        for artifact, record in zip(produced, records, strict=True):
            payload = bytes(artifact.payload)
            if (
                record.project_id != request.project_id
                or record.operation_run_id != request.operation_run_id
                or record.attempt_id != request.operation_attempt_id
                or record.attempt_number != attempt_number
                or record.fencing_token != fencing_token
                or record.content_digest != _content_digest(payload)
                or record.byte_size != len(payload)
                or record.mime_type != artifact.mime_type
                or record.logical_role != artifact.logical_role
                or record.retention_class != artifact.retention_class
                or record.created_at != persisted_created_at
            ):
                raise ArtifactConflict(
                    "staged artifact batch identity changed"
                )
            if record.status is ArtifactStatus.COMMITTED:
                ref = record.persistent_ref()
            else:
                ref = PersistentArtifactRef(
                    artifact_id=record.artifact_id,
                    project_id=record.project_id,
                    content_digest=record.content_digest,
                    mime_type=record.mime_type,
                    byte_size=record.byte_size,
                    logical_role=record.logical_role,
                    storage_uri=self.store.storage_uri(
                        record.content_digest
                    ),
                    produced_by_operation_run_id=record.operation_run_id,
                    produced_by_operation_attempt_id=record.attempt_id,
                    created_at=record.created_at,
                    retention_class=record.retention_class,
                )
            refs.append(ref)
        if len({ref.artifact_id for ref in refs}) != len(refs):
            raise ArtifactConflict(
                "artifact publication batch contains duplicate artifacts"
            )
        if committed:
            for locator in staging_locators:
                self.store.discard_staging(locator)
        return PublicationArtifactBatch(
            publication=self.publication,
            project_id=request.project_id,
            staging_tokens=tuple(
                record.staging_token for record in records
            ),
            refs=tuple(refs),
            committed=committed,
        )

    def _abandon_staged_batch(
        self,
        *,
        project_id: UUID,
        records: list[ArtifactRecord],
        staging_locators: list[str],
    ) -> None:
        try:
            if records:
                self.publication.abort_batch(
                    project_id=project_id,
                    staging_tokens=tuple(
                        record.staging_token for record in records
                    ),
                    allow_incomplete=True,
                )
        finally:
            for locator in staging_locators:
                self.store.discard_staging(locator)

    def _remember_registered_record(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
        records: list[ArtifactRecord],
    ) -> None:
        try:
            record = self.repository.get_by_token(
                project_id=project_id,
                staging_token=staging_token,
            )
        except ArtifactUnavailable:
            return
        if all(
            item.staging_token != record.staging_token for item in records
        ):
            records.append(record)

    def publish(
        self,
        artifact: ProducedArtifact,
        /,
        *,
        request: OperationRequest,
        created_at,
    ) -> PersistentArtifactRef:
        del created_at
        attempt_number, fencing_token = self.attempt_identity(request)
        record = self.publication.publish(
            project_id=request.project_id,
            operation_run_id=request.operation_run_id,
            attempt_id=request.operation_attempt_id,
            attempt_number=attempt_number,
            fencing_token=fencing_token,
            publication_key=(
                f"{artifact.logical_role}:"
                f"{_content_digest(bytes(artifact.payload))}"
            ),
            stream=(bytes(artifact.payload),),
            mime_type=artifact.mime_type,
            logical_role=artifact.logical_role,
            retention_class=artifact.retention_class,
        )
        if request.input_artifact_refs:
            self.lineage.append(
                project_id=request.project_id,
                output_artifact_id=record.artifact_id,
                inputs=tuple(
                    LineageInput(
                        artifact_id=item.artifact_id,
                        role="input",
                        ordinal=index,
                    )
                    for index, item in enumerate(
                        request.input_artifact_refs
                    )
                ),
            )
        return record.persistent_ref()


def database_attempt_identity(
    session_factory: Callable[[], Session],
) -> AttemptIdentity:
    """Resolve the immutable scheduler Attempt facts for publication."""

    def resolve(request: OperationRequest) -> tuple[int, int]:
        with session_factory() as session:
            attempt = session.scalar(
                select(OperationAttemptRecord).where(
                    OperationAttemptRecord.id
                    == request.operation_attempt_id,
                    OperationAttemptRecord.project_id
                    == request.project_id,
                    OperationAttemptRecord.operation_run_id
                    == request.operation_run_id,
                )
            )
            if attempt is None:
                raise ArtifactLineageUnavailable(
                    "operation attempt is unavailable for publication"
                )
            return attempt.attempt_number, attempt.fencing_token

    return resolve


@dataclass(frozen=True, slots=True)
class GateSubmission:
    outcome: GateOutcome
    human_review_task_id: UUID | None = None


class DurableQualityGate:
    """Persist and decide one quality stage through T10 and T11."""

    def __init__(
        self,
        *,
        policy: GatePolicySnapshot,
        repository: QualityRepository,
        certifications,
        selection_sealer: SelectionSealer,
        selection_head_id: UUID,
        gate_key: str,
        review_sink: HumanReviewSink | None,
        created_by_actor: str,
        restored_candidates: tuple[CandidateVersion, ...] = (),
        restored_outcomes: tuple[GateOutcome, ...] = (),
        restored_human_review_task_id: UUID | None = None,
    ) -> None:
        if not gate_key.strip() or len(gate_key) > 200:
            raise ValueError("quality gate key is invalid")
        if policy.gate_key != gate_key:
            raise ValueError("quality policy does not belong to this gate")
        self.policy = policy
        self.repository = repository
        self.selection_head_id = selection_head_id
        self.gate_key = gate_key
        self.review_sink = review_sink
        self.created_by_actor = created_by_actor
        self.engine = GateEngine(
            policy=policy,
            certifications=certifications,
            selection_sealer=selection_sealer,
        )
        self.engine.restore_history(
            candidates=restored_candidates,
            outcomes=restored_outcomes,
        )
        self._sequence = len(restored_outcomes)
        self._human_review_task_id = restored_human_review_task_id
        repository.store_policy(policy)

    @property
    def candidates(self) -> tuple[CandidateVersion, ...]:
        return self.engine.candidates

    def submit(
        self,
        *,
        candidate: CandidateVersion,
        proposed_repair: RepairProposal | None = None,
    ) -> GateSubmission:
        self.repository.store_evaluation(candidate.evaluation)
        self.repository.store_candidate(candidate)
        self.engine.add_candidate(candidate)
        outcome = self.engine.decide(proposed_repair=proposed_repair)
        self._sequence += 1
        self.repository.append_gate_outcome(
            policy=self.policy,
            outcome=outcome,
            sequence=self._sequence,
        )
        if outcome.kind is GateOutcomeKind.WAITING_HUMAN:
            if self.review_sink is not None:
                task = self.review_sink.open_for_gate(
                    policy=self.policy,
                    candidates=self.engine.candidates,
                    gate_key=self.gate_key,
                    selection_head_id=self.selection_head_id,
                    expected_selection_version=(
                        outcome.expected_selection_version
                    ),
                    reason=outcome.reason,
                    created_by_actor=self.created_by_actor,
                )
                self._human_review_task_id = task.id
        return GateSubmission(
            outcome=outcome,
            human_review_task_id=self._human_review_task_id,
        )


@dataclass(frozen=True, slots=True)
class ArtifactInvalidationPlan:
    project_id: UUID
    replaced_artifact_id: UUID
    invalidated_artifact_ids: frozenset[UUID]
    carried_forward_artifact_ids: frozenset[UUID]


class LineageInvalidationPlanner:
    """Plan a new workflow revision without mutating sealed selections."""

    def __init__(self, lineage: ArtifactLineageGraph) -> None:
        self.lineage = lineage

    def replace(
        self,
        *,
        project_id: UUID,
        replaced_artifact_id: UUID,
        candidate_artifact_ids: Iterable[UUID],
    ) -> ArtifactInvalidationPlan:
        affected = {replaced_artifact_id}
        edges = self.lineage.edges(project_id=project_id)
        while True:
            expanded = {
                edge.output_artifact_id
                for edge in edges
                if edge.input_artifact_id in affected
            }
            if expanded.issubset(affected):
                break
            affected.update(expanded)
        candidates = frozenset(candidate_artifact_ids)
        return ArtifactInvalidationPlan(
            project_id=project_id,
            replaced_artifact_id=replaced_artifact_id,
            invalidated_artifact_ids=frozenset(affected),
            carried_forward_artifact_ids=candidates - affected,
        )


@dataclass(frozen=True, slots=True)
class WorkflowTrace:
    project_id: UUID
    workflow_run_id: UUID
    operation_run_ids: tuple[UUID, ...]
    operation_attempt_ids: tuple[UUID, ...]
    artifact_ids: tuple[UUID, ...]
    lineage_edge_ids: tuple[UUID, ...]
    evidence_pack_ids: tuple[UUID, ...]
    evaluation_ids: tuple[UUID, ...]
    candidate_ids: tuple[UUID, ...]
    selection_revision_ids: tuple[UUID, ...]
    human_review_task_ids: tuple[UUID, ...]


def trace_workflow(
    session: Session,
    *,
    project_id: UUID,
    workflow_run_id: UUID,
) -> WorkflowTrace:
    """Return stable IDs for every authority involved in one workflow."""

    operations = session.scalars(
        select(OperationRunRecord).where(
            OperationRunRecord.project_id == project_id,
            OperationRunRecord.workflow_run_id == workflow_run_id,
        )
    ).all()
    operation_ids = {item.id for item in operations}
    attempts = (
        session.scalars(
            select(OperationAttemptRecord).where(
                OperationAttemptRecord.project_id == project_id,
                OperationAttemptRecord.operation_run_id.in_(operation_ids),
            )
        ).all()
        if operation_ids
        else ()
    )
    artifacts = (
        session.scalars(
            select(ArtifactRecordRow).where(
                ArtifactRecordRow.project_id == project_id,
                ArtifactRecordRow.operation_run_id.in_(operation_ids),
            )
        ).all()
        if operation_ids
        else ()
    )
    artifact_ids = {item.id for item in artifacts}
    lineage = (
        session.scalars(
            select(ArtifactLineageEdgeRecord).where(
                ArtifactLineageEdgeRecord.project_id == project_id,
                ArtifactLineageEdgeRecord.output_artifact_id.in_(
                    artifact_ids
                ),
            )
        ).all()
        if artifact_ids
        else ()
    )
    evaluations = session.scalars(
        select(QCEvaluationFactRecord).where(
            QCEvaluationFactRecord.project_id == project_id,
            QCEvaluationFactRecord.workflow_run_id == workflow_run_id,
        )
    ).all()
    candidates = session.scalars(
        select(QCCandidateVersionRecord).where(
            QCCandidateVersionRecord.project_id == project_id,
            QCCandidateVersionRecord.workflow_run_id == workflow_run_id,
        )
    ).all()
    heads = session.scalars(
        select(SelectionHeadRecord.id).where(
            SelectionHeadRecord.project_id == project_id,
            SelectionHeadRecord.workflow_run_id == workflow_run_id,
        )
    ).all()
    selections = (
        session.scalars(
            select(SelectionRevisionRecord).where(
                SelectionRevisionRecord.project_id == project_id,
                SelectionRevisionRecord.selection_head_id.in_(heads),
            )
        ).all()
        if heads
        else ()
    )
    human_reviews = session.scalars(
        select(HumanReviewTaskRecord).where(
            HumanReviewTaskRecord.project_id == project_id,
            HumanReviewTaskRecord.workflow_run_id == workflow_run_id,
        )
    ).all()
    return WorkflowTrace(
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        operation_run_ids=_sorted_ids(item.id for item in operations),
        operation_attempt_ids=_sorted_ids(item.id for item in attempts),
        artifact_ids=_sorted_ids(item.id for item in artifacts),
        lineage_edge_ids=_sorted_ids(item.id for item in lineage),
        evidence_pack_ids=_sorted_ids(
            item.evidence_pack_id for item in evaluations
        ),
        evaluation_ids=_sorted_ids(item.id for item in evaluations),
        candidate_ids=_sorted_ids(item.id for item in candidates),
        selection_revision_ids=_sorted_ids(
            item.id for item in selections
        ),
        human_review_task_ids=_sorted_ids(
            item.id for item in human_reviews
        ),
    )


def _content_digest(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _sorted_ids(values: Iterable[UUID]) -> tuple[UUID, ...]:
    return tuple(sorted(values, key=str))


__all__ = [
    "ArtifactInvalidationPlan",
    "DurableQualityGate",
    "GateSubmission",
    "LineageInvalidationPlanner",
    "PublicationArtifactGateway",
    "WorkflowTrace",
    "database_attempt_identity",
    "trace_workflow",
]
