"""Persist successful H3 results from re-queried durable authorities.

This boundary runs inside the worker completion transaction.  It never trusts
the executor result alone: the operation, Attempt, and committed artifact
catalog are reloaded and matched exactly before an H3 domain repository may be
mutated.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid5

from shared_contracts import (
    CharacterReferenceSetV1,
    CharacterReferenceSourceAssetV1,
    EpisodeGenerationIRV1,
    H3AttemptQCEvidenceV1,
    H3AttemptSelectionV1,
    H3CandidateScoreV1,
    H3SequenceV1,
    H3SourceLineageV1,
    OperationRequest,
    OperationResult,
    OperationStatus,
    PersistentArtifactRef,
    ProjectCreativeIRV1,
    RetentionClass,
    SchemaRevision,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db.canonical import canonical_json_digest
from .db.models import (
    ArtifactRecordRow,
    EvidencePackRevisionRecord,
    H3SequenceRevisionRecord,
    OperationAttemptRecord,
    OperationRunRecord,
    QCGatePolicySnapshotRecord,
    QCEvaluationFactRecord,
    QCPromptRevisionRecord,
    SelectionHeadRecord,
)
from .h3_artifact_inputs import (
    H3ArtifactInputError,
    VerifiedH3ArtifactInputs,
)
from .h3_atomic_runtime import H3_OPERATION_TYPES
from .h3_repository import H3Repository
from .quality import (
    ArtifactBinding,
    EvaluatorBundle,
    EvidencePackBinding,
    GatePolicySnapshot,
    MachineJudgment,
    QCEvaluation,
    QCDefect,
    QCPromptRevision,
    QualityStage,
    RepairDisposition,
    RepairResult,
)


class H3ResultPersistenceError(RuntimeError):
    """A successful result did not match its persisted H3 authority."""


class _H3DomainRepository(Protocol):
    def store_project_creative_ir(
        self,
        project_ir: ProjectCreativeIRV1,
        *,
        command_idempotency_key: str,
    ) -> object: ...

    def store_character_source_asset(
        self,
        project_id: UUID,
        source_asset: CharacterReferenceSourceAssetV1,
        *,
        command_idempotency_key: str,
    ) -> object: ...

    def store_character_reference_set_revision(
        self,
        project_id: UUID,
        reference_set: CharacterReferenceSetV1,
        *,
        command_idempotency_key: str,
    ) -> object: ...

    def store_episode_generation_ir(
        self,
        project_id: UUID,
        episode_ir: EpisodeGenerationIRV1,
        *,
        command_idempotency_key: str,
    ) -> object: ...

    def select_h3_attempt(
        self,
        project_id: UUID,
        sequence_revision_id: UUID,
        selection: H3AttemptSelectionV1,
        *,
        command_idempotency_key: str,
        created_by_actor: str,
        expected_state_version: int = 0,
    ) -> object: ...

    def store_h3_sequence_revision(
        self,
        project_id: UUID,
        episode_revision_id: UUID,
        sequence: H3SequenceV1,
        *,
        selection_head_id: UUID,
        command_idempotency_key: str,
    ) -> object: ...

    def record_h3_runtime_attempt(
        self,
        project_id: UUID,
        sequence_revision_id: UUID,
        lineage: H3SourceLineageV1,
        *,
        operation_run_id: UUID,
        operation_attempt_id: UUID,
        artifact_id: UUID,
        prompt_digest: str,
        workflow_digest: str,
        command_idempotency_key: str,
        qc_evaluation_id: UUID,
        qc_gate_key: str,
        repair_of_attempt_id: UUID | None = None,
    ) -> object: ...


H3RepositoryFactory = Callable[[Session], _H3DomainRepository]
_COMPLETION_STATUSES = frozenset({"LEASED", "RUNNING", "MATERIALIZING"})
_H3_QC_EVALUATION_NAMESPACE = UUID(
    "7b0a2c6f-2f69-5c9e-a744-efbaabf3f401"
)
_PERSISTENCE_HANDLERS = {
    "character_reference.generate": "_finalize_character_reference_stage",
    "character_reference.qc": "_finalize_character_reference_stage",
    "character_reference.freeze": "_persist_character_reference_set",
    "episode_ir.generate": "_persist_episode_generation_ir",
    "h3.attempt.select": "_persist_h3_attempt_selection",
    "h3.sequence.execute": "_persist_h3_sequence",
    "project_ir.generate": "_persist_project_creative_ir",
}
_OUTPUT_ARTIFACT_CONTRACTS = {
    "character_reference.qc": (
        ("character.reference-qc", "application/json"),
    ),
    "character_reference.freeze": (
        ("character.reference-set", "application/json"),
    ),
    "episode_ir.generate": (
        ("h3.episode-generation-ir", "application/json"),
    ),
    "h3.attempt.select": (),
    "project_ir.generate": (
        ("h3.project-creative-ir", "application/json"),
    ),
}


def h3_qc_evaluation_id(
    project_id: UUID,
    operation_run_id: UUID,
    attempt_ordinal: int,
    /,
) -> UUID:
    """Return the stable QC fact identity required by an H3 result draft."""

    if (
        not isinstance(project_id, UUID)
        or not isinstance(operation_run_id, UUID)
        or type(attempt_ordinal) is not int
        or attempt_ordinal not in {0, 1}
    ):
        raise H3ResultPersistenceError(
            "H3 QC evaluation identity inputs are invalid"
        )
    command = f"h3-result:{operation_run_id}:qc:{attempt_ordinal}"
    return uuid5(
        _H3_QC_EVALUATION_NAMESPACE,
        f"{project_id}:{command}",
    )


def _validate_output_artifact_contract(
    result: OperationResult,
    *,
    sequence_ordinal: int | None = None,
    reference_authority: CharacterReferenceSetV1 | None = None,
) -> None:
    if result.op_type == "character_reference.generate":
        if reference_authority is None:
            raise H3ResultPersistenceError(
                "generated character reference authority is unavailable"
            )
        refs = tuple(result.output_artifact_refs)
        views = tuple(reference_authority.views)
        if len(refs) != len(views) + 1:
            raise H3ResultPersistenceError(
                "character generation artifact count does not match its views"
            )
        for ref, view in zip(refs[:-1], views, strict=True):
            if (
                ref.logical_role
                != f"character.reference.{view.view_name}"
                or ref.mime_type != "image/png"
                or ref.artifact_id != view.asset_id
                or ref.content_digest != view.image_digest
            ):
                raise H3ResultPersistenceError(
                    "character generation artifact role or view authority "
                    "does not match"
                )
        manifest = refs[-1]
        if (
            manifest.logical_role != "character.reference-generation"
            or manifest.mime_type != "application/json"
        ):
            raise H3ResultPersistenceError(
                "character generation authority artifact does not match its "
                "contract"
            )
        return
    if result.op_type == "h3.sequence.execute":
        refs = tuple(result.output_artifact_refs)
        if sequence_ordinal is None or len(refs) not in {1, 2}:
            raise H3ResultPersistenceError(
                "H3 sequence output artifact contract requires one or two videos"
            )
        for attempt_ordinal, ref in enumerate(refs):
            expected_role = (
                f"h3.sequence.{sequence_ordinal:03d}.attempt."
                f"{attempt_ordinal}.video"
            )
            if (
                ref.logical_role != expected_role
                or ref.mime_type != "video/mp4"
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence output artifact role or MIME does not match "
                    "its contract"
                )
        return

    expected = _OUTPUT_ARTIFACT_CONTRACTS.get(result.op_type)
    refs = tuple(result.output_artifact_refs)
    if expected is None or len(refs) != len(expected):
        raise H3ResultPersistenceError(
            "H3 output artifact contract has the wrong artifact count"
        )
    for ref, (expected_role, expected_mime) in zip(
        refs,
        expected,
        strict=True,
    ):
        if (
            ref.logical_role != expected_role
            or ref.mime_type != expected_mime
        ):
            raise H3ResultPersistenceError(
                "H3 output artifact role or MIME does not match its contract"
            )


def _db_created_at(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise H3ResultPersistenceError(
            "persisted artifact created_at is invalid"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _validate_artifact_authority(
    rows: tuple[object, ...],
    result: OperationResult,
) -> None:
    refs = tuple(result.output_artifact_refs)
    refs_by_id = {ref.artifact_id: ref for ref in refs}
    row_ids = tuple(getattr(row, "id", None) for row in rows)
    if (
        len(refs_by_id) != len(refs)
        or len(set(row_ids)) != len(row_ids)
        or len(rows) != len(refs)
        or set(row_ids) != set(refs_by_id)
    ):
        raise H3ResultPersistenceError(
            "result artifact collection does not match persisted authority"
        )

    for row in rows:
        ref = refs_by_id[row.id]
        try:
            retention_class = RetentionClass(row.retention_class)
            created_at = _db_created_at(row.created_at)
        except (AttributeError, TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "persisted artifact metadata is invalid"
            ) from exc
        if (
            row.status != "COMMITTED"
            or row.project_id != result.project_id
            or row.operation_run_id != result.operation_run_id
            or row.operation_attempt_id != result.operation_attempt_id
            or ref.project_id != row.project_id
            or ref.produced_by_operation_run_id != row.operation_run_id
            or ref.produced_by_operation_attempt_id
            != row.operation_attempt_id
            or ref.content_digest != row.content_digest
            or ref.mime_type != row.mime_type
            or ref.byte_size != row.byte_size
            or ref.logical_role != row.logical_role
            or ref.storage_uri != row.storage_uri
            or ref.retention_class is not retention_class
            or ref.created_at != created_at
        ):
            raise H3ResultPersistenceError(
                "result artifact does not match persisted authority"
            )


@dataclass(frozen=True, slots=True)
class _SequenceAttemptAuthority:
    lineage: H3SourceLineageV1
    artifact: PersistentArtifactRef
    qc_evidence: H3AttemptQCEvidenceV1
    qc_gate_key: str
    candidate: H3CandidateScoreV1


@dataclass(frozen=True, slots=True)
class _PreparedSequenceQC:
    evidence: H3AttemptQCEvidenceV1
    row: QCEvaluationFactRecord
    already_persisted: bool


@dataclass(frozen=True, slots=True)
class H3SuccessfulResultFinalizer:
    """Validate and persist one successful H3 operation result.

    The handler table is the exhaustive operation boundary.  Unknown or
    unbound H3 results fail closed rather than advancing without durable
    authority.
    """

    artifact_gateway: object
    h3_repository_factory: H3RepositoryFactory = H3Repository

    def __post_init__(self) -> None:
        try:
            reader = getattr(self.artifact_gateway, "read_bytes")
        except Exception:
            reader = None
        if not callable(reader):
            raise H3ResultPersistenceError(
                "H3 artifact gateway must provide read_bytes"
            )
        if not callable(self.h3_repository_factory):
            raise TypeError("h3_repository_factory must be callable")

    def __call__(
        self,
        session: Session,
        result: OperationResult,
        /,
    ) -> None:
        if not isinstance(result, OperationResult):
            raise H3ResultPersistenceError(
                "H3 finalizer requires OperationResult"
            )
        if (
            result.status is not OperationStatus.SUCCEEDED
            or result.op_type not in H3_OPERATION_TYPES
        ):
            return

        handler_name = _PERSISTENCE_HANDLERS.get(result.op_type)
        if handler_name is None:
            raise H3ResultPersistenceError(
                f"H3 result persistence is not implemented for {result.op_type}"
            )
        sequence_authority = None
        sequence_qc_evidences: tuple[H3AttemptQCEvidenceV1, ...] = ()
        reference_stage_authority = None
        if result.op_type == "h3.sequence.execute":
            (
                sequence_authority,
                sequence_qc_evidences,
            ) = self._h3_sequence_authority(result)
        elif result.op_type == "character_reference.generate":
            reference_stage_authority = (
                self._character_reference_stage_authority(
                    result,
                    expected_state="generating",
                )
            )
        elif result.op_type == "character_reference.qc":
            reference_stage_authority = (
                self._character_reference_stage_authority(
                    result,
                    expected_state="qc_pending",
                )
            )
        _validate_output_artifact_contract(
            result,
            sequence_ordinal=(
                sequence_authority.plan.ordinal
                if sequence_authority is not None
                else None
            ),
            reference_authority=reference_stage_authority,
        )

        operation = session.get(OperationRunRecord, result.operation_run_id)
        attempt = session.get(
            OperationAttemptRecord,
            result.operation_attempt_id,
        )
        if operation is None:
            raise H3ResultPersistenceError(
                "H3 operation authority is unavailable"
            )
        if attempt is None:
            raise H3ResultPersistenceError(
                "H3 operation attempt authority is unavailable"
            )

        request = self._validated_attempt_request(attempt)

        self._validate_invocation_authority(
            operation=operation,
            attempt=attempt,
            request=request,
            result=result,
        )
        self._validate_operation_template(
            operation=operation,
            request=request,
        )
        selection_ordinal = None
        if result.op_type == "h3.attempt.select":
            selection_ordinal = self._selection_request_ordinal(
                operation=operation,
                request=request,
            )
        sequence_ordinal = None
        if result.op_type == "h3.sequence.execute":
            if sequence_authority is None:
                raise H3ResultPersistenceError(
                    "H3 generated sequence authority is unavailable"
                )
            sequence_ordinal = self._sequence_request_ordinal(
                operation=operation,
                request=request,
                sequence=sequence_authority,
            )

        artifact_rows = tuple(
            session.scalars(
                select(ArtifactRecordRow)
                .where(
                    ArtifactRecordRow.project_id == result.project_id,
                    ArtifactRecordRow.operation_run_id
                    == result.operation_run_id,
                    ArtifactRecordRow.operation_attempt_id
                    == result.operation_attempt_id,
                )
                .order_by(ArtifactRecordRow.id)
            ).all()
        )
        _validate_artifact_authority(artifact_rows, result)

        if result.op_type in {
            "character_reference.generate",
            "character_reference.qc",
        }:
            if reference_stage_authority is None:
                raise H3ResultPersistenceError(
                    "character reference stage authority is unavailable"
                )
            self._validate_persisted_character_reference_inputs(
                session=session,
                request=request,
            )
            artifact_authority = (
                self._character_reference_stage_artifact_authority(result)
            )
            if reference_stage_authority != artifact_authority:
                raise H3ResultPersistenceError(
                    "character reference stage artifact authority does not "
                    "match structured output"
                )
            self._validate_character_reference_inputs(
                request=request,
                authority=reference_stage_authority,
            )
            handler = getattr(self, handler_name)
            handler(
                authority=reference_stage_authority,
                result=result,
                stage=result.op_type,
            )
            return

        if result.op_type == "h3.sequence.execute":
            if sequence_authority is None or sequence_ordinal is None:
                raise H3ResultPersistenceError(
                    "H3 generated sequence authority is unavailable"
                )
            episode = self._sequence_episode_authority(
                session=session,
                request=request,
                sequence=sequence_authority,
            )
            head = self._sequence_selection_head_authority(
                session=session,
                request=request,
                sequence_ordinal=sequence_ordinal,
            )
            attempts = self._sequence_attempt_authorities(
                request=request,
                result=result,
                sequence=sequence_authority,
                qc_evidences=sequence_qc_evidences,
                sequence_ordinal=sequence_ordinal,
            )
            prepared_qc = self._prepare_sequence_qc_authorities(
                session=session,
                request=request,
                result=result,
                expected_selection_version=head.state_version,
                attempts=attempts,
            )
            self._persist_prepared_sequence_qc(
                session=session,
                prepared=prepared_qc,
            )
            repository = self.h3_repository_factory(session)
            handler = getattr(self, handler_name)
            handler(
                repository=repository,
                authority=sequence_authority,
                result=result,
                episode_revision_id=episode.episode_revision_id,
                selection_head_id=head.id,
                qc_evaluation_ids=tuple(
                    item.evidence.evaluation_id for item in prepared_qc
                ),
                attempts=attempts,
            )
            return
        if result.op_type == "h3.attempt.select":
            if selection_ordinal is None:
                raise H3ResultPersistenceError(
                    "H3 selection sequence ordinal is unavailable"
                )
            selection = self._h3_attempt_selection_authority(result)
            head, sequence = self._selection_storage_authority(
                session=session,
                request=request,
                selection=selection,
                sequence_ordinal=selection_ordinal,
            )
            repository = self.h3_repository_factory(session)
            handler = getattr(self, handler_name)
            handler(
                repository=repository,
                authority=selection,
                result=result,
                sequence_revision_id=sequence.id,
                expected_state_version=head.state_version,
            )
            return
        if result.op_type == "character_reference.freeze":
            projected_authority = self._character_reference_set_authority(
                result
            )
            artifact_authority = (
                self._character_reference_set_artifact_authority(result)
            )
        elif result.op_type == "episode_ir.generate":
            projected_authority = self._episode_generation_ir_authority(
                result
            )
            artifact_authority = (
                self._episode_generation_ir_artifact_authority(result)
            )
        else:
            projected_authority = self._project_creative_ir_authority(result)
            artifact_authority = self._project_creative_ir_artifact_authority(
                result
            )
        if projected_authority != artifact_authority:
            raise H3ResultPersistenceError(
                "H3 artifact authority does not match structured output"
            )
        if result.op_type == "character_reference.freeze":
            self._validate_persisted_character_reference_inputs(
                session=session,
                request=request,
            )
            self._validate_character_reference_freeze_inputs(
                request=request,
                frozen_authority=artifact_authority,
            )

        repository = self.h3_repository_factory(session)
        handler = getattr(self, handler_name)
        handler(
            repository=repository,
            authority=artifact_authority,
            result=result,
        )

    @staticmethod
    def _selection_request_ordinal(
        *,
        operation: object,
        request: OperationRequest,
    ) -> int:
        sequence_ordinal = request.structured_inputs.get("sequence_ordinal")
        if type(sequence_ordinal) is not int or sequence_ordinal <= 0:
            raise H3ResultPersistenceError(
                "H3 selection sequence ordinal must be a positive integer"
            )
        expected_node_key = f"sequence.{sequence_ordinal:03d}.select"
        if getattr(operation, "node_key", None) != expected_node_key:
            raise H3ResultPersistenceError(
                "H3 selection node does not match its sequence ordinal"
            )
        return sequence_ordinal

    @staticmethod
    def _sequence_request_ordinal(
        *,
        operation: object,
        request: OperationRequest,
        sequence: H3SequenceV1,
    ) -> int:
        sequence_ordinal = request.structured_inputs.get("sequence_ordinal")
        if type(sequence_ordinal) is not int or sequence_ordinal <= 0:
            raise H3ResultPersistenceError(
                "H3 execution sequence ordinal must be a positive integer"
            )
        expected_node_key = f"sequence.{sequence_ordinal:03d}.execute"
        if getattr(operation, "node_key", None) != expected_node_key:
            raise H3ResultPersistenceError(
                "H3 execution node does not match its sequence ordinal"
            )
        if sequence.plan.ordinal != sequence_ordinal:
            raise H3ResultPersistenceError(
                "H3 sequence plan ordinal does not match its request"
            )
        return sequence_ordinal

    @staticmethod
    def _validated_attempt_request(attempt: object) -> OperationRequest:
        payload = getattr(attempt, "request_payload", None)
        stored_digest = getattr(attempt, "request_digest", None)
        if not isinstance(payload, Mapping) or not isinstance(
            stored_digest, str
        ):
            raise H3ResultPersistenceError(
                "H3 attempt request digest authority is invalid"
            )
        try:
            raw_payload = dict(payload)
            raw_digest = canonical_json_digest(raw_payload)
        except (TypeError, ValueError, OverflowError) as exc:
            raise H3ResultPersistenceError(
                "H3 attempt request digest cannot be verified"
            ) from exc
        if not hmac.compare_digest(stored_digest, raw_digest):
            raise H3ResultPersistenceError(
                "H3 attempt request digest does not match its payload"
            )
        try:
            request = OperationRequest.model_validate(raw_payload)
        except (TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "H3 attempt request payload is invalid"
            ) from exc
        normalized_digest = canonical_json_digest(
            request.model_dump(mode="json")
        )
        if not hmac.compare_digest(stored_digest, normalized_digest):
            raise H3ResultPersistenceError(
                "H3 attempt request digest changed after validation"
            )
        return request

    @staticmethod
    def _validate_invocation_authority(
        *,
        operation: object,
        attempt: object,
        request: OperationRequest,
        result: OperationResult,
    ) -> None:
        if (
            operation.project_id != result.project_id
            or attempt.project_id != result.project_id
            or request.project_id != result.project_id
        ):
            raise H3ResultPersistenceError(
                "H3 result project authority does not match"
            )
        if (
            operation.workflow_run_id != request.workflow_run_id
            or operation.id != result.operation_run_id
            or attempt.operation_run_id != result.operation_run_id
            or request.operation_run_id != result.operation_run_id
        ):
            raise H3ResultPersistenceError(
                "H3 result workflow or operation authority does not match"
            )
        if (
            attempt.id != result.operation_attempt_id
            or request.operation_attempt_id != result.operation_attempt_id
        ):
            raise H3ResultPersistenceError(
                "H3 result attempt authority does not match"
            )
        if (
            operation.op_type != result.op_type
            or request.op_type != result.op_type
        ):
            raise H3ResultPersistenceError(
                "H3 result operation type does not match"
            )
        expected_db_version = (
            f"{request.op_version.major}.{request.op_version.minor}"
        )
        if (
            result.op_version != request.op_version
            or operation.op_version != expected_db_version
        ):
            raise H3ResultPersistenceError(
                "H3 result operation version does not match"
            )
        if (
            operation.command_idempotency_key
            != request.command_idempotency_key
        ):
            raise H3ResultPersistenceError(
                "H3 operation command idempotency authority does not match"
            )
        if (
            operation.parent_operation_run_id
            != request.parent_operation_run_id
        ):
            raise H3ResultPersistenceError(
                "H3 operation parent authority does not match"
            )
        if (
            attempt.implementation_digest != request.implementation_digest
            or result.implementation_digest
            != request.implementation_digest
        ):
            raise H3ResultPersistenceError(
                "H3 result implementation digest does not match"
            )
        if (
            result.output_schema_version
            != request.required_output_schema_version
        ):
            raise H3ResultPersistenceError(
                "H3 result output schema does not match"
            )
        if operation.status not in _COMPLETION_STATUSES:
            raise H3ResultPersistenceError(
                "H3 operation status is outside completion authority"
            )
        if (
            type(attempt.attempt_number) is not int
            or attempt.attempt_number <= 0
        ):
            raise H3ResultPersistenceError(
                "H3 operation attempt number is invalid"
            )

        accepted_attempt_id = operation.accepted_attempt_id
        accepted_attempt_number = operation.accepted_attempt_number
        if accepted_attempt_id is None:
            if accepted_attempt_number is not None:
                raise H3ResultPersistenceError(
                    "H3 accepted attempt authority is incomplete"
                )
        elif (
            accepted_attempt_id != attempt.id
            or accepted_attempt_number != attempt.attempt_number
        ):
            raise H3ResultPersistenceError(
                "H3 accepted attempt does not match this result"
            )

    @staticmethod
    def _validate_operation_template(
        *,
        operation: object,
        request: OperationRequest,
    ) -> None:
        template = getattr(operation, "request_payload", None)
        if not isinstance(template, Mapping):
            raise H3ResultPersistenceError(
                "H3 operation request template is invalid"
            )
        stored_template_digest = getattr(
            operation,
            "operation_input_digest",
            None,
        )
        try:
            template_digest = canonical_json_digest(dict(template))
        except (TypeError, ValueError, OverflowError) as exc:
            raise H3ResultPersistenceError(
                "H3 operation template digest cannot be verified"
            ) from exc
        try:
            template_op_version = SchemaRevision.model_validate(
                template.get("op_version")
            )
        except (TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "H3 operation template version is invalid"
            ) from exc
        if template_op_version != request.op_version:
            raise H3ResultPersistenceError(
                "H3 operation template version does not match"
            )
        if (
            template.get("operation_spec_digest")
            != request.operation_spec_digest
        ):
            raise H3ResultPersistenceError(
                "H3 operation template spec digest does not match"
            )
        if (
            template.get("implementation_digest")
            != request.implementation_digest
        ):
            raise H3ResultPersistenceError(
                "H3 operation template implementation digest does not match"
            )
        try:
            input_schema = SchemaRevision.model_validate(
                template.get("input_schema_version")
            )
            output_schema = SchemaRevision.model_validate(
                template.get("output_schema_version")
            )
        except (TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "H3 operation template schema authority is invalid"
            ) from exc
        if (
            input_schema != request.input_schema_version
            or output_schema != request.required_output_schema_version
        ):
            raise H3ResultPersistenceError(
                "H3 operation template schema does not match"
            )

        binding = template.get("operation_request_binding")
        if not isinstance(binding, Mapping):
            raise H3ResultPersistenceError(
                "H3 operation template node binding is invalid"
            )
        raw_node_run_id = binding.get("node_run_id")
        if raw_node_run_id is None:
            raise H3ResultPersistenceError(
                "H3 operation template node identity is required"
            )
        try:
            node_run_id = UUID(str(raw_node_run_id))
        except (TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "H3 operation template node identity is invalid"
            ) from exc
        if node_run_id != request.node_run_id:
            raise H3ResultPersistenceError(
                "H3 operation template node identity does not match"
            )
        if (
            not isinstance(stored_template_digest, str)
            or not hmac.compare_digest(
                stored_template_digest,
                template_digest,
            )
        ):
            raise H3ResultPersistenceError(
                "H3 operation template digest does not match its payload"
            )

    @staticmethod
    def _project_creative_ir_authority(
        result: OperationResult,
    ) -> ProjectCreativeIRV1:
        structured_output = dict(result.structured_output)
        if set(structured_output) != {"project_creative_ir"}:
            raise H3ResultPersistenceError(
                "H3 project structured output must contain only "
                "project_creative_ir"
            )
        try:
            authority = ProjectCreativeIRV1.model_validate(
                structured_output["project_creative_ir"]
            )
        except (TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "H3 project structured output is invalid"
            ) from exc
        if authority.project_id != result.project_id:
            raise H3ResultPersistenceError(
                "H3 project structured output belongs to another project"
            )
        return authority

    def _project_creative_ir_artifact_authority(
        self,
        result: OperationResult,
    ) -> ProjectCreativeIRV1:
        try:
            verified = VerifiedH3ArtifactInputs(
                project_id=result.project_id,
                artifact_refs=result.output_artifact_refs,
                gateway=self.artifact_gateway,
            )
            authority = verified.read_json_model(
                "h3.project-creative-ir",
                ProjectCreativeIRV1,
            )
        except H3ArtifactInputError as exc:
            raise H3ResultPersistenceError(
                "H3 project artifact authority is invalid"
            ) from exc
        if authority.project_id != result.project_id:
            raise H3ResultPersistenceError(
                "H3 project artifact authority belongs to another project"
            )
        return authority

    @staticmethod
    def _character_reference_stage_authority(
        result: OperationResult,
        *,
        expected_state: str,
    ) -> CharacterReferenceSetV1:
        structured_output = dict(result.structured_output)
        if set(structured_output) != {"reference_set"}:
            raise H3ResultPersistenceError(
                "H3 character reference structured output must contain "
                "only reference_set"
            )
        raw = structured_output["reference_set"]
        if not isinstance(raw, Mapping):
            raise H3ResultPersistenceError(
                "H3 character reference structured authority is invalid"
            )
        try:
            authority = CharacterReferenceSetV1.model_validate(raw)
            raw_digest = canonical_json_digest(dict(raw))
            normalized_digest = canonical_json_digest(
                authority.model_dump(mode="json")
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise H3ResultPersistenceError(
                "H3 character reference structured authority is invalid"
            ) from exc
        if not hmac.compare_digest(raw_digest, normalized_digest):
            raise H3ResultPersistenceError(
                "H3 character reference authority changed after validation"
            )
        if authority.state != expected_state:
            raise H3ResultPersistenceError(
                "H3 character reference state does not match its operation"
            )
        if len(authority.views) != 3:
            raise H3ResultPersistenceError(
                "H3 character reference stage requires three canonical views"
            )
        if expected_state == "generating":
            if (
                authority.cross_view_qc is not None
                or any(view.single_view_qc_passed for view in authority.views)
            ):
                raise H3ResultPersistenceError(
                    "generated character reference authority cannot claim QC"
                )
        elif (
            authority.cross_view_qc is None
            or not authority.cross_view_qc.all_gates_passed()
            or not all(
                view.single_view_qc_passed for view in authority.views
            )
        ):
            raise H3ResultPersistenceError(
                "character reference QC authority did not pass every gate"
            )
        return authority

    @staticmethod
    def _validate_persisted_artifact_refs(
        *,
        session: Session,
        project_id: UUID,
        artifact_refs: tuple[object, ...],
        label: str,
    ) -> tuple[PersistentArtifactRef, ...]:
        persisted: list[PersistentArtifactRef] = []
        for ref in artifact_refs:
            ref_id = getattr(ref, "artifact_id", None)
            if not isinstance(ref_id, UUID):
                raise H3ResultPersistenceError(
                    f"{label} input artifact identity is invalid"
                )
            row = session.get(ArtifactRecordRow, ref_id)
            if row is None:
                raise H3ResultPersistenceError(
                    f"{label} input artifact authority is unavailable"
                )
            if (
                getattr(row, "id", None) != ref_id
                or getattr(row, "status", None) != "COMMITTED"
                or getattr(row, "project_id", None) != project_id
                or getattr(row, "content_digest", None)
                != getattr(ref, "content_digest", None)
                or getattr(row, "mime_type", None)
                != getattr(ref, "mime_type", None)
                or getattr(row, "byte_size", None)
                != getattr(ref, "byte_size", None)
                or getattr(row, "logical_role", None)
                != getattr(ref, "logical_role", None)
            ):
                raise H3ResultPersistenceError(
                    f"{label} input artifact does not match persisted authority"
                )
            try:
                durable = PersistentArtifactRef(
                    artifact_id=row.id,
                    project_id=row.project_id,
                    content_digest=row.content_digest,
                    mime_type=row.mime_type,
                    byte_size=row.byte_size,
                    logical_role=row.logical_role,
                    storage_uri=row.storage_uri,
                    produced_by_operation_run_id=row.operation_run_id,
                    produced_by_operation_attempt_id=row.operation_attempt_id,
                    created_at=_db_created_at(row.created_at),
                    retention_class=row.retention_class,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise H3ResultPersistenceError(
                    f"persisted {label} input artifact authority is invalid"
                ) from exc
            persisted.append(durable)
        return tuple(persisted)

    @classmethod
    def _validate_persisted_character_reference_inputs(
        cls,
        *,
        session: Session,
        request: OperationRequest,
    ) -> None:
        cls._validate_persisted_artifact_refs(
            session=session,
            project_id=request.project_id,
            artifact_refs=tuple(request.input_artifact_refs),
            label="character reference",
        )

    def _character_reference_stage_artifact_authority(
        self,
        result: OperationResult,
    ) -> CharacterReferenceSetV1:
        role = {
            "character_reference.generate": "character.reference-generation",
            "character_reference.qc": "character.reference-qc",
        }.get(result.op_type)
        if role is None:
            raise H3ResultPersistenceError(
                "character reference artifact reader received wrong operation"
            )
        return self._read_character_reference_authority(
            project_id=result.project_id,
            artifact_refs=result.output_artifact_refs,
            role=role,
        )

    def _read_character_reference_authority(
        self,
        *,
        project_id: UUID,
        artifact_refs: tuple[object, ...],
        role: str,
    ) -> CharacterReferenceSetV1:
        try:
            verified = VerifiedH3ArtifactInputs(
                project_id=project_id,
                artifact_refs=artifact_refs,
                gateway=self.artifact_gateway,
            )
            authority = verified.read_json_model(
                role,
                CharacterReferenceSetV1,
            )
            raw = json.loads(
                verified.read_bytes(
                    role,
                    allowed_mime_types=frozenset({"application/json"}),
                ).decode("utf-8", errors="strict")
            )
        except (
            H3ArtifactInputError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise H3ResultPersistenceError(
                "character reference stage artifact authority is invalid"
            ) from exc
        if (
            not isinstance(raw, dict)
            or canonical_json_digest(raw)
            != canonical_json_digest(authority.model_dump(mode="json"))
        ):
            raise H3ResultPersistenceError(
                "character reference stage artifact authority changed after "
                "validation"
            )
        return authority

    def _validate_character_reference_inputs(
        self,
        *,
        request: OperationRequest,
        authority: CharacterReferenceSetV1,
    ) -> None:
        refs = tuple(request.input_artifact_refs)
        if request.op_type == "character_reference.generate":
            source_refs = tuple(
                ref
                for ref in refs
                if ref.logical_role == "character.source.image"
            )
            project_refs = tuple(
                ref
                for ref in refs
                if ref.logical_role == "h3.project-creative-ir"
            )
            if (
                len(refs) != 2
                or len(source_refs) != 1
                or len(project_refs) != 1
                or source_refs[0].artifact_id
                != authority.source_asset.asset_id
                or source_refs[0].content_digest
                != authority.source_asset.content_digest
                or source_refs[0].mime_type
                not in {"image/png", "image/jpeg", "image/webp"}
                or project_refs[0].mime_type != "application/json"
            ):
                raise H3ResultPersistenceError(
                    "character generation input source authority does not match"
                )
            return
        if request.op_type != "character_reference.qc":
            raise H3ResultPersistenceError(
                "character reference input validator received wrong operation"
            )
        if len(refs) != len(authority.views) + 1:
            raise H3ResultPersistenceError(
                "character QC input artifact count does not match its views"
            )
        for ref, view in zip(refs[:-1], authority.views, strict=True):
            if (
                ref.logical_role
                != f"character.reference.{view.view_name}"
                or ref.mime_type != "image/png"
                or ref.artifact_id != view.asset_id
                or ref.content_digest != view.image_digest
            ):
                raise H3ResultPersistenceError(
                    "character QC input artifact does not match its view authority"
                )
        generation_ref = refs[-1]
        if (
            generation_ref.logical_role
            != "character.reference-generation"
            or generation_ref.mime_type != "application/json"
        ):
            raise H3ResultPersistenceError(
                "character QC generation authority input is invalid"
            )
        try:
            generated = self._read_character_reference_authority(
                project_id=request.project_id,
                artifact_refs=refs,
                role="character.reference-generation",
            )
        except H3ResultPersistenceError as exc:
            raise H3ResultPersistenceError(
                "character QC generation authority input is invalid"
            ) from exc
        if generated.state != "generating":
            raise H3ResultPersistenceError(
                "character QC generation authority is not canonical"
            )
        self._validate_character_reference_qc_transition(
            generated=generated,
            qc_authority=authority,
        )

    @staticmethod
    def _validate_character_reference_qc_transition(
        *,
        generated: CharacterReferenceSetV1,
        qc_authority: CharacterReferenceSetV1,
    ) -> None:
        if (
            generated.reference_set_revision_id
            == qc_authority.reference_set_revision_id
        ):
            raise H3ResultPersistenceError(
                "character QC must publish a distinct authority revision"
            )
        generated_identity = generated.model_dump(
            mode="json",
            exclude={
                "reference_set_revision_id",
                "views",
                "cross_view_qc",
                "state",
                "reference_set_digest",
            },
        )
        qc_identity = qc_authority.model_dump(
            mode="json",
            exclude={
                "reference_set_revision_id",
                "views",
                "cross_view_qc",
                "state",
                "reference_set_digest",
            },
        )
        if generated_identity != qc_identity:
            raise H3ResultPersistenceError(
                "character QC authority rebound its generated identity"
            )
        if len(generated.views) != len(qc_authority.views):
            raise H3ResultPersistenceError(
                "character QC authority rebound its generated views"
            )
        for generated_view, qc_view in zip(
            generated.views,
            qc_authority.views,
            strict=True,
        ):
            if generated_view.model_dump(
                mode="json",
                exclude={"single_view_qc_passed"},
            ) != qc_view.model_dump(
                mode="json",
                exclude={"single_view_qc_passed"},
            ):
                raise H3ResultPersistenceError(
                    "character QC authority rebound a generated view"
                )

    def _validate_character_reference_freeze_inputs(
        self,
        *,
        request: OperationRequest,
        frozen_authority: CharacterReferenceSetV1,
    ) -> None:
        if request.op_type != "character_reference.freeze":
            raise H3ResultPersistenceError(
                "character freeze input validator received wrong operation"
            )
        refs = tuple(request.input_artifact_refs)
        expected_roles = (
            "character.reference.front",
            "character.reference.three_quarter_left",
            "character.reference.profile_left",
            "character.reference-generation",
            "character.reference-qc",
        )
        if (
            len(refs) != len(expected_roles)
            or tuple(ref.logical_role for ref in refs) != expected_roles
        ):
            raise H3ResultPersistenceError(
                "character freeze input artifact contract is invalid"
            )
        for ref, view in zip(
            refs[:3],
            frozen_authority.views,
            strict=True,
        ):
            if (
                ref.mime_type != "image/png"
                or ref.artifact_id != view.asset_id
                or ref.content_digest != view.image_digest
            ):
                raise H3ResultPersistenceError(
                    "character freeze input artifact rebound a reference view"
                )
        if any(ref.mime_type != "application/json" for ref in refs[3:]):
            raise H3ResultPersistenceError(
                "character freeze authority artifact MIME is invalid"
            )
        generated = self._read_character_reference_authority(
            project_id=request.project_id,
            artifact_refs=refs,
            role="character.reference-generation",
        )
        qc_authority = self._read_character_reference_authority(
            project_id=request.project_id,
            artifact_refs=refs,
            role="character.reference-qc",
        )
        if generated.state != "generating" or qc_authority.state != "qc_pending":
            raise H3ResultPersistenceError(
                "character freeze authority chain has an invalid state"
            )
        self._validate_character_reference_qc_transition(
            generated=generated,
            qc_authority=qc_authority,
        )
        if (
            qc_authority.reference_set_revision_id
            == frozen_authority.reference_set_revision_id
        ):
            raise H3ResultPersistenceError(
                "character freeze must publish a distinct authority revision"
            )
        qc_identity = qc_authority.model_dump(
            mode="json",
            exclude={
                "reference_set_revision_id",
                "state",
                "reference_set_digest",
            },
        )
        frozen_identity = frozen_authority.model_dump(
            mode="json",
            exclude={
                "reference_set_revision_id",
                "state",
                "reference_set_digest",
            },
        )
        if qc_identity != frozen_identity:
            raise H3ResultPersistenceError(
                "character freeze authority rebound its QC authority"
            )

    @staticmethod
    def _character_reference_set_authority(
        result: OperationResult,
    ) -> CharacterReferenceSetV1:
        structured_output = dict(result.structured_output)
        if set(structured_output) != {"reference_set"}:
            raise H3ResultPersistenceError(
                "H3 character structured output must contain only reference_set"
            )
        try:
            authority = CharacterReferenceSetV1.model_validate(
                structured_output["reference_set"]
            )
        except (TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "H3 character reference structured output is invalid"
            ) from exc
        if authority.state != "frozen":
            raise H3ResultPersistenceError(
                "H3 character reference authority must be frozen"
            )
        return authority

    def _character_reference_set_artifact_authority(
        self,
        result: OperationResult,
    ) -> CharacterReferenceSetV1:
        authority = self._read_character_reference_authority(
            project_id=result.project_id,
            artifact_refs=result.output_artifact_refs,
            role="character.reference-set",
        )
        if authority.state != "frozen":
            raise H3ResultPersistenceError(
                "H3 character reference artifact authority must be frozen"
            )
        return authority

    @staticmethod
    def _episode_generation_ir_authority(
        result: OperationResult,
    ) -> EpisodeGenerationIRV1:
        structured_output = dict(result.structured_output)
        if set(structured_output) != {"episode_generation_ir"}:
            raise H3ResultPersistenceError(
                "H3 episode structured output must contain only "
                "episode_generation_ir"
            )
        try:
            authority = EpisodeGenerationIRV1.model_validate(
                structured_output["episode_generation_ir"]
            )
        except (TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "H3 episode structured output is invalid"
            ) from exc
        if authority.project_ir.project_id != result.project_id:
            raise H3ResultPersistenceError(
                "H3 episode structured output belongs to another project"
            )
        return authority

    def _episode_generation_ir_artifact_authority(
        self,
        result: OperationResult,
    ) -> EpisodeGenerationIRV1:
        try:
            verified = VerifiedH3ArtifactInputs(
                project_id=result.project_id,
                artifact_refs=result.output_artifact_refs,
                gateway=self.artifact_gateway,
            )
            authority = verified.read_json_model(
                "h3.episode-generation-ir",
                EpisodeGenerationIRV1,
            )
        except H3ArtifactInputError as exc:
            raise H3ResultPersistenceError(
                "H3 episode artifact authority is invalid"
            ) from exc
        if authority.project_ir.project_id != result.project_id:
            raise H3ResultPersistenceError(
                "H3 episode artifact authority belongs to another project"
            )
        return authority

    @staticmethod
    def _h3_sequence_authority(
        result: OperationResult,
    ) -> tuple[H3SequenceV1, tuple[H3AttemptQCEvidenceV1, ...]]:
        structured_output = dict(result.structured_output)
        if set(structured_output) != {"sequence", "qc_evaluations"}:
            raise H3ResultPersistenceError(
                "H3 sequence structured output must contain exactly sequence "
                "and QC evaluations"
            )
        raw_sequence = structured_output["sequence"]
        if not isinstance(raw_sequence, Mapping):
            raise H3ResultPersistenceError(
                "H3 sequence structured output is invalid"
            )
        try:
            authority = H3SequenceV1.model_validate(
                raw_sequence
            )
            if canonical_json_digest(dict(raw_sequence)) != (
                canonical_json_digest(authority.model_dump(mode="json"))
            ):
                raise ValueError("sequence changed after validation")
        except (TypeError, ValueError, OverflowError) as exc:
            raise H3ResultPersistenceError(
                "H3 sequence structured output is invalid"
            ) from exc
        if authority.state != "generated" or authority.selection is not None:
            raise H3ResultPersistenceError(
                "H3 sequence result must be generated and unselected"
            )
        raw_evidences = structured_output["qc_evaluations"]
        if not isinstance(raw_evidences, list):
            raise H3ResultPersistenceError(
                "H3 sequence QC evaluations must be a JSON array"
            )
        evidences: list[H3AttemptQCEvidenceV1] = []
        try:
            for raw in raw_evidences:
                if not isinstance(raw, Mapping):
                    raise TypeError("QC evidence must be an object")
                evidence = H3AttemptQCEvidenceV1.model_validate(raw)
                if canonical_json_digest(dict(raw)) != canonical_json_digest(
                    evidence.model_dump(mode="json")
                ):
                    raise ValueError("QC evidence changed after validation")
                evidences.append(evidence)
        except (TypeError, ValueError, OverflowError) as exc:
            raise H3ResultPersistenceError(
                "H3 sequence QC evidence is invalid"
            ) from exc
        return authority, tuple(evidences)

    def _sequence_episode_authority(
        self,
        *,
        session: Session,
        request: OperationRequest,
        sequence: H3SequenceV1,
    ) -> EpisodeGenerationIRV1:
        refs = tuple(request.input_artifact_refs)
        persisted_refs = self._validate_persisted_artifact_refs(
            session=session,
            project_id=request.project_id,
            artifact_refs=refs,
            label="H3 sequence",
        )
        try:
            verified = VerifiedH3ArtifactInputs(
                project_id=request.project_id,
                artifact_refs=persisted_refs,
                gateway=self.artifact_gateway,
            )
            episode_refs = tuple(
                ref
                for ref in persisted_refs
                if ref.logical_role == "h3.episode-generation-ir"
            )
            if (
                len(episode_refs) != 1
                or episode_refs[0].mime_type != "application/json"
            ):
                raise H3ArtifactInputError(
                    "episode input artifact contract is invalid"
                )
            episode = verified.read_json_model(
                "h3.episode-generation-ir",
                EpisodeGenerationIRV1,
            )
        except H3ArtifactInputError as exc:
            raise H3ResultPersistenceError(
                "H3 sequence episode artifact authority is invalid"
            ) from exc
        if episode.project_ir.project_id != request.project_id:
            raise H3ResultPersistenceError(
                "H3 sequence episode authority belongs to another project"
            )
        declared_plans = tuple(
            plan
            for plan in episode.sequence_plans
            if plan.sequence_id == sequence.plan.sequence_id
        )
        if len(declared_plans) != 1 or declared_plans[0] != sequence.plan:
            raise H3ResultPersistenceError(
                "H3 sequence plan does not match the frozen episode authority"
            )
        return episode

    @staticmethod
    def _sequence_selection_head_authority(
        *,
        session: Session,
        request: OperationRequest,
        sequence_ordinal: int,
    ) -> SelectionHeadRecord:
        selection_key = f"h3.sequence.{sequence_ordinal:03d}"
        head = session.scalar(
            select(SelectionHeadRecord).where(
                SelectionHeadRecord.project_id == request.project_id,
                SelectionHeadRecord.workflow_run_id
                == request.workflow_run_id,
                SelectionHeadRecord.selection_key == selection_key,
            )
        )
        if head is None:
            raise H3ResultPersistenceError(
                "H3 sequence selection head authority is unavailable"
            )
        if (
            not isinstance(getattr(head, "id", None), UUID)
            or getattr(head, "project_id", None) != request.project_id
            or getattr(head, "workflow_run_id", None)
            != request.workflow_run_id
            or getattr(head, "selection_key", None) != selection_key
            or getattr(head, "status", None) not in {"OPEN", "SEALED"}
            or type(getattr(head, "state_version", None)) is not int
            or getattr(head, "state_version", None) < 0
        ):
            raise H3ResultPersistenceError(
                "H3 sequence selection head authority does not match"
            )
        return head

    @staticmethod
    def _sequence_attempt_authorities(
        *,
        request: OperationRequest,
        result: OperationResult,
        sequence: H3SequenceV1,
        qc_evidences: tuple[H3AttemptQCEvidenceV1, ...],
        sequence_ordinal: int,
    ) -> tuple[_SequenceAttemptAuthority, ...]:
        lineages = (sequence.initial_attempt,)
        if sequence.repair_attempt is not None:
            lineages += (sequence.repair_attempt,)
        artifacts = tuple(result.output_artifact_refs)
        if (
            len(lineages) != len(artifacts)
            or len(qc_evidences) != len(artifacts)
        ):
            raise H3ResultPersistenceError(
                "H3 sequence QC evidence and lineage count must match its "
                "output artifacts"
            )

        attempts: list[_SequenceAttemptAuthority] = []
        for attempt_ordinal, (lineage, artifact, evidence) in enumerate(
            zip(lineages, artifacts, qc_evidences, strict=True)
        ):
            if (
                lineage.attempt_ordinal != attempt_ordinal
                or lineage.artifact_digest != artifact.content_digest
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence lineage does not match its output artifact"
                )
            if len(lineage.qc_evidence_ids) != 1:
                raise H3ResultPersistenceError(
                    "H3 sequence lineage must bind exactly one QC evaluation"
                )
            try:
                expected_qc_id = UUID(lineage.qc_evidence_ids[0])
            except (TypeError, ValueError) as exc:
                raise H3ResultPersistenceError(
                    "H3 sequence QC evidence identity is invalid"
                ) from exc
            qc_gate_key = (
                f"h3.sequence.{sequence_ordinal:03d}.attempt."
                f"{attempt_ordinal}"
            )
            if (
                evidence.evaluation_id != expected_qc_id
                or lineage.qc_evidence_ids
                != (str(evidence.evaluation_id),)
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC evaluation identity does not match its "
                    "lineage"
                )
            if evidence.project_id != result.project_id:
                raise H3ResultPersistenceError(
                    "H3 sequence QC project authority does not match"
                )
            if evidence.workflow_run_id != request.workflow_run_id:
                raise H3ResultPersistenceError(
                    "H3 sequence QC workflow authority does not match"
                )
            if evidence.stage != "clip":
                raise H3ResultPersistenceError(
                    "H3 sequence QC stage authority does not match"
                )
            if evidence.gate_key != qc_gate_key:
                raise H3ResultPersistenceError(
                    "H3 sequence QC gate authority does not match"
                )
            if (
                evidence.sequence_id != sequence.plan.sequence_id
                or evidence.candidate.sequence_id
                != sequence.plan.sequence_id
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC sequence authority does not match"
                )
            if (
                evidence.attempt_ordinal != attempt_ordinal
                or evidence.candidate.attempt_ordinal != attempt_ordinal
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC attempt ordinal does not match"
                )
            if (
                evidence.artifact_id != artifact.artifact_id
                or evidence.artifact_digest != artifact.content_digest
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC artifact authority does not match"
                )
            if (
                evidence.artifact_operation_run_id
                != result.operation_run_id
                or evidence.artifact_operation_attempt_id
                != result.operation_attempt_id
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC operation authority does not match"
                )
            duration_ms = sequence.plan.duration_seconds * 1000.0
            if any(
                defect.time_range_ms is not None
                and defect.time_range_ms[1] > duration_ms
                for defect in evidence.defects
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC defect range exceeds sequence duration"
                )
            attempts.append(
                _SequenceAttemptAuthority(
                    lineage=lineage,
                    artifact=artifact,
                    qc_evidence=evidence,
                    qc_gate_key=qc_gate_key,
                    candidate=evidence.candidate,
                )
            )

        initial_exceptions = attempts[0].candidate.exception_codes
        if not initial_exceptions:
            if len(attempts) != 1:
                raise H3ResultPersistenceError(
                    "H3 clean initial QC forbids a repair attempt"
                )
        elif (
            len(attempts) != 2
            or attempts[1].lineage.repair_trigger_codes
            != initial_exceptions
        ):
            raise H3ResultPersistenceError(
                "H3 exceptional initial QC requires exactly one matching repair"
            )
        return tuple(attempts)

    @staticmethod
    def _qc_rows_match(
        actual: object,
        expected: QCEvaluationFactRecord,
    ) -> bool:
        fields = (
            "id",
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            "artifact_id",
            "artifact_digest",
            "artifact_operation_run_id",
            "artifact_operation_attempt_id",
            "evidence_pack_id",
            "evidence_pack_digest",
            "expected_selection_version",
            "prompt_revision_id",
            "prompt_digest",
            "rubric_revision_id",
            "rubric_digest",
            "model_name",
            "model_version",
            "implementation_digest",
            "evaluator_bundle_digest",
            "judgment",
            "quality_score",
            "confidence",
            "defects",
            "recommended_actions",
            "repair_result",
            "h3_qc",
            "evaluation_digest",
        )
        if not all(
            getattr(actual, field, None) == getattr(expected, field)
            for field in fields
        ):
            return False
        try:
            actual_evaluated_at = _db_created_at(actual.evaluated_at)
            expected_evaluated_at = _db_created_at(expected.evaluated_at)
        except (AttributeError, H3ResultPersistenceError):
            return False
        return actual_evaluated_at == expected_evaluated_at

    @classmethod
    def _prepare_sequence_qc_authorities(
        cls,
        *,
        session: Session,
        request: OperationRequest,
        result: OperationResult,
        expected_selection_version: int,
        attempts: tuple[_SequenceAttemptAuthority, ...],
    ) -> tuple[_PreparedSequenceQC, ...]:
        if (
            type(expected_selection_version) is not int
            or expected_selection_version < 0
        ):
            raise H3ResultPersistenceError(
                "H3 sequence QC selection version authority is invalid"
            )
        prepared: list[_PreparedSequenceQC] = []
        for attempt in attempts:
            evidence = attempt.qc_evidence
            evidence_pack_row = session.scalar(
                select(EvidencePackRevisionRecord).where(
                    EvidencePackRevisionRecord.id
                    == evidence.evidence_pack_id,
                    EvidencePackRevisionRecord.project_id
                    == result.project_id,
                    EvidencePackRevisionRecord.digest
                    == evidence.evidence_pack_digest,
                    EvidencePackRevisionRecord.publishable.is_(True),
                )
            )
            if evidence_pack_row is None:
                raise H3ResultPersistenceError(
                    "H3 sequence QC evidence pack authority is unavailable"
                )
            if (
                getattr(evidence_pack_row, "id", None)
                != evidence.evidence_pack_id
                or getattr(evidence_pack_row, "project_id", None)
                != result.project_id
                or getattr(evidence_pack_row, "digest", None)
                != evidence.evidence_pack_digest
                or getattr(evidence_pack_row, "publishable", None) is not True
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC evidence pack authority does not match evidence"
                )
            prompt_row = session.scalar(
                select(QCPromptRevisionRecord).where(
                    QCPromptRevisionRecord.id
                    == evidence.prompt_revision_id,
                    QCPromptRevisionRecord.project_id
                    == result.project_id,
                )
            )
            if prompt_row is None:
                raise H3ResultPersistenceError(
                    "H3 sequence QC prompt authority is unavailable"
                )
            try:
                prompt = QCPromptRevision(
                    prompt_revision_id=prompt_row.id,
                    project_id=prompt_row.project_id,
                    prompt_key=prompt_row.prompt_key,
                    stage=QualityStage(prompt_row.stage),
                    revision=prompt_row.revision,
                    prompt_text=prompt_row.prompt_text,
                    parent_revision_id=prompt_row.parent_revision_id,
                    created_by_actor=prompt_row.created_by_actor,
                    created_at=_db_created_at(prompt_row.created_at),
                    prompt_digest=prompt_row.prompt_digest,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise H3ResultPersistenceError(
                    "persisted H3 sequence QC prompt authority is invalid"
                ) from exc
            if (
                prompt.prompt_key != evidence.prompt_key
                or prompt.stage is not QualityStage.CLIP
                or prompt.prompt_text != evidence.prompt_text
                or prompt.prompt_digest != evidence.prompt_digest
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC prompt authority does not match evidence"
                )

            try:
                evaluator = EvaluatorBundle(
                    project_id=result.project_id,
                    stage=QualityStage.CLIP,
                    prompt_revision_id=prompt.prompt_revision_id,
                    prompt_digest=prompt.prompt_digest,
                    rubric_revision_id=evidence.rubric_revision_id,
                    rubric_digest=evidence.rubric_digest,
                    model_name=evidence.evaluator_name,
                    model_version=evidence.evaluator_version,
                    implementation_digest=evidence.implementation_digest,
                )
            except (TypeError, ValueError) as exc:
                raise H3ResultPersistenceError(
                    "H3 sequence QC evaluator authority is invalid"
                ) from exc
            if evaluator.bundle_digest != evidence.evaluator_bundle_digest:
                raise H3ResultPersistenceError(
                    "H3 sequence QC evaluator authority does not match evidence"
                )

            policy_row = session.scalar(
                select(QCGatePolicySnapshotRecord).where(
                    QCGatePolicySnapshotRecord.id
                    == evidence.policy_snapshot_id,
                    QCGatePolicySnapshotRecord.project_id
                    == result.project_id,
                )
            )
            if policy_row is None:
                raise H3ResultPersistenceError(
                    "H3 sequence QC policy authority is unavailable"
                )
            try:
                policy = GatePolicySnapshot(
                    policy_snapshot_id=policy_row.id,
                    project_id=policy_row.project_id,
                    workflow_run_id=policy_row.workflow_run_id,
                    stage=QualityStage(policy_row.stage),
                    gate_key=policy_row.gate_key,
                    review_mode=policy_row.review_mode,
                    exhaustion_policy=policy_row.exhaustion_policy,
                    machine_qc_required=policy_row.machine_qc_required,
                    budget=policy_row.budget,
                    ranking_revision=policy_row.ranking_revision,
                    ranking_weights=policy_row.ranking_weights,
                    prompt_revision_id=policy_row.prompt_revision_id,
                    rubric_revision_id=policy_row.rubric_revision_id,
                    evaluator_bundle_digest=(
                        policy_row.evaluator_bundle_digest
                    ),
                    created_at=_db_created_at(policy_row.created_at),
                    policy_digest=policy_row.policy_digest,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise H3ResultPersistenceError(
                    "persisted H3 sequence QC policy authority is invalid"
                ) from exc
            if (
                policy.workflow_run_id != request.workflow_run_id
                or policy.stage is not QualityStage.CLIP
                or policy.gate_key != evidence.gate_key
                or policy.prompt_revision_id != evidence.prompt_revision_id
                or policy.rubric_revision_id
                != evidence.rubric_revision_id
                or policy.evaluator_bundle_digest
                != evidence.evaluator_bundle_digest
                or policy.ranking_revision
                != evidence.qc_policy_revision
                or policy.policy_digest
                != evidence.policy_snapshot_digest
            ):
                raise H3ResultPersistenceError(
                    "H3 sequence QC policy authority does not match evidence"
                )

            expected_evaluation_id = h3_qc_evaluation_id(
                result.project_id,
                result.operation_run_id,
                evidence.attempt_ordinal,
            )
            if evidence.evaluation_id != expected_evaluation_id:
                raise H3ResultPersistenceError(
                    "H3 sequence QC evaluation identity is not idempotent"
                )

            try:
                defects = tuple(
                    QCDefect(
                        defect_code=item.defect_code,
                        severity=item.severity,
                        message=item.message,
                        time_range_ms=item.time_range_ms,
                        subject_refs=(str(evidence.sequence_id),),
                        evidence_refs=item.evidence_refs,
                        recommended_repair_action=(
                            item.recommended_repair_action
                        ),
                    )
                    for item in evidence.defects
                )
                has_exceptions = bool(
                    evidence.candidate.exception_codes
                )
                disposition = (
                    RepairDisposition.NOT_REQUIRED
                    if not has_exceptions
                    else (
                        RepairDisposition.PLANNED
                        if evidence.attempt_ordinal == 0
                        else RepairDisposition.BUDGET_EXHAUSTED
                    )
                )
                evaluation = QCEvaluation(
                    evaluation_id=evidence.evaluation_id,
                    project_id=result.project_id,
                    workflow_run_id=request.workflow_run_id,
                    stage=QualityStage.CLIP,
                    gate_key=evidence.gate_key,
                    artifact=ArtifactBinding(
                        project_id=result.project_id,
                        artifact_id=attempt.artifact.artifact_id,
                        content_digest=attempt.artifact.content_digest,
                        operation_run_id=result.operation_run_id,
                        operation_attempt_id=result.operation_attempt_id,
                    ),
                    evidence_pack=EvidencePackBinding(
                        project_id=result.project_id,
                        evidence_pack_id=evidence.evidence_pack_id,
                        content_digest=evidence.evidence_pack_digest,
                        artifact_ids=(attempt.artifact.artifact_id,),
                    ),
                    expected_selection_version=(
                        expected_selection_version
                    ),
                    evaluator=evaluator,
                    judgment=(
                        MachineJudgment.FAIL
                        if has_exceptions
                        else MachineJudgment.PASS
                    ),
                    quality_score=(
                        sum(evidence.candidate.score_vector())
                        / len(evidence.candidate.score_vector())
                        * 100
                    ),
                    confidence=evidence.confidence,
                    defects=defects,
                    recommended_actions=tuple(
                        item.recommended_repair_action
                        for item in evidence.defects
                    ),
                    repair_result=RepairResult(disposition=disposition),
                    h3_qc=evidence.candidate,
                    evaluated_at=evidence.evaluated_at,
                )
            except (TypeError, ValueError) as exc:
                raise H3ResultPersistenceError(
                    "H3 sequence QC evaluation authority is invalid"
                ) from exc
            row = QCEvaluationFactRecord(
                id=evaluation.evaluation_id,
                project_id=evaluation.project_id,
                workflow_run_id=evaluation.workflow_run_id,
                stage=evaluation.stage.value,
                gate_key=evaluation.gate_key,
                artifact_id=evaluation.artifact.artifact_id,
                artifact_digest=evaluation.artifact.content_digest,
                artifact_operation_run_id=(
                    evaluation.artifact.operation_run_id
                ),
                artifact_operation_attempt_id=(
                    evaluation.artifact.operation_attempt_id
                ),
                evidence_pack_id=evaluation.evidence_pack.evidence_pack_id,
                evidence_pack_digest=(
                    evaluation.evidence_pack.content_digest
                ),
                expected_selection_version=(
                    evaluation.expected_selection_version
                ),
                prompt_revision_id=evaluator.prompt_revision_id,
                prompt_digest=evaluator.prompt_digest,
                rubric_revision_id=evaluator.rubric_revision_id,
                rubric_digest=evaluator.rubric_digest,
                model_name=evaluator.model_name,
                model_version=evaluator.model_version,
                implementation_digest=evaluator.implementation_digest,
                evaluator_bundle_digest=evaluator.bundle_digest,
                judgment=evaluation.judgment.value,
                quality_score=round(evaluation.quality_score * 10_000),
                confidence=round(evaluation.confidence * 1_000_000),
                defects=[
                    item.model_dump(mode="json")
                    for item in evaluation.defects
                ],
                recommended_actions=list(
                    evaluation.recommended_actions
                ),
                repair_result=evaluation.repair_result.model_dump(
                    mode="json"
                ),
                h3_qc=evaluation.h3_qc.model_dump(mode="json"),
                evaluation_digest=evaluation.evaluation_digest,
                evaluated_at=evaluation.evaluated_at,
            )
            existing = session.get(
                QCEvaluationFactRecord,
                evidence.evaluation_id,
            )
            if existing is not None and not cls._qc_rows_match(
                existing,
                row,
            ):
                raise H3ResultPersistenceError(
                    "persisted H3 sequence QC authority conflicts with draft"
                )
            prepared.append(
                _PreparedSequenceQC(
                    evidence=evidence,
                    row=row if existing is None else existing,
                    already_persisted=existing is not None,
                )
            )
        return tuple(prepared)

    @classmethod
    def _persist_prepared_sequence_qc(
        cls,
        *,
        session: Session,
        prepared: tuple[_PreparedSequenceQC, ...],
    ) -> None:
        pending = tuple(
            item for item in prepared if not item.already_persisted
        )
        if not pending:
            return
        for item in pending:
            try:
                with session.begin_nested():
                    session.add(item.row)
                    session.flush()
            except IntegrityError as exc:
                existing = session.get(
                    QCEvaluationFactRecord,
                    item.evidence.evaluation_id,
                )
                if existing is None or not cls._qc_rows_match(
                    existing,
                    item.row,
                ):
                    raise H3ResultPersistenceError(
                        "persisted H3 sequence QC authority conflicts with draft"
                    ) from exc

    @staticmethod
    def _h3_attempt_selection_authority(
        result: OperationResult,
    ) -> H3AttemptSelectionV1:
        structured_output = dict(result.structured_output)
        if set(structured_output) != {"selection"}:
            raise H3ResultPersistenceError(
                "H3 selection structured output must contain only selection"
            )
        try:
            return H3AttemptSelectionV1.model_validate(
                structured_output["selection"]
            )
        except (TypeError, ValueError) as exc:
            raise H3ResultPersistenceError(
                "H3 selection structured output is invalid"
            ) from exc

    @staticmethod
    def _selection_storage_authority(
        *,
        session: Session,
        request: OperationRequest,
        selection: H3AttemptSelectionV1,
        sequence_ordinal: int,
    ) -> tuple[SelectionHeadRecord, H3SequenceRevisionRecord]:
        selection_key = f"h3.sequence.{sequence_ordinal:03d}"
        head = session.scalar(
            select(SelectionHeadRecord).where(
                SelectionHeadRecord.project_id == request.project_id,
                SelectionHeadRecord.workflow_run_id
                == request.workflow_run_id,
                SelectionHeadRecord.selection_key == selection_key,
            )
        )
        if head is None:
            raise H3ResultPersistenceError(
                "H3 selection head authority is unavailable"
            )
        head_id = getattr(head, "id", None)
        head_project_id = getattr(head, "project_id", None)
        head_workflow_run_id = getattr(head, "workflow_run_id", None)
        head_selection_key = getattr(head, "selection_key", None)
        head_status = getattr(head, "status", None)
        head_current_revision = getattr(head, "current_revision", None)
        head_state_version = getattr(head, "state_version", None)
        if (
            not isinstance(head_id, UUID)
            or head_project_id != request.project_id
            or head_workflow_run_id != request.workflow_run_id
            or head_selection_key != selection_key
            or head_status not in {"OPEN", "SEALED"}
            or (
                head_current_revision is not None
                and (
                    type(head_current_revision) is not int
                    or head_current_revision <= 0
                )
            )
            or type(head_state_version) is not int
            or head_state_version < 0
        ):
            raise H3ResultPersistenceError(
                "H3 selection head authority does not match"
            )

        sequence = session.scalar(
            select(H3SequenceRevisionRecord).where(
                H3SequenceRevisionRecord.project_id == request.project_id,
                H3SequenceRevisionRecord.selection_head_id == head_id,
                H3SequenceRevisionRecord.ordinal == sequence_ordinal,
                H3SequenceRevisionRecord.sequence_id
                == selection.sequence_id,
            )
        )
        if sequence is None:
            raise H3ResultPersistenceError(
                "H3 selection sequence authority is unavailable"
            )
        sequence_id = getattr(sequence, "id", None)
        sequence_project_id = getattr(sequence, "project_id", None)
        sequence_head_id = getattr(sequence, "selection_head_id", None)
        sequence_ordinal_value = getattr(sequence, "ordinal", None)
        logical_sequence_id = getattr(sequence, "sequence_id", None)
        if (
            not isinstance(sequence_id, UUID)
            or sequence_project_id != request.project_id
            or sequence_head_id != head_id
            or type(sequence_ordinal_value) is not int
            or sequence_ordinal_value != sequence_ordinal
            or logical_sequence_id != selection.sequence_id
        ):
            raise H3ResultPersistenceError(
                "H3 selection sequence authority does not match"
            )
        return head, sequence

    @staticmethod
    def _persist_project_creative_ir(
        *,
        repository: _H3DomainRepository,
        authority: ProjectCreativeIRV1,
        result: OperationResult,
    ) -> None:
        repository.store_project_creative_ir(
            authority,
            command_idempotency_key=(
                f"h3-result:{result.operation_run_id}:project-ir"
            ),
        )

    @staticmethod
    def _persist_character_reference_set(
        *,
        repository: _H3DomainRepository,
        authority: CharacterReferenceSetV1,
        result: OperationResult,
    ) -> None:
        repository.store_character_source_asset(
            result.project_id,
            authority.source_asset,
            command_idempotency_key=(
                f"h3-result:{result.operation_run_id}:character-source"
            ),
        )
        repository.store_character_reference_set_revision(
            result.project_id,
            authority,
            command_idempotency_key=(
                f"h3-result:{result.operation_run_id}:reference-set"
            ),
        )

    @staticmethod
    def _finalize_character_reference_stage(
        *,
        authority: CharacterReferenceSetV1,
        result: OperationResult,
        stage: str,
    ) -> None:
        expected_state = {
            "character_reference.generate": "generating",
            "character_reference.qc": "qc_pending",
        }.get(stage)
        if expected_state is None or result.op_type != stage:
            raise H3ResultPersistenceError(
                "character reference finalizer received wrong operation"
            )
        if authority.state != expected_state:
            raise H3ResultPersistenceError(
                "character reference finalizer received wrong authority state"
            )
        # The committed JSON manifest is the immutable stage authority.  Only
        # freeze writes CharacterReferenceSet rows: generate and QC share view
        # asset identities, so writing both as domain revisions would violate
        # the view-asset primary-key invariant on a real database.

    @staticmethod
    def _persist_episode_generation_ir(
        *,
        repository: _H3DomainRepository,
        authority: EpisodeGenerationIRV1,
        result: OperationResult,
    ) -> None:
        repository.store_episode_generation_ir(
            result.project_id,
            authority,
            command_idempotency_key=(
                f"h3-result:{result.operation_run_id}:episode-ir"
            ),
        )

    @staticmethod
    def _persist_h3_attempt_selection(
        *,
        repository: _H3DomainRepository,
        authority: H3AttemptSelectionV1,
        result: OperationResult,
        sequence_revision_id: UUID,
        expected_state_version: int,
    ) -> None:
        repository.select_h3_attempt(
            result.project_id,
            sequence_revision_id,
            authority,
            command_idempotency_key=(
                f"h3-result:{result.operation_run_id}:selection"
            ),
            created_by_actor="system.h3-result-finalizer",
            expected_state_version=expected_state_version,
        )

    @staticmethod
    def _stored_record_id(stored: object, *, entity: str) -> UUID:
        value = getattr(stored, "value", None)
        record_id = getattr(value, "id", None)
        if not isinstance(record_id, UUID):
            raise H3ResultPersistenceError(
                f"persisted H3 {entity} identity is invalid"
            )
        return record_id

    @classmethod
    def _persist_h3_sequence(
        cls,
        *,
        repository: _H3DomainRepository,
        authority: H3SequenceV1,
        result: OperationResult,
        episode_revision_id: UUID,
        selection_head_id: UUID,
        qc_evaluation_ids: tuple[UUID, ...],
        attempts: tuple[_SequenceAttemptAuthority, ...],
    ) -> None:
        if len(qc_evaluation_ids) != len(attempts):
            raise H3ResultPersistenceError(
                "persisted H3 QC identities do not match sequence attempts"
            )
        stored_sequence = repository.store_h3_sequence_revision(
            result.project_id,
            episode_revision_id,
            authority,
            selection_head_id=selection_head_id,
            command_idempotency_key=(
                f"h3-result:{result.operation_run_id}:sequence"
            ),
        )
        sequence_revision_id = cls._stored_record_id(
            stored_sequence,
            entity="sequence revision",
        )

        initial_attempt_id: UUID | None = None
        for attempt, qc_evaluation_id in zip(
            attempts,
            qc_evaluation_ids,
            strict=True,
        ):
            attempt_ordinal = attempt.lineage.attempt_ordinal
            repair_of_attempt_id = (
                initial_attempt_id if attempt_ordinal == 1 else None
            )
            stored_attempt = repository.record_h3_runtime_attempt(
                result.project_id,
                sequence_revision_id,
                attempt.lineage,
                operation_run_id=result.operation_run_id,
                operation_attempt_id=result.operation_attempt_id,
                artifact_id=attempt.artifact.artifact_id,
                prompt_digest=authority.prompt_digest,
                workflow_digest=authority.workflow_digest,
                command_idempotency_key=(
                    f"h3-result:{result.operation_run_id}:attempt:"
                    f"{attempt_ordinal}"
                ),
                qc_evaluation_id=qc_evaluation_id,
                qc_gate_key=attempt.qc_gate_key,
                repair_of_attempt_id=repair_of_attempt_id,
            )
            stored_attempt_id = cls._stored_record_id(
                stored_attempt,
                entity=f"attempt {attempt_ordinal}",
            )
            if attempt_ordinal == 0:
                initial_attempt_id = stored_attempt_id


__all__ = [
    "H3ResultPersistenceError",
    "H3SuccessfulResultFinalizer",
]
