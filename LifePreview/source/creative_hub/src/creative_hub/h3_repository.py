"""Fail-closed persistence bindings for the AMD MiniMax H3 domain.

The repository deliberately reuses the orchestration runtime's generic
operation, provider, artifact, QC, and selection facts.  The tables owned by
this module only bind those facts to the frozen H3 contracts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from shared_contracts import (
    CharacterReferenceSetV1,
    CharacterReferenceSourceAssetV1,
    EpisodeGenerationIRV1,
    H3AttemptSelectionV1,
    H3CandidateScoreV1,
    H3DeliveryV1,
    H3_PRODUCT_CONTRACT_VERSIONS,
    H3SequencePlanV1,
    H3SequenceV1,
    H3SourceLineageV1,
    ProjectCreativeIRV1,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from drama.h3.assembly import H3AssemblyError, H3SelectedSegment

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import (
    ArtifactRecordRow,
    CharacterReferenceSetRevisionRecord,
    CharacterReferenceViewAssetRecord,
    CharacterSourceAssetRecord,
    DeliveryRevisionRecord,
    EpisodeGenerationIRRevisionRecord,
    H3RuntimeAttemptRecord,
    H3SequenceRevisionRecord,
    ProjectCreativeIRRevisionRecord,
    QCEvaluationFactRecord,
    SelectionHeadRecord,
    SelectionRevisionRecord,
    VideoJobProjectionRecord,
    VideoJobSequenceProjectionRecord,
)
from creative_hub.db.repositories import (
    ConcurrentStateConflict,
    IdempotencyConflict,
    InvalidState,
    PersistenceError,
    SelectionRepository,
    Stored,
)


def _json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    """Detach and canonicalize a JSON object before it reaches an ORM row."""

    rendered = json.dumps(
        dict(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    normalized = json.loads(rendered)
    if not isinstance(normalized, dict):
        raise ValueError("H3 authority payload must be a JSON object")
    return normalized


def _require_command_key(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise ValueError("command_idempotency_key must contain 1 to 255 characters")
    return value


def _same_replay(
    record: Any,
    *,
    digest_attribute: str,
    expected_digest: str,
    expected_attributes: Mapping[str, Any] | None = None,
    command_idempotency_key: str,
    entity: str,
) -> Stored:
    attributes = dict(expected_attributes or {})
    if getattr(record, digest_attribute) != expected_digest or any(
        getattr(record, name) != expected for name, expected in attributes.items()
    ):
        raise IdempotencyConflict(
            f"idempotency key {command_idempotency_key!r} belongs to a "
            f"different {entity}"
        )
    return Stored(record, False)


def _same_h3_sequence_replay(
    record: Any,
    *,
    episode_revision_id: UUID,
    plan_digest: str,
    prompt_digest: str,
    workflow_digest: str,
    selection_head_id: UUID,
    command_idempotency_key: str,
) -> Stored:
    return _same_replay(
        record,
        digest_attribute="plan_digest",
        expected_digest=plan_digest,
        expected_attributes={
            "episode_revision_id": episode_revision_id,
            "prompt_digest": prompt_digest,
            "workflow_digest": workflow_digest,
            "selection_head_id": selection_head_id,
        },
        command_idempotency_key=command_idempotency_key,
        entity="H3 sequence",
    )


def _same_h3_selection_replay(
    record: Any,
    *,
    selection_head_id: UUID,
    selected: Any,
    payload_digest: str,
    created_by_actor: str,
    command_idempotency_key: str,
) -> Stored:
    return _same_replay(
        record,
        digest_attribute="payload_digest",
        expected_digest=payload_digest,
        expected_attributes={
            "selection_head_id": selection_head_id,
            "selected_operation_run_id": selected.operation_run_id,
            "selected_attempt_id": selected.operation_attempt_id,
            "artifact_id": selected.artifact_id,
            "artifact_digest": selected.artifact_digest,
            "created_by_actor": created_by_actor,
        },
        command_idempotency_key=command_idempotency_key,
        entity="H3 selection",
    )


def _selection_revision_matches_attempt(revision: Any, attempt: Any) -> bool:
    return all(
        getattr(revision, name, None) == getattr(attempt, attempt_name, None)
        for name, attempt_name in (
            ("selected_operation_run_id", "operation_run_id"),
            ("selected_attempt_id", "operation_attempt_id"),
            ("artifact_id", "artifact_id"),
            ("artifact_digest", "artifact_digest"),
        )
    )


def _selection_revision_allows_projection_status(
    revision: Any,
    status: str,
) -> bool:
    decision = getattr(revision, "decision", None)
    if status == "selected_clean":
        return decision == "SELECTED"
    if status == "selected_with_qc_exception":
        return decision == "DEGRADED_ACCEPTED"
    return decision in {"SELECTED", "DEGRADED_ACCEPTED"}


def _guard_projection_version(
    session: Session,
    *,
    project_id: UUID,
    projection_id: UUID,
    expected_state_version: int,
) -> None:
    guarded = session.execute(
        update(VideoJobSequenceProjectionRecord)
        .where(
            VideoJobSequenceProjectionRecord.id == projection_id,
            VideoJobSequenceProjectionRecord.project_id == project_id,
            VideoJobSequenceProjectionRecord.state_version
            == expected_state_version,
        )
        .values(
            state_version=expected_state_version,
            updated_at=VideoJobSequenceProjectionRecord.updated_at,
        )
    )
    if guarded.rowcount != 1:
        raise ConcurrentStateConflict(
            "video job sequence projection changed concurrently"
        )


def _h3_candidate_from_evaluation(
    evaluation: Any,
    *,
    sequence_id: UUID,
    attempt_ordinal: int,
    artifact_id: UUID,
    artifact_digest: str,
) -> H3CandidateScoreV1:
    """Derive the selection vector exclusively from persisted generic QC."""

    if (
        getattr(evaluation, "artifact_id", None) != artifact_id
        or getattr(evaluation, "artifact_digest", None) != artifact_digest
    ):
        raise PersistenceError("H3 QC artifact authority does not match the attempt")
    raw_qc = getattr(evaluation, "h3_qc", None)
    if not isinstance(raw_qc, Mapping):
        raise PersistenceError("H3 QC authority is unavailable")
    try:
        candidate = H3CandidateScoreV1.model_validate(dict(raw_qc))
    except ValueError as exc:
        raise PersistenceError("H3 QC candidate authority is invalid") from exc
    if (
        candidate.sequence_id != sequence_id
        or candidate.attempt_ordinal != attempt_ordinal
    ):
        raise PersistenceError("H3 QC candidate does not match the sequence attempt")
    return candidate


def _repair_triggers_from_evaluation(
    evaluation: Any,
    *,
    sequence_id: UUID,
    artifact_id: UUID,
    artifact_digest: str,
) -> tuple[str, ...]:
    candidate = _h3_candidate_from_evaluation(
        evaluation,
        sequence_id=sequence_id,
        attempt_ordinal=0,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )
    return candidate.exception_codes


class H3Repository:
    """Uses the caller's transaction and never commits on its behalf."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def store_project_creative_ir(
        self,
        project_ir: ProjectCreativeIRV1 | Mapping[str, Any],
        *,
        command_idempotency_key: str,
        project_ir_id: UUID | None = None,
    ) -> Stored:
        command = _require_command_key(command_idempotency_key)
        authority = ProjectCreativeIRV1.model_validate(project_ir)
        payload = _json_object(authority.model_dump(mode="json"))
        record_id = project_ir_id or authority.project_id
        replay = self._command_replay(
            ProjectCreativeIRRevisionRecord,
            authority.project_id,
            command,
        )
        if replay is not None:
            return _same_replay(
                replay,
                digest_attribute="revision_digest",
                expected_digest=authority.revision_digest,
                command_idempotency_key=command,
                entity="project creative IR",
            )
        existing = self.session.scalar(
            select(ProjectCreativeIRRevisionRecord).where(
                ProjectCreativeIRRevisionRecord.project_id
                == authority.project_id,
                ProjectCreativeIRRevisionRecord.revision_digest
                == authority.revision_digest,
            )
        )
        if existing is not None:
            return Stored(existing, False)
        row = ProjectCreativeIRRevisionRecord(
            id=record_id,
            project_id=authority.project_id,
            evidence_pack_revision_id=authority.evidence_pack_revision_id,
            trial_script_revision_id=authority.trial_script_revision_id,
            payload=payload,
            revision_digest=authority.revision_digest,
            command_idempotency_key=command,
        )
        self.session.add(row)
        self.session.flush()
        return Stored(row, True)

    def store_character_source_asset(
        self,
        project_id: UUID,
        source_asset: CharacterReferenceSourceAssetV1 | Mapping[str, Any],
        *,
        command_idempotency_key: str,
    ) -> Stored:
        command = _require_command_key(command_idempotency_key)
        authority = CharacterReferenceSourceAssetV1.model_validate(source_asset)
        if not authority.verified or not authority.historical or authority.ai_derived:
            raise ValueError(
                "character source must be verified, historical, and not AI-derived"
            )
        replay = self._command_replay(
            CharacterSourceAssetRecord, project_id, command
        )
        if replay is not None:
            return _same_replay(
                replay,
                digest_attribute="content_digest",
                expected_digest=authority.content_digest,
                expected_attributes={
                    "id": authority.asset_id,
                    "artifact_id": authority.asset_id,
                    "verified": authority.verified,
                    "historical": authority.historical,
                    "ai_derived": authority.ai_derived,
                    "uploaded_by": authority.uploaded_by,
                    "uploaded_at": authority.uploaded_at,
                },
                command_idempotency_key=command,
                entity="character source asset",
            )
        artifact = self._committed_artifact(
            project_id=project_id,
            artifact_id=authority.asset_id,
            digest=authority.content_digest,
        )
        source_attributes = {
            "id": authority.asset_id,
            "artifact_id": artifact.id,
            "verified": authority.verified,
            "historical": authority.historical,
            "ai_derived": authority.ai_derived,
            "uploaded_by": authority.uploaded_by,
            "uploaded_at": authority.uploaded_at,
        }
        existing = self.session.scalar(
            select(CharacterSourceAssetRecord).where(
                CharacterSourceAssetRecord.project_id == project_id,
                CharacterSourceAssetRecord.artifact_id == artifact.id,
            )
        )
        if existing is not None:
            return _same_replay(
                existing,
                digest_attribute="content_digest",
                expected_digest=authority.content_digest,
                expected_attributes=source_attributes,
                command_idempotency_key=command,
                entity="character source asset",
            )
        row = CharacterSourceAssetRecord(
            id=authority.asset_id,
            project_id=project_id,
            artifact_id=artifact.id,
            content_digest=authority.content_digest,
            verified=authority.verified,
            historical=authority.historical,
            ai_derived=authority.ai_derived,
            uploaded_by=authority.uploaded_by,
            uploaded_at=authority.uploaded_at,
            command_idempotency_key=command,
        )
        self.session.add(row)
        self.session.flush()
        return Stored(row, True)

    def store_character_reference_set_revision(
        self,
        project_id: UUID,
        reference_set: CharacterReferenceSetV1 | Mapping[str, Any],
        *,
        command_idempotency_key: str,
    ) -> Stored:
        command = _require_command_key(command_idempotency_key)
        authority = CharacterReferenceSetV1.model_validate(reference_set)
        payload = _json_object(authority.model_dump(mode="json"))
        replay = self._command_replay(
            CharacterReferenceSetRevisionRecord, project_id, command
        )
        if replay is not None:
            stored = _same_replay(
                replay,
                digest_attribute="reference_set_digest",
                expected_digest=authority.reference_set_digest,
                command_idempotency_key=command,
                entity="character reference set",
            )
            view_count = len(
                self.session.scalars(
                    select(CharacterReferenceViewAssetRecord).where(
                        CharacterReferenceViewAssetRecord.project_id == project_id,
                        CharacterReferenceViewAssetRecord.reference_set_revision_id
                        == replay.id,
                    )
                ).all()
            )
            if view_count != len(authority.views):
                raise PersistenceError("character reference set is partially stored")
            return stored
        source = self.session.scalar(
            select(CharacterSourceAssetRecord).where(
                CharacterSourceAssetRecord.id == authority.source_asset.asset_id,
                CharacterSourceAssetRecord.project_id == project_id,
                CharacterSourceAssetRecord.content_digest
                == authority.source_asset.content_digest,
            )
        )
        if source is None:
            raise PersistenceError("verified character source asset is unavailable")
        existing = self.session.scalar(
            select(CharacterReferenceSetRevisionRecord).where(
                CharacterReferenceSetRevisionRecord.project_id == project_id,
                CharacterReferenceSetRevisionRecord.reference_set_id
                == authority.reference_set_id,
                CharacterReferenceSetRevisionRecord.reference_set_digest
                == authority.reference_set_digest,
            )
        )
        if existing is not None:
            return Stored(existing, False)
        row = CharacterReferenceSetRevisionRecord(
            id=authority.reference_set_revision_id,
            project_id=project_id,
            reference_set_id=authority.reference_set_id,
            source_asset_id=source.id,
            character_id=authority.character_id,
            age_stage=authority.age_stage,
            state=authority.state,
            model_family=authority.model_revision.model_family,
            model_revision=authority.model_revision.revision,
            workflow_digest=authority.model_revision.workflow_sha256,
            payload=payload,
            reference_set_digest=authority.reference_set_digest,
            command_idempotency_key=command,
        )
        self.session.add(row)
        self.session.flush()
        for view in authority.views:
            artifact = self._committed_artifact(
                project_id=project_id,
                artifact_id=view.asset_id,
                digest=view.image_digest,
            )
            self.session.add(
                CharacterReferenceViewAssetRecord(
                    id=view.asset_id,
                    project_id=project_id,
                    reference_set_revision_id=row.id,
                    artifact_id=artifact.id,
                    view_name=view.view_name,
                    attempt_ordinal=view.attempt_ordinal,
                    image_digest=view.image_digest,
                    ai_derived=view.ai_derived,
                    historical=view.historical,
                    identity_control=view.identity_control,
                    single_view_qc_passed=view.single_view_qc_passed,
                    generated_at=view.generated_at,
                    payload=_json_object(view.model_dump(mode="json")),
                )
            )
        self.session.flush()
        return Stored(row, True)

    def store_episode_generation_ir(
        self,
        project_id: UUID,
        episode_ir: EpisodeGenerationIRV1 | Mapping[str, Any],
        *,
        command_idempotency_key: str,
    ) -> Stored:
        command = _require_command_key(command_idempotency_key)
        authority = EpisodeGenerationIRV1.model_validate(episode_ir)
        if authority.project_ir.project_id != project_id:
            raise ValueError("episode IR belongs to a different project")
        payload = _json_object(authority.model_dump(mode="json"))
        replay = self._command_replay(
            EpisodeGenerationIRRevisionRecord, project_id, command
        )
        if replay is not None:
            return _same_replay(
                replay,
                digest_attribute="revision_digest",
                expected_digest=authority.revision_digest,
                command_idempotency_key=command,
                entity="episode generation IR",
            )
        project_ir = self.session.scalar(
            select(ProjectCreativeIRRevisionRecord).where(
                ProjectCreativeIRRevisionRecord.id == authority.project_ir_id,
                ProjectCreativeIRRevisionRecord.project_id == project_id,
                ProjectCreativeIRRevisionRecord.revision_digest
                == authority.project_ir_revision_digest,
            )
        )
        if project_ir is None:
            raise PersistenceError("frozen project creative IR is unavailable")
        declared_reference_ids = set(authority.reference_set_revision_ids)
        stored_reference_ids = set(
            self.session.scalars(
                select(CharacterReferenceSetRevisionRecord.id).where(
                    CharacterReferenceSetRevisionRecord.project_id == project_id,
                    CharacterReferenceSetRevisionRecord.id.in_(
                        declared_reference_ids
                    ),
                    CharacterReferenceSetRevisionRecord.state == "frozen",
                )
            ).all()
        )
        if stored_reference_ids != declared_reference_ids:
            raise PersistenceError("episode references are not all frozen and stored")
        row = EpisodeGenerationIRRevisionRecord(
            id=authority.episode_revision_id,
            project_id=project_id,
            project_ir_id=project_ir.id,
            project_ir_revision_digest=authority.project_ir_revision_digest,
            model_family=authority.model_family,
            duration_allocation_digest=authority.duration_allocation_digest,
            payload=payload,
            revision_digest=authority.revision_digest,
            command_idempotency_key=command,
        )
        self.session.add(row)
        self.session.flush()
        return Stored(row, True)

    def store_h3_sequence_revision(
        self,
        project_id: UUID,
        episode_revision_id: UUID,
        sequence: H3SequencePlanV1 | H3SequenceV1 | Mapping[str, Any],
        *,
        prompt_digest: str | None = None,
        workflow_digest: str | None = None,
        selection_head_id: UUID,
        command_idempotency_key: str,
        sequence_revision_id: UUID | None = None,
    ) -> Stored:
        command = _require_command_key(command_idempotency_key)
        if isinstance(sequence, H3SequenceV1):
            plan = sequence.plan
            prompt_digest = prompt_digest or sequence.prompt_digest
            workflow_digest = workflow_digest or sequence.workflow_digest
        else:
            source = dict(sequence) if isinstance(sequence, Mapping) else sequence
            if isinstance(source, Mapping) and "plan" in source:
                runtime = H3SequenceV1.model_validate(source)
                plan = runtime.plan
                prompt_digest = prompt_digest or runtime.prompt_digest
                workflow_digest = workflow_digest or runtime.workflow_digest
            else:
                plan = H3SequencePlanV1.model_validate(source)
        self._require_digest(prompt_digest, "prompt_digest")
        self._require_digest(workflow_digest, "workflow_digest")
        episode = self.session.scalar(
            select(EpisodeGenerationIRRevisionRecord).where(
                EpisodeGenerationIRRevisionRecord.id == episode_revision_id,
                EpisodeGenerationIRRevisionRecord.project_id == project_id,
            )
        )
        if episode is None:
            raise PersistenceError("episode generation IR is unavailable")
        episode_authority = EpisodeGenerationIRV1.model_validate(episode.payload)
        declared = next(
            (
                item
                for item in episode_authority.sequence_plans
                if item.sequence_id == plan.sequence_id
            ),
            None,
        )
        if declared is None or declared != plan:
            raise ValueError("sequence plan does not match the frozen episode IR")
        selection_head = self.session.scalar(
            select(SelectionHeadRecord).where(
                SelectionHeadRecord.id == selection_head_id,
                SelectionHeadRecord.project_id == project_id,
            )
        )
        if selection_head is None:
            raise PersistenceError("sequence selection head is unavailable")
        payload = _json_object(plan.model_dump(mode="json"))
        plan_digest = canonical_json_digest(payload)
        replay = self._command_replay(H3SequenceRevisionRecord, project_id, command)
        if replay is not None:
            return _same_h3_sequence_replay(
                replay,
                episode_revision_id=episode_revision_id,
                plan_digest=plan_digest,
                prompt_digest=prompt_digest,
                workflow_digest=workflow_digest,
                selection_head_id=selection_head_id,
                command_idempotency_key=command,
            )
        row = H3SequenceRevisionRecord(
            id=sequence_revision_id or plan.sequence_id,
            project_id=project_id,
            episode_revision_id=episode_revision_id,
            sequence_id=plan.sequence_id,
            ordinal=plan.ordinal,
            mode=plan.mode.value,
            frame_count=plan.frame_count,
            fps=plan.fps,
            duration_seconds=plan.duration_seconds,
            plan_payload=payload,
            plan_digest=plan_digest,
            prompt_digest=prompt_digest,
            workflow_digest=workflow_digest,
            selection_head_id=selection_head_id,
            command_idempotency_key=command,
        )
        self.session.add(row)
        self.session.flush()
        return Stored(row, True)

    def record_h3_runtime_attempt(
        self,
        project_id: UUID,
        sequence_revision_id: UUID,
        lineage: H3SourceLineageV1 | Mapping[str, Any],
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
        h3_attempt_id: UUID | None = None,
    ) -> Stored:
        command = _require_command_key(command_idempotency_key)
        authority = H3SourceLineageV1.model_validate(lineage)
        self._require_digest(prompt_digest, "prompt_digest")
        self._require_digest(workflow_digest, "workflow_digest")
        if not isinstance(qc_gate_key, str) or not qc_gate_key.strip():
            raise ValueError("qc_gate_key is required")
        sequence = self.session.scalar(
            select(H3SequenceRevisionRecord).where(
                H3SequenceRevisionRecord.id == sequence_revision_id,
                H3SequenceRevisionRecord.project_id == project_id,
            )
        )
        if sequence is None:
            raise PersistenceError("H3 sequence revision is unavailable")
        if (
            sequence.prompt_digest != prompt_digest
            or sequence.workflow_digest != workflow_digest
        ):
            raise ValueError("attempt compiler digests do not match the sequence")
        if authority.attempt_ordinal == 0:
            if repair_of_attempt_id is not None or authority.repair_trigger_codes:
                raise ValueError("initial H3 attempt cannot carry repair lineage")
            repair_of_attempt_ordinal = None
        else:
            if repair_of_attempt_id is None or not authority.repair_trigger_codes:
                raise ValueError("repair H3 attempt requires its initial lineage")
            parent = self.session.scalar(
                select(H3RuntimeAttemptRecord).where(
                    H3RuntimeAttemptRecord.id == repair_of_attempt_id,
                    H3RuntimeAttemptRecord.project_id == project_id,
                    H3RuntimeAttemptRecord.sequence_revision_id
                    == sequence_revision_id,
                    H3RuntimeAttemptRecord.attempt_ordinal == 0,
                )
            )
            if parent is None:
                raise PersistenceError(
                    "repair parent is not this sequence's initial attempt"
                )
            parent_evaluation = self.session.scalar(
                select(QCEvaluationFactRecord).where(
                    QCEvaluationFactRecord.id == parent.qc_evaluation_id,
                    QCEvaluationFactRecord.project_id == project_id,
                    QCEvaluationFactRecord.artifact_id == parent.artifact_id,
                    QCEvaluationFactRecord.artifact_digest
                    == parent.artifact_digest,
                    QCEvaluationFactRecord.gate_key == parent.qc_gate_key,
                )
            )
            if parent_evaluation is None:
                raise PersistenceError("repair parent QC authority is unavailable")
            expected_triggers = _repair_triggers_from_evaluation(
                parent_evaluation,
                sequence_id=sequence.sequence_id,
                artifact_id=parent.artifact_id,
                artifact_digest=parent.artifact_digest,
            )
            if authority.repair_trigger_codes != expected_triggers:
                raise InvalidState(
                    "repair trigger codes do not match the initial QC exceptions"
                )
            repair_of_attempt_ordinal = 0
        artifact = self._committed_artifact(
            project_id=project_id,
            artifact_id=artifact_id,
            digest=authority.artifact_digest,
            operation_run_id=operation_run_id,
            operation_attempt_id=operation_attempt_id,
        )
        evaluation = self.session.scalar(
            select(QCEvaluationFactRecord).where(
                QCEvaluationFactRecord.id == qc_evaluation_id,
                QCEvaluationFactRecord.project_id == project_id,
                QCEvaluationFactRecord.artifact_id == artifact_id,
                QCEvaluationFactRecord.artifact_digest
                == authority.artifact_digest,
                QCEvaluationFactRecord.gate_key == qc_gate_key,
            )
        )
        if evaluation is None:
            raise PersistenceError("H3 QC does not bind the attempt artifact and gate")
        _h3_candidate_from_evaluation(
            evaluation,
            sequence_id=sequence.sequence_id,
            attempt_ordinal=authority.attempt_ordinal,
            artifact_id=artifact_id,
            artifact_digest=authority.artifact_digest,
        )
        payload = _json_object(authority.model_dump(mode="json"))
        lineage_digest = canonical_json_digest(payload)
        attempt_attributes = {
            "sequence_revision_id": sequence_revision_id,
            "attempt_ordinal": authority.attempt_ordinal,
            "operation_run_id": operation_run_id,
            "operation_attempt_id": operation_attempt_id,
            "artifact_id": artifact_id,
            "artifact_digest": authority.artifact_digest,
            "qc_evaluation_id": qc_evaluation_id,
            "qc_gate_key": qc_gate_key,
            "repair_of_attempt_id": repair_of_attempt_id,
            "repair_of_attempt_ordinal": repair_of_attempt_ordinal,
            "prompt_digest": prompt_digest,
            "workflow_digest": workflow_digest,
        }
        replay = self._command_replay(H3RuntimeAttemptRecord, project_id, command)
        if replay is not None:
            return _same_replay(
                replay,
                digest_attribute="source_lineage_digest",
                expected_digest=lineage_digest,
                expected_attributes=attempt_attributes,
                command_idempotency_key=command,
                entity="H3 runtime attempt",
            )
        existing = self.session.scalar(
            select(H3RuntimeAttemptRecord).where(
                H3RuntimeAttemptRecord.project_id == project_id,
                H3RuntimeAttemptRecord.sequence_revision_id
                == sequence_revision_id,
                H3RuntimeAttemptRecord.attempt_ordinal
                == authority.attempt_ordinal,
            )
        )
        if existing is not None:
            return _same_replay(
                existing,
                digest_attribute="source_lineage_digest",
                expected_digest=lineage_digest,
                expected_attributes=attempt_attributes,
                command_idempotency_key=command,
                entity="H3 runtime attempt",
            )
        row = H3RuntimeAttemptRecord(
            id=h3_attempt_id or uuid4(),
            project_id=project_id,
            sequence_revision_id=sequence_revision_id,
            attempt_ordinal=authority.attempt_ordinal,
            operation_run_id=operation_run_id,
            operation_attempt_id=operation_attempt_id,
            artifact_id=artifact.id,
            artifact_digest=authority.artifact_digest,
            qc_evaluation_id=qc_evaluation_id,
            qc_gate_key=qc_gate_key,
            repair_of_attempt_id=repair_of_attempt_id,
            repair_of_attempt_ordinal=repair_of_attempt_ordinal,
            repair_trigger_codes=list(authority.repair_trigger_codes),
            prompt_digest=prompt_digest,
            workflow_digest=workflow_digest,
            source_lineage_payload=payload,
            source_lineage_digest=lineage_digest,
            command_idempotency_key=command,
        )
        self.session.add(row)
        self.session.flush()
        return Stored(row, True)

    def get_h3_attempts(
        self,
        project_id: UUID,
        sequence_revision_id: UUID,
    ) -> tuple[H3RuntimeAttemptRecord, ...]:
        return tuple(
            self.session.scalars(
                select(H3RuntimeAttemptRecord)
                .where(
                    H3RuntimeAttemptRecord.project_id == project_id,
                    H3RuntimeAttemptRecord.sequence_revision_id
                    == sequence_revision_id,
                )
                .order_by(H3RuntimeAttemptRecord.attempt_ordinal)
            ).all()
        )

    def select_h3_attempt(
        self,
        project_id: UUID,
        sequence_revision_id: UUID,
        selection: H3AttemptSelectionV1 | Mapping[str, Any],
        *,
        command_idempotency_key: str,
        created_by_actor: str,
        expected_state_version: int = 0,
    ) -> Stored:
        command = _require_command_key(command_idempotency_key)
        authority = H3AttemptSelectionV1.model_validate(selection)
        sequence = self.session.scalar(
            select(H3SequenceRevisionRecord).where(
                H3SequenceRevisionRecord.id == sequence_revision_id,
                H3SequenceRevisionRecord.project_id == project_id,
                H3SequenceRevisionRecord.sequence_id == authority.sequence_id,
            )
        )
        if sequence is None:
            raise PersistenceError("selection sequence is unavailable")
        attempts = self.get_h3_attempts(project_id, sequence_revision_id)
        derived_candidates: list[H3CandidateScoreV1] = []
        for attempt in attempts:
            evaluation = self.session.scalar(
                select(QCEvaluationFactRecord).where(
                    QCEvaluationFactRecord.id == attempt.qc_evaluation_id,
                    QCEvaluationFactRecord.project_id == project_id,
                    QCEvaluationFactRecord.artifact_id == attempt.artifact_id,
                    QCEvaluationFactRecord.artifact_digest
                    == attempt.artifact_digest,
                    QCEvaluationFactRecord.gate_key == attempt.qc_gate_key,
                )
            )
            if evaluation is None:
                raise PersistenceError("stored H3 attempt QC authority is unavailable")
            derived_candidates.append(
                _h3_candidate_from_evaluation(
                    evaluation,
                    sequence_id=sequence.sequence_id,
                    attempt_ordinal=attempt.attempt_ordinal,
                    artifact_id=attempt.artifact_id,
                    artifact_digest=attempt.artifact_digest,
                )
            )
        derived = tuple(derived_candidates)
        if authority.candidates != derived:
            raise InvalidState(
                "provided H3 selection candidates do not match persisted QC authority"
            )
        if tuple(row.attempt_ordinal for row in attempts) != tuple(
            candidate.attempt_ordinal for candidate in derived
        ):
            raise InvalidState("selection candidates do not match stored H3 attempts")
        selected = next(
            row
            for row in attempts
            if row.attempt_ordinal == authority.selected_attempt_ordinal
        )
        payload = _json_object(authority.model_dump(mode="json"))
        replay = self.session.scalar(
            select(SelectionRevisionRecord).where(
                SelectionRevisionRecord.project_id == project_id,
                SelectionRevisionRecord.command_idempotency_key == command,
            )
        )
        if replay is not None:
            return _same_h3_selection_replay(
                replay,
                selection_head_id=sequence.selection_head_id,
                selected=selected,
                payload_digest=canonical_json_digest(payload),
                created_by_actor=created_by_actor,
                command_idempotency_key=command,
            )
        return SelectionRepository(self.session).compare_and_set(
            selection_head_id=sequence.selection_head_id,
            project_id=project_id,
            expected_state_version=expected_state_version,
            selected_operation_run_id=selected.operation_run_id,
            selected_attempt_id=selected.operation_attempt_id,
            artifact_id=selected.artifact_id,
            artifact_digest=selected.artifact_digest,
            decision=(
                "SELECTED"
                if authority.selected_cleanly
                else "DEGRADED_ACCEPTED"
            ),
            command_idempotency_key=command,
            created_by_actor=created_by_actor,
            payload=payload,
            reason=authority.selection_reason,
            seal=True,
        )

    def upsert_video_job_sequence_projection(
        self,
        project_id: UUID,
        video_job_projection_id: UUID,
        sequence_revision_id: UUID,
        *,
        ordinal: int,
        status: str,
        payload: Mapping[str, Any],
        expected_state_version: int,
        selected_attempt_id: UUID | None = None,
        projection_id: UUID | None = None,
    ) -> Stored:
        allowed = {
            "planned",
            "generating_initial",
            "qc_initial",
            "repair_planned",
            "generating_repair",
            "qc_repair",
            "selecting_best",
            "selected_clean",
            "selected_with_qc_exception",
            "ready_for_assembly",
            "assembled",
            "delivered",
            "runtime_error",
        }
        if status not in allowed or ordinal <= 0:
            raise ValueError("video job sequence projection state is invalid")
        if expected_state_version < 0:
            raise ValueError("expected_state_version must be non-negative")
        job = self.session.scalar(
            select(VideoJobProjectionRecord).where(
                VideoJobProjectionRecord.id == video_job_projection_id,
                VideoJobProjectionRecord.project_id == project_id,
            )
        )
        sequence = self.session.scalar(
            select(H3SequenceRevisionRecord).where(
                H3SequenceRevisionRecord.id == sequence_revision_id,
                H3SequenceRevisionRecord.project_id == project_id,
                H3SequenceRevisionRecord.ordinal == ordinal,
            )
        )
        if job is None or sequence is None:
            raise PersistenceError("video job or sequence authority is unavailable")
        if selected_attempt_id is not None:
            selected = self.session.scalar(
                select(H3RuntimeAttemptRecord).where(
                    H3RuntimeAttemptRecord.id == selected_attempt_id,
                    H3RuntimeAttemptRecord.project_id == project_id,
                    H3RuntimeAttemptRecord.sequence_revision_id
                    == sequence_revision_id,
                )
            )
            if selected is None:
                raise PersistenceError("projection selected attempt is invalid")
            head = self.session.scalar(
                select(SelectionHeadRecord).where(
                    SelectionHeadRecord.id == sequence.selection_head_id,
                    SelectionHeadRecord.project_id == project_id,
                    SelectionHeadRecord.status == "SEALED",
                    SelectionHeadRecord.current_revision.is_not(None),
                )
            )
            if head is None:
                raise PersistenceError(
                    "projection selection head is not sealed"
                )
            selection_revision = self.session.scalar(
                select(SelectionRevisionRecord).where(
                    SelectionRevisionRecord.selection_head_id == head.id,
                    SelectionRevisionRecord.project_id == project_id,
                    SelectionRevisionRecord.revision == head.current_revision,
                )
            )
            if (
                selection_revision is None
                or not _selection_revision_matches_attempt(
                    selection_revision, selected
                )
                or not _selection_revision_allows_projection_status(
                    selection_revision, status
                )
            ):
                raise PersistenceError(
                    "projection selected attempt is not the current selection"
                )
        elif status in {
            "selected_clean",
            "selected_with_qc_exception",
            "ready_for_assembly",
            "assembled",
            "delivered",
        }:
            raise InvalidState("selected projection state requires an H3 attempt")
        normalized = _json_object(payload)
        existing = self.session.scalar(
            select(VideoJobSequenceProjectionRecord).where(
                VideoJobSequenceProjectionRecord.video_job_projection_id
                == video_job_projection_id,
                VideoJobSequenceProjectionRecord.project_id == project_id,
                VideoJobSequenceProjectionRecord.sequence_revision_id
                == sequence_revision_id,
            )
        )
        if existing is None:
            if expected_state_version != 0:
                raise ConcurrentStateConflict(
                    "video job sequence projection does not exist at the "
                    "expected version"
                )
            row = VideoJobSequenceProjectionRecord(
                id=projection_id or uuid4(),
                project_id=project_id,
                video_job_projection_id=video_job_projection_id,
                sequence_revision_id=sequence_revision_id,
                ordinal=ordinal,
                status=status,
                selected_attempt_id=selected_attempt_id,
                payload=normalized,
                state_version=0,
            )
            self.session.add(row)
            self.session.flush()
            return Stored(row, True)
        if existing.state_version != expected_state_version:
            raise ConcurrentStateConflict(
                "video job sequence projection changed concurrently"
            )
        if (
            existing.status == status
            and existing.selected_attempt_id == selected_attempt_id
            and existing.payload == normalized
        ):
            _guard_projection_version(
                self.session,
                project_id=project_id,
                projection_id=existing.id,
                expected_state_version=expected_state_version,
            )
            self.session.refresh(existing)
            return Stored(existing, False)
        changed = self.session.execute(
            update(VideoJobSequenceProjectionRecord)
            .where(
                VideoJobSequenceProjectionRecord.id == existing.id,
                VideoJobSequenceProjectionRecord.project_id == project_id,
                VideoJobSequenceProjectionRecord.state_version
                == expected_state_version,
            )
            .values(
                status=status,
                selected_attempt_id=selected_attempt_id,
                payload=normalized,
                state_version=expected_state_version + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict(
                "video job sequence projection changed concurrently"
            )
        self.session.refresh(existing)
        return Stored(existing, False)

    def load_h3_product_authority(
        self,
        project_id: UUID,
        episode_revision_id: UUID,
    ) -> dict[str, Any]:
        episode = self.session.scalar(
            select(EpisodeGenerationIRRevisionRecord).where(
                EpisodeGenerationIRRevisionRecord.id == episode_revision_id,
                EpisodeGenerationIRRevisionRecord.project_id == project_id,
            )
        )
        if episode is None:
            raise PersistenceError("episode generation IR is unavailable")
        episode_authority = EpisodeGenerationIRV1.model_validate(episode.payload)
        sequences = self.session.scalars(
            select(H3SequenceRevisionRecord)
            .where(
                H3SequenceRevisionRecord.project_id == project_id,
                H3SequenceRevisionRecord.episode_revision_id
                == episode_revision_id,
            )
            .order_by(H3SequenceRevisionRecord.ordinal)
        ).all()
        if tuple(row.sequence_id for row in sequences) != tuple(
            item.sequence_id for item in episode_authority.sequence_plans
        ):
            raise PersistenceError("episode sequence authority is incomplete")
        reference_ids = set(episode_authority.reference_set_revision_ids)
        references = self.session.scalars(
            select(CharacterReferenceSetRevisionRecord).where(
                CharacterReferenceSetRevisionRecord.project_id == project_id,
                CharacterReferenceSetRevisionRecord.id.in_(reference_ids),
            )
        ).all()
        if {row.id for row in references} != reference_ids:
            raise PersistenceError("episode character references are incomplete")
        stored_references = {
            row.id: CharacterReferenceSetV1.model_validate(row.payload)
            for row in references
        }
        for plan in episode_authority.sequence_plans:
            for binding in plan.reference_bindings:
                stored = stored_references.get(
                    binding.reference_set.reference_set_revision_id
                )
                if stored != binding.reference_set:
                    raise PersistenceError(
                        "episode embedded character reference does not match storage"
                    )
        final_sequences: list[dict[str, Any]] = []
        for sequence in sequences:
            attempts = self.get_h3_attempts(project_id, sequence.id)
            if tuple(row.attempt_ordinal for row in attempts) not in ((0,), (0, 1)):
                raise PersistenceError("H3 runtime attempt authority is incomplete")
            head = self.session.scalar(
                select(SelectionHeadRecord).where(
                    SelectionHeadRecord.id == sequence.selection_head_id,
                    SelectionHeadRecord.project_id == project_id,
                )
            )
            if (
                head is None
                or head.status != "SEALED"
                or head.current_revision is None
            ):
                raise PersistenceError("H3 selection head is not sealed")
            revision = self.session.scalar(
                select(SelectionRevisionRecord).where(
                    SelectionRevisionRecord.selection_head_id == head.id,
                    SelectionRevisionRecord.project_id == project_id,
                    SelectionRevisionRecord.revision == head.current_revision,
                )
            )
            if revision is None:
                raise PersistenceError("active H3 selection revision is missing")
            selection = H3AttemptSelectionV1.model_validate(revision.payload)
            selected = next(
                (
                    row
                    for row in attempts
                    if row.attempt_ordinal == selection.selected_attempt_ordinal
                ),
                None,
            )
            if (
                selected is None
                or not _selection_revision_matches_attempt(revision, selected)
                or not _selection_revision_allows_projection_status(
                    revision,
                    (
                        "selected_clean"
                        if selection.selected_cleanly
                        else "selected_with_qc_exception"
                    ),
                )
            ):
                raise PersistenceError(
                    "active H3 selection does not match the selected attempt"
                )
            final = H3SequenceV1.model_validate(
                {
                    "plan": _json_object(sequence.plan_payload),
                    "prompt_digest": sequence.prompt_digest,
                    "workflow_digest": sequence.workflow_digest,
                    "initial_attempt": _json_object(
                        attempts[0].source_lineage_payload
                    ),
                    "repair_attempt": (
                        None
                        if len(attempts) == 1
                        else _json_object(attempts[1].source_lineage_payload)
                    ),
                    "selection_policy_revision": selection.qc_policy_revision,
                    "selection": selection.model_dump(mode="json"),
                    "state": "delivered",
                }
            )
            final_sequences.append(final.model_dump(mode="json"))
        return {
            "episode": _json_object(episode.payload),
            "final_sequences": final_sequences,
        }

    def load_h3_assembly_authority(
        self,
        project_id: UUID,
        workflow_run_id: UUID,
    ) -> tuple[UUID, tuple[H3SelectedSegment, ...]]:
        """Load the sealed, digest-bound media authority for final assembly."""

        if type(project_id) is not UUID or type(workflow_run_id) is not UUID:
            raise ValueError("H3 assembly authority identity is invalid")
        heads = tuple(
            self.session.scalars(
                select(SelectionHeadRecord)
                .where(
                    SelectionHeadRecord.project_id == project_id,
                    SelectionHeadRecord.workflow_run_id == workflow_run_id,
                    SelectionHeadRecord.selection_key.like("h3.sequence.%"),
                    SelectionHeadRecord.status == "SEALED",
                    SelectionHeadRecord.current_revision.is_not(None),
                )
                .order_by(SelectionHeadRecord.selection_key)
            ).all()
        )
        if not heads:
            raise PersistenceError("H3 assembly has no sealed sequence selections")
        head_ids = tuple(head.id for head in heads)
        sequences = tuple(
            self.session.scalars(
                select(H3SequenceRevisionRecord)
                .where(
                    H3SequenceRevisionRecord.project_id == project_id,
                    H3SequenceRevisionRecord.selection_head_id.in_(head_ids),
                )
                .order_by(H3SequenceRevisionRecord.ordinal)
            ).all()
        )
        expected_ordinals = tuple(range(1, len(heads) + 1))
        if (
            len(sequences) != len(heads)
            or tuple(sequence.ordinal for sequence in sequences)
            != expected_ordinals
            or len({sequence.episode_revision_id for sequence in sequences}) != 1
            or len({sequence.id for sequence in sequences}) != len(sequences)
        ):
            raise PersistenceError("H3 assembly sequence authority is incomplete")
        heads_by_id = {head.id: head for head in heads}
        if len(heads_by_id) != len(heads):
            raise PersistenceError("H3 assembly selection heads are not unique")

        selected_segments: list[H3SelectedSegment] = []
        for sequence in sequences:
            head = heads_by_id.get(sequence.selection_head_id)
            expected_key = f"h3.sequence.{sequence.ordinal:03d}"
            if (
                head is None
                or head.project_id != project_id
                or head.workflow_run_id != workflow_run_id
                or head.selection_key != expected_key
                or head.status != "SEALED"
                or type(head.current_revision) is not int
                or head.current_revision <= 0
            ):
                raise PersistenceError(
                    "H3 assembly selection head does not match its sequence"
                )
            revision = self.session.scalar(
                select(SelectionRevisionRecord).where(
                    SelectionRevisionRecord.selection_head_id == head.id,
                    SelectionRevisionRecord.project_id == project_id,
                    SelectionRevisionRecord.revision == head.current_revision,
                )
            )
            if revision is None or not isinstance(revision.payload, Mapping):
                raise PersistenceError("H3 assembly selection revision is unavailable")
            selection_payload = _json_object(revision.payload)
            selection_payload_digest = canonical_json_digest(selection_payload)
            if revision.payload_digest != selection_payload_digest:
                raise PersistenceError("H3 assembly selection payload digest mismatch")
            try:
                selection = H3AttemptSelectionV1.model_validate(selection_payload)
            except (TypeError, ValueError) as exc:
                raise PersistenceError("H3 assembly selection payload is invalid") from exc
            expected_decision = (
                "SELECTED" if selection.selected_cleanly else "DEGRADED_ACCEPTED"
            )
            if (
                selection.sequence_id != sequence.sequence_id
                or revision.decision != expected_decision
                or revision.selection_head_id != head.id
            ):
                raise PersistenceError("H3 assembly selection binding is invalid")

            attempt = self.session.scalar(
                select(H3RuntimeAttemptRecord).where(
                    H3RuntimeAttemptRecord.project_id == project_id,
                    H3RuntimeAttemptRecord.sequence_revision_id == sequence.id,
                    H3RuntimeAttemptRecord.attempt_ordinal
                    == selection.selected_attempt_ordinal,
                )
            )
            if attempt is None or not _selection_revision_matches_attempt(
                revision, attempt
            ):
                raise PersistenceError("H3 assembly selected attempt is unavailable")
            if not isinstance(attempt.source_lineage_payload, Mapping):
                raise PersistenceError("H3 assembly source lineage is unavailable")
            lineage_payload = _json_object(attempt.source_lineage_payload)
            source_lineage_digest = canonical_json_digest(lineage_payload)
            if attempt.source_lineage_digest != source_lineage_digest:
                raise PersistenceError("H3 assembly source lineage digest mismatch")
            try:
                source_lineage = H3SourceLineageV1.model_validate(lineage_payload)
            except (TypeError, ValueError) as exc:
                raise PersistenceError("H3 assembly source lineage is invalid") from exc
            if (
                source_lineage.attempt_ordinal != selection.selected_attempt_ordinal
                or source_lineage.artifact_digest != attempt.artifact_digest
                or str(attempt.qc_evaluation_id)
                not in source_lineage.qc_evidence_ids
            ):
                raise PersistenceError("H3 assembly source lineage binding is invalid")

            evaluation = self.session.scalar(
                select(QCEvaluationFactRecord).where(
                    QCEvaluationFactRecord.id == attempt.qc_evaluation_id,
                    QCEvaluationFactRecord.project_id == project_id,
                    QCEvaluationFactRecord.workflow_run_id == workflow_run_id,
                    QCEvaluationFactRecord.artifact_id == attempt.artifact_id,
                    QCEvaluationFactRecord.artifact_digest == attempt.artifact_digest,
                    QCEvaluationFactRecord.gate_key == attempt.qc_gate_key,
                )
            )
            evaluation_digest = getattr(evaluation, "evaluation_digest", None)
            if (
                evaluation is None
                or evaluation.id != attempt.qc_evaluation_id
                or evaluation.project_id != project_id
                or evaluation.workflow_run_id != workflow_run_id
                or evaluation.artifact_id != attempt.artifact_id
                or evaluation.artifact_digest != attempt.artifact_digest
                or evaluation.gate_key != attempt.qc_gate_key
                or type(evaluation_digest) is not str
                or len(evaluation_digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in evaluation_digest
                )
            ):
                raise PersistenceError("H3 assembly QC authority is invalid")

            artifact = self.session.scalar(
                select(ArtifactRecordRow).where(
                    ArtifactRecordRow.id == attempt.artifact_id,
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.operation_run_id == attempt.operation_run_id,
                    ArtifactRecordRow.operation_attempt_id
                    == attempt.operation_attempt_id,
                    ArtifactRecordRow.content_digest == attempt.artifact_digest,
                    ArtifactRecordRow.status == "COMMITTED",
                )
            )
            expected_role = (
                f"h3.sequence.{sequence.ordinal:03d}.attempt."
                f"{selection.selected_attempt_ordinal}.video"
            )
            if (
                artifact is None
                or artifact.mime_type != "video/mp4"
                or artifact.logical_role != expected_role
                or type(artifact.byte_size) is not int
                or artifact.byte_size <= 0
                or artifact.content_digest != source_lineage.artifact_digest
            ):
                raise PersistenceError("H3 assembly media artifact is invalid")

            authority_fields: dict[str, Any] = {
                "schema_version": "h3.persisted-selection-authority.v1",
                "ordinal": sequence.ordinal,
                "sequence_id": sequence.sequence_id,
                "sequence_revision_id": sequence.id,
                "selected_attempt_id": attempt.operation_attempt_id,
                "artifact_id": attempt.artifact_id,
                "sequence_plan_digest": sequence.plan_digest,
                "selection_revision_id": revision.id,
                "selection_payload_digest": selection_payload_digest,
                "source_lineage_digest": source_lineage_digest,
                "qc_evaluation_id": evaluation.id,
                "qc_evaluation_digest": evaluation_digest,
                "selection": selection,
                "source_lineage": source_lineage,
            }
            authority_payload = {
                **{
                    key: str(value) if isinstance(value, UUID) else value
                    for key, value in authority_fields.items()
                    if key not in {"selection", "source_lineage"}
                },
                "selection": selection.model_dump(mode="json"),
                "source_lineage": source_lineage.model_dump(mode="json"),
            }
            try:
                selected_segments.append(
                    H3SelectedSegment(
                        **authority_fields,
                        authority_digest=canonical_json_digest(authority_payload),
                    )
                )
            except H3AssemblyError as exc:
                raise PersistenceError(
                    "H3 assembly selected segment authority is invalid"
                ) from exc
        return sequences[0].episode_revision_id, tuple(selected_segments)

    def store_h3_product_delivery(
        self,
        project_id: UUID,
        workflow_run_id: UUID,
        video_job_projection_id: UUID,
        delivery: H3DeliveryV1 | Mapping[str, Any],
        *,
        created_by_actor: str,
    ) -> Stored:
        if (
            not isinstance(project_id, UUID)
            or not isinstance(workflow_run_id, UUID)
            or not isinstance(video_job_projection_id, UUID)
            or not isinstance(created_by_actor, str)
            or not created_by_actor.strip()
            or len(created_by_actor) > 100
        ):
            raise ValueError("H3 delivery persistence identity is invalid")
        delivery_authority = H3DeliveryV1.model_validate(delivery)
        job = self.session.scalar(
            select(VideoJobProjectionRecord).where(
                VideoJobProjectionRecord.id == video_job_projection_id,
                VideoJobProjectionRecord.project_id == project_id,
            )
        )
        if (
            job is None
            or job.payload.get("workflowRunId") != str(workflow_run_id)
        ):
            raise PersistenceError("H3 delivery video job binding is unavailable")
        stem = self.load_h3_product_authority(
            project_id,
            delivery_authority.episode_revision_id,
        )
        authority = {
            "contract_versions": dict(H3_PRODUCT_CONTRACT_VERSIONS),
            "episode": stem["episode"],
            "final_sequences": stem["final_sequences"],
            "delivery": delivery_authority.model_dump(mode="json"),
        }

        selected_sources: list[tuple[str, int, str]] = []
        for final_payload in authority["final_sequences"]:
            final = H3SequenceV1.model_validate(final_payload)
            selected_ordinal = final.selection.selected_attempt_ordinal
            selected_lineage = (
                final.initial_attempt
                if selected_ordinal == 0
                else final.repair_attempt
            )
            if selected_lineage is None:
                raise PersistenceError("H3 delivery selected lineage is unavailable")
            selected_sources.append(
                (
                    str(final.plan.sequence_id),
                    selected_ordinal,
                    selected_lineage.artifact_digest,
                )
            )
        manifest_sources = [
            (
                str(source.sequence_id),
                source.selected_attempt_ordinal,
                source.source_artifact_digest,
            )
            for source in delivery_authority.assembly_manifest.sequence_sources
        ]
        if (
            manifest_sources != selected_sources
            or delivery_authority.episode_revision_id
            != UUID(str(authority["episode"]["episode_revision_id"]))
        ):
            raise PersistenceError(
                "H3 delivery assembly does not match selected sequence authority"
            )

        expected_assets: dict[UUID, tuple[str, str | None]] = {}
        for plan in EpisodeGenerationIRV1.model_validate(
            authority["episode"]
        ).sequence_plans:
            for binding in plan.reference_bindings:
                for view in binding.reference_set.views:
                    expected_assets[view.asset_id] = (
                        "reference",
                        view.image_digest,
                    )
        for asset_id in (
            delivery_authority.assembly_manifest.playback_asset_id,
            delivery_authority.assembly_manifest.download_asset_id,
        ):
            previous = expected_assets.setdefault(asset_id, ("video", None))
            if previous != ("video", None):
                raise PersistenceError("H3 delivery asset roles conflict")
        artifact_rows = self.session.scalars(
            select(ArtifactRecordRow).where(
                ArtifactRecordRow.project_id == project_id,
                ArtifactRecordRow.id.in_(tuple(expected_assets)),
                ArtifactRecordRow.status == "COMMITTED",
            )
        ).all()
        artifacts = {row.id: row for row in artifact_rows}
        if set(artifacts) != set(expected_assets):
            raise PersistenceError("H3 delivery artifacts are incomplete")
        asset_authorities: dict[str, dict[str, Any]] = {}
        for asset_id, (kind, expected_digest) in expected_assets.items():
            artifact = artifacts[asset_id]
            if kind == "reference":
                valid = (
                    artifact.content_digest == expected_digest
                    and artifact.mime_type
                    in {"image/jpeg", "image/png", "image/webp"}
                    and artifact.logical_role.startswith("character.reference.")
                )
            else:
                valid = (
                    artifact.mime_type == "video/mp4"
                    and artifact.logical_role == "final_episode"
                )
            if not valid or type(artifact.byte_size) is not int or artifact.byte_size <= 0:
                raise PersistenceError("H3 delivery artifact authority is invalid")
            asset_authorities[str(asset_id)] = {
                "owner": "drama_factory",
                "artifact_id": str(asset_id),
                "artifact_digest": artifact.content_digest,
                "byte_size": artifact.byte_size,
                "mime_type": artifact.mime_type,
                "logical_role": artifact.logical_role,
            }

        authority_digest = canonical_json_digest(authority)
        payload = {
            "schema_version": "shidu.h3-product-authority.v1",
            "workflow_run_id": str(workflow_run_id),
            "video_job_projection_id": str(video_job_projection_id),
            "authority": authority,
            "asset_authorities": asset_authorities,
        }
        record_id = uuid5(
            NAMESPACE_URL,
            (
                f"shidu-h3-delivery:{project_id}:{workflow_run_id}:"
                f"{video_job_projection_id}:{authority_digest}"
            ),
        )
        replay = self.session.get(DeliveryRevisionRecord, record_id)
        if replay is not None:
            if (
                replay.project_id != project_id
                or replay.digest != authority_digest
                or replay.payload != payload
                or replay.created_by_actor != created_by_actor
            ):
                raise IdempotencyConflict("H3 delivery replay conflicts")
            return Stored(replay, False)
        revision = self.session.scalar(
            select(func.max(DeliveryRevisionRecord.revision)).where(
                DeliveryRevisionRecord.project_id == project_id
            )
        ) or 0
        record = DeliveryRevisionRecord(
            id=record_id,
            project_id=project_id,
            revision=revision + 1,
            digest=authority_digest,
            created_by_actor=created_by_actor,
            payload=_json_object(payload),
        )
        self.session.add(record)
        self.session.flush()
        return Stored(record, True)

    def _command_replay(
        self,
        model: type[Any],
        project_id: UUID,
        command_idempotency_key: str,
    ) -> Any | None:
        return self.session.scalar(
            select(model).where(
                model.project_id == project_id,
                model.command_idempotency_key == command_idempotency_key,
            )
        )

    def _committed_artifact(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        digest: str,
        operation_run_id: UUID | None = None,
        operation_attempt_id: UUID | None = None,
    ) -> ArtifactRecordRow:
        self._require_digest(digest, "artifact digest")
        conditions = [
            ArtifactRecordRow.id == artifact_id,
            ArtifactRecordRow.project_id == project_id,
            ArtifactRecordRow.content_digest == digest,
            ArtifactRecordRow.status == "COMMITTED",
        ]
        if operation_run_id is not None:
            conditions.append(ArtifactRecordRow.operation_run_id == operation_run_id)
        if operation_attempt_id is not None:
            conditions.append(
                ArtifactRecordRow.operation_attempt_id == operation_attempt_id
            )
        artifact = self.session.scalar(select(ArtifactRecordRow).where(*conditions))
        if artifact is None:
            raise PersistenceError("committed project artifact is unavailable")
        return artifact

    @staticmethod
    def _require_digest(value: str | None, label: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        return value


__all__ = ["H3Repository"]
