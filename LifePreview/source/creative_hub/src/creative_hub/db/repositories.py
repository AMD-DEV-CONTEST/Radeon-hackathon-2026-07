from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import (
    ArtifactRecordRow,
    BudgetAccountRecord,
    BudgetLedgerEntryRecord,
    BudgetReservationRecord,
    OperationAttemptEventRecord,
    OperationAttemptRecord,
    OperationAttemptStateRecord,
    OperationRunRecord,
    ProjectRecord,
    SelectionHeadRecord,
    SelectionRevisionRecord,
    WorkflowDefinitionRecord,
    WorkflowDefinitionRevisionRecord,
    WorkflowRunRecord,
)


class PersistenceError(RuntimeError):
    pass


class IdempotencyConflict(PersistenceError):
    pass


class ConcurrentStateConflict(PersistenceError):
    pass


class InvalidState(PersistenceError):
    pass


class BudgetExceeded(PersistenceError):
    pass


@dataclass(frozen=True)
class Stored:
    value: Any
    created: bool


@dataclass(frozen=True)
class WorkflowStored:
    definition: WorkflowDefinitionRecord
    revision: WorkflowDefinitionRevisionRecord
    created: bool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _locked(statement: Select[Any]) -> Select[Any]:
    return statement.with_for_update()


def _require_same(
    condition: bool,
    *,
    key: str,
    entity: str,
) -> None:
    if not condition:
        raise IdempotencyConflict(
            f"idempotency key {key!r} already belongs to different {entity}"
        )


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_project(
        self,
        *,
        project_key: str,
        title: str,
        config: dict[str, Any] | None = None,
        project_id: UUID | None = None,
        template_key: str = "general_video",
        template_version: int = 1,
    ) -> Stored:
        payload = config or {}
        digest = canonical_json_digest(payload)
        existing = self.session.scalar(
            select(ProjectRecord).where(ProjectRecord.project_key == project_key)
        )
        if existing is not None:
            _require_same(
                existing.title == title
                and existing.config_digest == digest,
                key=project_key,
                entity="project",
            )
            return Stored(existing, False)
        if self.session.get_bind().dialect.name == "postgresql":
            inserted_id = self.session.scalar(
                postgresql_insert(ProjectRecord)
                .values(
                    id=project_id or uuid4(),
                    project_key=project_key,
                    title=title,
                    config=payload,
                    config_digest=digest,
                    template_key=template_key,
                    template_version=template_version,
                )
                .on_conflict_do_nothing(index_elements=["project_key"])
                .returning(ProjectRecord.id)
            )
            if inserted_id is not None:
                record = self.session.get(ProjectRecord, inserted_id)
                if record is None:
                    raise PersistenceError(
                        "inserted project could not be loaded"
                    )
                return Stored(record, True)
            existing = self.session.scalar(
                select(ProjectRecord).where(
                    ProjectRecord.project_key == project_key
                )
            )
            if existing is None:
                raise PersistenceError(
                    "conflicting project could not be loaded"
                )
            _require_same(
                existing.title == title
                and existing.config_digest == digest,
                key=project_key,
                entity="project",
            )
            return Stored(existing, False)
        record = ProjectRecord(
            id=project_id or uuid4(),
            project_key=project_key,
            title=title,
            config=payload,
            config_digest=digest,
            template_key=template_key,
            template_version=template_version,
        )
        self.session.add(record)
        self.session.flush()
        return Stored(record, True)

    def create_workflow_definition(
        self,
        *,
        project_id: UUID,
        workflow_key: str,
        name: str,
        definition: dict[str, Any],
        schema_revision: str,
        command_idempotency_key: str,
        created_by_actor: str,
        expected_revision: int | None = None,
        workflow_definition_id: UUID | None = None,
        workflow_revision_id: UUID | None = None,
    ) -> WorkflowStored:
        digest = canonical_json_digest(
            {
                "definition": definition,
                "schema_revision": schema_revision,
            }
        )
        replay = self.session.scalar(
            select(WorkflowDefinitionRevisionRecord).where(
                WorkflowDefinitionRevisionRecord.project_id == project_id,
                WorkflowDefinitionRevisionRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        if replay is not None:
            workflow = self.session.get(
                WorkflowDefinitionRecord, replay.workflow_definition_id
            )
            _require_same(
                workflow is not None
                and workflow.workflow_key == workflow_key
                and workflow.name == name
                and replay.definition_digest == digest
                and replay.schema_revision == schema_revision,
                key=command_idempotency_key,
                entity="workflow definition revision",
            )
            return WorkflowStored(workflow, replay, False)

        if self.session.get_bind().dialect.name == "postgresql":
            inserted_id = self.session.scalar(
                postgresql_insert(WorkflowDefinitionRecord)
                .values(
                    id=workflow_definition_id or uuid4(),
                    project_id=project_id,
                    workflow_key=workflow_key,
                    name=name,
                    current_revision=1,
                )
                .on_conflict_do_nothing(
                    index_elements=["project_id", "workflow_key"]
                )
                .returning(WorkflowDefinitionRecord.id)
            )
            if inserted_id is not None:
                workflow = self.session.get(
                    WorkflowDefinitionRecord, inserted_id
                )
                if workflow is None:
                    raise PersistenceError(
                        "inserted workflow definition could not be loaded"
                    )
                revision_number = 1
            else:
                workflow = self.session.scalar(
                    _locked(
                        select(WorkflowDefinitionRecord).where(
                            WorkflowDefinitionRecord.project_id == project_id,
                            WorkflowDefinitionRecord.workflow_key
                            == workflow_key,
                        )
                    )
                )
                if workflow is None:
                    raise PersistenceError(
                        "conflicting workflow definition could not be loaded"
                    )
                replay = self.session.scalar(
                    select(WorkflowDefinitionRevisionRecord).where(
                        WorkflowDefinitionRevisionRecord.project_id
                        == project_id,
                        WorkflowDefinitionRevisionRecord.command_idempotency_key
                        == command_idempotency_key,
                    )
                )
                if replay is not None:
                    _require_same(
                        replay.workflow_definition_id == workflow.id
                        and workflow.name == name
                        and replay.definition_digest == digest
                        and replay.schema_revision == schema_revision,
                        key=command_idempotency_key,
                        entity="workflow definition revision",
                    )
                    return WorkflowStored(workflow, replay, False)
                if workflow.name != name:
                    raise IdempotencyConflict(
                        f"workflow key {workflow_key!r} already has a "
                        "different name"
                    )
                if expected_revision is not None and (
                    workflow.current_revision != expected_revision
                ):
                    raise ConcurrentStateConflict(
                        f"workflow revision is {workflow.current_revision}, "
                        f"expected {expected_revision}"
                    )
                old_revision = workflow.current_revision
                revision_number = old_revision + 1
                workflow.current_revision = revision_number
                workflow.updated_at = _utcnow()
        else:
            workflow = self.session.scalar(
                _locked(
                    select(WorkflowDefinitionRecord).where(
                        WorkflowDefinitionRecord.project_id == project_id,
                        WorkflowDefinitionRecord.workflow_key == workflow_key,
                    )
                )
            )
            if workflow is None:
                if expected_revision not in (None, 0):
                    raise ConcurrentStateConflict(
                        f"workflow revision is 0, expected {expected_revision}"
                    )
                workflow = WorkflowDefinitionRecord(
                    id=workflow_definition_id or uuid4(),
                    project_id=project_id,
                    workflow_key=workflow_key,
                    name=name,
                    current_revision=1,
                )
                revision_number = 1
                self.session.add(workflow)
            else:
                if workflow.name != name:
                    raise IdempotencyConflict(
                        f"workflow key {workflow_key!r} already has a "
                        "different name"
                    )
                if expected_revision is not None and (
                    workflow.current_revision != expected_revision
                ):
                    raise ConcurrentStateConflict(
                        f"workflow revision is {workflow.current_revision}, "
                        f"expected {expected_revision}"
                    )
                old_revision = workflow.current_revision
                revision_number = old_revision + 1
                updated = self.session.execute(
                    update(WorkflowDefinitionRecord)
                    .where(
                        WorkflowDefinitionRecord.id == workflow.id,
                        WorkflowDefinitionRecord.project_id == project_id,
                        WorkflowDefinitionRecord.current_revision
                        == old_revision,
                    )
                    .values(
                        current_revision=revision_number,
                        updated_at=_utcnow(),
                    )
                )
                if updated.rowcount != 1:
                    raise ConcurrentStateConflict(
                        "workflow definition changed concurrently"
                    )
                workflow.current_revision = revision_number

        revision = WorkflowDefinitionRevisionRecord(
            id=workflow_revision_id or uuid4(),
            project_id=project_id,
            workflow_definition_id=workflow.id,
            revision=revision_number,
            command_idempotency_key=command_idempotency_key,
            schema_revision=schema_revision,
            definition=definition,
            definition_digest=digest,
            created_by_actor=created_by_actor,
        )
        self.session.add(revision)
        self.session.flush()
        return WorkflowStored(workflow, revision, True)

    create_workflow = create_workflow_definition

    def create_workflow_run(
        self,
        *,
        project_id: UUID,
        workflow_definition_id: UUID,
        workflow_revision_id: UUID,
        command_idempotency_key: str,
        input_payload: dict[str, Any],
        policy_snapshot: dict[str, Any],
        trace_id: UUID | None = None,
        workflow_run_id: UUID | None = None,
        parent_workflow_run_id: UUID | None = None,
        source_repair_proposal_id: UUID | None = None,
    ) -> Stored:
        input_digest = canonical_json_digest(input_payload)
        policy_digest = canonical_json_digest(policy_snapshot)
        replay = self.session.scalar(
            select(WorkflowRunRecord).where(
                WorkflowRunRecord.project_id == project_id,
                WorkflowRunRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        if replay is not None:
            _require_same(
                replay.workflow_definition_id == workflow_definition_id
                and replay.workflow_revision_id == workflow_revision_id
                and replay.input_digest == input_digest
                and replay.policy_digest == policy_digest
                and replay.parent_workflow_run_id == parent_workflow_run_id
                and replay.source_repair_proposal_id
                == source_repair_proposal_id,
                key=command_idempotency_key,
                entity="workflow run",
            )
            return Stored(replay, False)
        if self.session.get_bind().dialect.name == "postgresql":
            identifier = workflow_run_id or uuid4()
            inserted_id = self.session.scalar(
                postgresql_insert(WorkflowRunRecord)
                .values(
                    id=identifier,
                    project_id=project_id,
                    workflow_definition_id=workflow_definition_id,
                    workflow_revision_id=workflow_revision_id,
                    parent_workflow_run_id=parent_workflow_run_id,
                    source_repair_proposal_id=source_repair_proposal_id,
                    command_idempotency_key=command_idempotency_key,
                    input_payload=input_payload,
                    input_digest=input_digest,
                    policy_snapshot=policy_snapshot,
                    policy_digest=policy_digest,
                    trace_id=trace_id or uuid4(),
                )
                .on_conflict_do_nothing(
                    index_elements=["project_id", "command_idempotency_key"]
                )
                .returning(WorkflowRunRecord.id)
            )
            if inserted_id is not None:
                record = self.session.get(WorkflowRunRecord, inserted_id)
                if record is None:
                    raise PersistenceError(
                        "inserted workflow run could not be loaded"
                    )
                return Stored(record, True)
            replay = self.session.scalar(
                select(WorkflowRunRecord).where(
                    WorkflowRunRecord.project_id == project_id,
                    WorkflowRunRecord.command_idempotency_key
                    == command_idempotency_key,
                )
            )
            if replay is None:
                raise PersistenceError(
                    "conflicting workflow run could not be loaded"
                )
            _require_same(
                replay.workflow_definition_id == workflow_definition_id
                and replay.workflow_revision_id == workflow_revision_id
                and replay.input_digest == input_digest
                and replay.policy_digest == policy_digest
                and replay.parent_workflow_run_id == parent_workflow_run_id
                and replay.source_repair_proposal_id
                == source_repair_proposal_id,
                key=command_idempotency_key,
                entity="workflow run",
            )
            return Stored(replay, False)
        record = WorkflowRunRecord(
            id=workflow_run_id or uuid4(),
            project_id=project_id,
            workflow_definition_id=workflow_definition_id,
            workflow_revision_id=workflow_revision_id,
            parent_workflow_run_id=parent_workflow_run_id,
            source_repair_proposal_id=source_repair_proposal_id,
            command_idempotency_key=command_idempotency_key,
            input_payload=input_payload,
            input_digest=input_digest,
            policy_snapshot=policy_snapshot,
            policy_digest=policy_digest,
            trace_id=trace_id or uuid4(),
        )
        self.session.add(record)
        self.session.flush()
        return Stored(record, True)

    def compare_and_set_run(
        self,
        *,
        workflow_run_id: UUID,
        project_id: UUID,
        expected_state_version: int,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> WorkflowRunRecord:
        values: dict[str, Any] = {
            "status": status,
            "state_version": expected_state_version + 1,
            "updated_at": _utcnow(),
        }
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        result = self.session.execute(
            update(WorkflowRunRecord)
            .where(
                WorkflowRunRecord.id == workflow_run_id,
                WorkflowRunRecord.project_id == project_id,
                WorkflowRunRecord.state_version == expected_state_version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise ConcurrentStateConflict(
                "workflow run state_version changed concurrently"
            )
        self.session.flush()
        record = self.session.get(WorkflowRunRecord, workflow_run_id)
        if record is None:
            raise PersistenceError("workflow run disappeared after CAS")
        self.session.refresh(record)
        return record

    transition_workflow_run = compare_and_set_run


class OperationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_operation_run(
        self,
        *,
        project_id: UUID,
        workflow_run_id: UUID,
        node_key: str,
        op_type: str,
        op_version: str,
        command_idempotency_key: str,
        request_payload: dict[str, Any],
        parent_operation_run_id: UUID | None = None,
        operation_run_id: UUID | None = None,
    ) -> Stored:
        digest = canonical_json_digest(request_payload)
        replay = self.session.scalar(
            select(OperationRunRecord).where(
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        if replay is not None:
            _require_same(
                replay.workflow_run_id == workflow_run_id
                and replay.node_key == node_key
                and replay.op_type == op_type
                and replay.op_version == op_version
                and replay.operation_input_digest == digest
                and replay.parent_operation_run_id
                == parent_operation_run_id,
                key=command_idempotency_key,
                entity="operation run",
            )
            return Stored(replay, False)
        workflow_run = self.session.scalar(
            _locked(
                select(WorkflowRunRecord).where(
                    WorkflowRunRecord.id == workflow_run_id,
                    WorkflowRunRecord.project_id == project_id,
                )
            )
        )
        if workflow_run is None:
            raise PersistenceError("workflow run not found")
        replay = self.session.scalar(
            select(OperationRunRecord).where(
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        if replay is not None:
            _require_same(
                replay.workflow_run_id == workflow_run_id
                and replay.node_key == node_key
                and replay.op_type == op_type
                and replay.op_version == op_version
                and replay.operation_input_digest == digest
                and replay.parent_operation_run_id
                == parent_operation_run_id,
                key=command_idempotency_key,
                entity="operation run",
            )
            return Stored(replay, False)
        record = OperationRunRecord(
            id=operation_run_id or uuid4(),
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            node_key=node_key,
            op_type=op_type,
            op_version=op_version,
            command_idempotency_key=command_idempotency_key,
            request_payload=request_payload,
            operation_input_digest=digest,
            parent_operation_run_id=parent_operation_run_id,
        )
        self.session.add(record)
        self.session.flush()
        return Stored(record, True)

    def create_attempt(
        self,
        *,
        project_id: UUID,
        operation_run_id: UUID,
        attempt_number: int,
        fencing_token: int,
        worker_id: str,
        implementation_digest: str,
        request_payload: dict[str, Any],
        submission_nonce: UUID,
        provider_task_id: str | None = None,
        attempt_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> Stored:
        operation = self.session.scalar(
            _locked(
                select(OperationRunRecord).where(
                    OperationRunRecord.id == operation_run_id,
                    OperationRunRecord.project_id == project_id,
                )
            )
        )
        if operation is None:
            raise PersistenceError("operation run not found")
        if "expected_selection_version" in operation.request_payload:
            expected_selection_version = operation.request_payload[
                "expected_selection_version"
            ]
            attempt_selection_version = request_payload.get(
                "expected_selection_version"
            )
            if (
                type(expected_selection_version) is not int
                or type(attempt_selection_version) is not int
                or attempt_selection_version != expected_selection_version
            ):
                raise PersistenceError(
                    "repair attempt selection version does not match "
                    "the immutable operation run"
                )
        digest = canonical_json_digest(request_payload)
        replay = self.session.scalar(
            select(OperationAttemptRecord).where(
                OperationAttemptRecord.operation_run_id == operation_run_id,
                OperationAttemptRecord.attempt_number == attempt_number,
            )
        )
        if replay is not None:
            _require_same(
                replay.project_id == project_id
                and replay.fencing_token == fencing_token
                and replay.worker_id == worker_id
                and replay.implementation_digest == implementation_digest
                and replay.request_digest == digest
                and replay.submission_nonce == submission_nonce
                and replay.provider_task_id == provider_task_id,
                key=f"{operation_run_id}:{attempt_number}",
                entity="operation attempt",
            )
            return Stored(replay, False)
        replay = self.session.scalar(
            select(OperationAttemptRecord).where(
                OperationAttemptRecord.operation_run_id == operation_run_id,
                OperationAttemptRecord.attempt_number == attempt_number,
            )
        )
        if replay is not None:
            _require_same(
                replay.project_id == project_id
                and replay.fencing_token == fencing_token
                and replay.worker_id == worker_id
                and replay.implementation_digest == implementation_digest
                and replay.request_digest == digest
                and replay.submission_nonce == submission_nonce
                and replay.provider_task_id == provider_task_id,
                key=f"{operation_run_id}:{attempt_number}",
                entity="operation attempt",
            )
            return Stored(replay, False)
        attempt = OperationAttemptRecord(
            id=attempt_id or uuid4(),
            project_id=project_id,
            operation_run_id=operation_run_id,
            attempt_number=attempt_number,
            fencing_token=fencing_token,
            worker_id=worker_id,
            implementation_digest=implementation_digest,
            provider_task_id=provider_task_id,
            submission_nonce=submission_nonce,
            request_payload=request_payload,
            request_digest=digest,
        )
        self.session.add(attempt)
        self.session.flush()
        state = OperationAttemptStateRecord(
            attempt_id=attempt.id,
            project_id=project_id,
            operation_run_id=operation_run_id,
            status="PREPARED",
            stage="PREPARED",
            state_version=0,
        )
        event_data = {
            "fencing_token": fencing_token,
            "worker_id": worker_id,
        }
        event = OperationAttemptEventRecord(
            id=uuid4(),
            project_id=project_id,
            operation_run_id=operation_run_id,
            attempt_id=attempt.id,
            sequence=1,
            state_version=0,
            event_type="ATTEMPT_PREPARED",
            from_status=None,
            to_status="PREPARED",
            data=event_data,
            data_digest=canonical_json_digest(event_data),
            occurred_at=occurred_at or _utcnow(),
        )
        self.session.add_all((state, event))
        self.session.flush()
        return Stored(attempt, True)

    def compare_and_set_attempt_state(
        self,
        *,
        attempt_id: UUID,
        project_id: UUID,
        expected_state_version: int,
        status: str,
        stage: str,
        event_type: str,
        event_data: dict[str, Any] | None = None,
        provider_state: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        cost_micros: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        occurred_at: datetime | None = None,
    ) -> OperationAttemptStateRecord:
        state = self.session.scalar(
            select(OperationAttemptStateRecord).where(
                OperationAttemptStateRecord.attempt_id == attempt_id,
                OperationAttemptStateRecord.project_id == project_id,
            )
        )
        if state is None:
            raise PersistenceError("operation attempt state not found")
        previous = state.status
        new_version = expected_state_version + 1
        values: dict[str, Any] = {
            "status": status,
            "stage": stage,
            "state_version": new_version,
            "updated_at": _utcnow(),
        }
        optional = {
            "provider_state": provider_state,
            "metrics": metrics,
            "error": error,
            "duration_ms": duration_ms,
            "cost_micros": cost_micros,
            "started_at": started_at,
            "completed_at": completed_at,
        }
        values.update({key: value for key, value in optional.items() if value is not None})
        changed = self.session.execute(
            update(OperationAttemptStateRecord)
            .where(
                OperationAttemptStateRecord.attempt_id == attempt_id,
                OperationAttemptStateRecord.project_id == project_id,
                OperationAttemptStateRecord.state_version
                == expected_state_version,
            )
            .values(**values)
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict(
                "operation attempt state_version changed concurrently"
            )
        payload = event_data or {}
        self.session.add(
            OperationAttemptEventRecord(
                id=uuid4(),
                project_id=project_id,
                operation_run_id=state.operation_run_id,
                attempt_id=attempt_id,
                sequence=new_version + 1,
                state_version=new_version,
                event_type=event_type,
                from_status=previous,
                to_status=status,
                data=payload,
                data_digest=canonical_json_digest(payload),
                occurred_at=occurred_at or _utcnow(),
            )
        )
        self.session.flush()
        self.session.refresh(state)
        return state

    transition_attempt = compare_and_set_attempt_state

    def compare_and_set_operation_run(
        self,
        *,
        operation_run_id: UUID,
        project_id: UUID,
        expected_state_version: int,
        status: str,
    ) -> OperationRunRecord:
        changed = self.session.execute(
            update(OperationRunRecord)
            .where(
                OperationRunRecord.id == operation_run_id,
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.state_version == expected_state_version,
            )
            .values(
                status=status,
                state_version=expected_state_version + 1,
                updated_at=_utcnow(),
            )
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict(
                "operation run state_version changed concurrently"
            )
        record = self.session.get(OperationRunRecord, operation_run_id)
        if record is None:
            raise PersistenceError("operation run disappeared after CAS")
        self.session.refresh(record)
        return record

    def accept_attempt(
        self,
        *,
        operation_run_id: UUID,
        attempt_id: UUID,
        project_id: UUID,
        expected_state_version: int,
    ) -> OperationRunRecord:
        attempt = self.session.scalar(
            select(OperationAttemptRecord).where(
                OperationAttemptRecord.id == attempt_id,
                OperationAttemptRecord.operation_run_id == operation_run_id,
                OperationAttemptRecord.project_id == project_id,
            )
        )
        if attempt is None:
            raise PersistenceError("attempt does not belong to operation run")
        state = self.session.get(OperationAttemptStateRecord, attempt_id)
        if state is None or state.status != "SUCCEEDED":
            raise InvalidState("only a succeeded attempt can be accepted")
        current = self.session.get(OperationRunRecord, operation_run_id)
        if current is None or current.project_id != project_id:
            raise PersistenceError("operation run not found")
        if current.accepted_attempt_id is not None:
            if current.accepted_attempt_id == attempt_id:
                return current
            raise InvalidState("operation run already accepted another attempt")
        changed = self.session.execute(
            update(OperationRunRecord)
            .where(
                OperationRunRecord.id == operation_run_id,
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.state_version == expected_state_version,
                OperationRunRecord.accepted_attempt_id.is_(None),
            )
            .values(
                accepted_attempt_id=attempt.id,
                accepted_attempt_number=attempt.attempt_number,
                status="SUCCEEDED",
                state_version=expected_state_version + 1,
                updated_at=_utcnow(),
            )
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict(
                "operation run changed before attempt acceptance"
            )
        self.session.flush()
        self.session.refresh(current)
        return current


class SelectionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_head(
        self,
        *,
        project_id: UUID,
        workflow_run_id: UUID,
        selection_key: str,
        selection_head_id: UUID | None = None,
    ) -> Stored:
        existing = self.session.scalar(
            select(SelectionHeadRecord).where(
                SelectionHeadRecord.project_id == project_id,
                SelectionHeadRecord.workflow_run_id == workflow_run_id,
                SelectionHeadRecord.selection_key == selection_key,
            )
        )
        if existing is not None:
            return Stored(existing, False)
        head = SelectionHeadRecord(
            id=selection_head_id or uuid4(),
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            selection_key=selection_key,
            current_revision=None,
        )
        self.session.add(head)
        self.session.flush()
        return Stored(head, True)

    def compare_and_set(
        self,
        *,
        selection_head_id: UUID,
        project_id: UUID,
        expected_state_version: int,
        selected_operation_run_id: UUID,
        selected_attempt_id: UUID,
        artifact_id: UUID,
        artifact_digest: str,
        decision: str,
        command_idempotency_key: str,
        created_by_actor: str,
        payload: dict[str, Any],
        reason: str | None = None,
        seal: bool = False,
        selection_revision_id: UUID | None = None,
    ) -> Stored:
        payload_digest = canonical_json_digest(payload)
        replay = self.session.scalar(
            select(SelectionRevisionRecord).where(
                SelectionRevisionRecord.project_id == project_id,
                SelectionRevisionRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        if replay is not None:
            _require_same(
                replay.selection_head_id == selection_head_id
                and replay.selected_operation_run_id
                == selected_operation_run_id
                and replay.selected_attempt_id == selected_attempt_id
                and replay.artifact_id == artifact_id
                and replay.artifact_digest == artifact_digest
                and replay.decision == decision
                and replay.reason == reason
                and replay.created_by_actor == created_by_actor
                and replay.payload_digest == payload_digest,
                key=command_idempotency_key,
                entity="selection revision",
            )
            return Stored(replay, False)
        head = self.session.scalar(
            _locked(
                select(SelectionHeadRecord).where(
                    SelectionHeadRecord.id == selection_head_id,
                    SelectionHeadRecord.project_id == project_id,
                )
            )
        )
        if head is None:
            raise PersistenceError("selection head not found")
        if head.state_version != expected_state_version:
            raise ConcurrentStateConflict(
                "selection state_version changed concurrently"
            )
        if head.status == "SEALED":
            raise InvalidState("selection head is sealed")
        attempt = self.session.scalar(
            select(OperationAttemptRecord)
            .join(
                OperationRunRecord,
                OperationRunRecord.id
                == OperationAttemptRecord.operation_run_id,
            )
            .where(
                OperationAttemptRecord.id == selected_attempt_id,
                OperationAttemptRecord.operation_run_id
                == selected_operation_run_id,
                OperationAttemptRecord.project_id == project_id,
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.workflow_run_id == head.workflow_run_id,
            )
        )
        if attempt is None:
            raise PersistenceError(
                "selected attempt does not belong to the selection workflow"
            )
        attempt_state = self.session.scalar(
            select(OperationAttemptStateRecord)
            .where(
                OperationAttemptStateRecord.attempt_id == selected_attempt_id,
                OperationAttemptStateRecord.operation_run_id
                == selected_operation_run_id,
                OperationAttemptStateRecord.project_id == project_id,
                OperationAttemptStateRecord.status == "SUCCEEDED",
            )
            .with_for_update()
        )
        if attempt_state is None:
            raise InvalidState("selected attempt has not succeeded")
        artifact = self.session.scalar(
            select(ArtifactRecordRow)
            .where(
                ArtifactRecordRow.id == artifact_id,
                ArtifactRecordRow.project_id == project_id,
                ArtifactRecordRow.operation_run_id
                == selected_operation_run_id,
                ArtifactRecordRow.operation_attempt_id
                == selected_attempt_id,
                ArtifactRecordRow.content_digest == artifact_digest,
                ArtifactRecordRow.status == "COMMITTED",
            )
            .with_for_update()
        )
        if artifact is None:
            raise PersistenceError(
                "selection artifact is unavailable or does not match "
                "the successful attempt"
            )
        next_revision = (head.current_revision or 0) + 1
        changed = self.session.execute(
            update(SelectionHeadRecord)
            .where(
                SelectionHeadRecord.id == selection_head_id,
                SelectionHeadRecord.project_id == project_id,
                SelectionHeadRecord.state_version == expected_state_version,
                SelectionHeadRecord.status == "OPEN",
            )
            .values(
                current_revision=next_revision,
                state_version=expected_state_version + 1,
                status="SEALED" if seal else "OPEN",
                updated_at=_utcnow(),
            )
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict(
                "selection state_version changed concurrently"
            )
        revision = SelectionRevisionRecord(
            id=selection_revision_id or uuid4(),
            project_id=project_id,
            selection_head_id=selection_head_id,
            revision=next_revision,
            command_idempotency_key=command_idempotency_key,
            selected_operation_run_id=selected_operation_run_id,
            selected_attempt_id=selected_attempt_id,
            artifact_id=artifact_id,
            artifact_digest=artifact_digest,
            decision=decision,
            reason=reason,
            created_by_actor=created_by_actor,
            payload=payload,
            payload_digest=payload_digest,
        )
        self.session.add(revision)
        self.session.flush()
        return Stored(revision, True)

    commit = compare_and_set


class BudgetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_account(
        self,
        *,
        project_id: UUID,
        account_key: str,
        currency: str,
        limit_micros: int,
        account_id: UUID | None = None,
    ) -> Stored:
        existing = self.session.scalar(
            select(BudgetAccountRecord).where(
                BudgetAccountRecord.project_id == project_id,
                BudgetAccountRecord.account_key == account_key,
            )
        )
        if existing is not None:
            _require_same(
                existing.currency == currency.upper()
                and existing.limit_micros == limit_micros,
                key=account_key,
                entity="budget account",
            )
            return Stored(existing, False)
        account = BudgetAccountRecord(
            id=account_id or uuid4(),
            project_id=project_id,
            account_key=account_key,
            currency=currency.upper(),
            limit_micros=limit_micros,
        )
        self.session.add(account)
        self.session.flush()
        return Stored(account, True)

    def reserve(
        self,
        *,
        project_id: UUID,
        account_id: UUID,
        amount_micros: int,
        command_idempotency_key: str,
        operation_attempt_id: UUID | None = None,
        operation_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        reservation_id: UUID | None = None,
    ) -> Stored:
        if amount_micros <= 0:
            raise ValueError("amount_micros must be positive")
        ledger_metadata = metadata or {}
        metadata_digest = canonical_json_digest(ledger_metadata)
        replay = self.session.scalar(
            select(BudgetReservationRecord).where(
                BudgetReservationRecord.project_id == project_id,
                BudgetReservationRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        if replay is not None:
            self._validate_reservation_replay(
                replay,
                account_id=account_id,
                amount_micros=amount_micros,
                operation_attempt_id=operation_attempt_id,
                operation_run_id=operation_run_id,
                metadata_digest=metadata_digest,
            )
            return Stored(replay, False)
        account = self.session.scalar(
            _locked(
                select(BudgetAccountRecord).where(
                    BudgetAccountRecord.id == account_id,
                    BudgetAccountRecord.project_id == project_id,
                )
            )
        )
        if account is None:
            raise PersistenceError("budget account not found")
        replay = self.session.scalar(
            select(BudgetReservationRecord).where(
                BudgetReservationRecord.project_id == project_id,
                BudgetReservationRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        if replay is not None:
            self._validate_reservation_replay(
                replay,
                account_id=account_id,
                amount_micros=amount_micros,
                operation_attempt_id=operation_attempt_id,
                operation_run_id=operation_run_id,
                metadata_digest=metadata_digest,
            )
            return Stored(replay, False)
        if (
            account.reserved_micros
            + account.settled_micros
            + amount_micros
            > account.limit_micros
        ):
            raise BudgetExceeded("budget reservation exceeds account limit")
        new_reserved = account.reserved_micros + amount_micros
        new_version = account.state_version + 1
        changed = self.session.execute(
            update(BudgetAccountRecord)
            .where(
                BudgetAccountRecord.id == account_id,
                BudgetAccountRecord.project_id == project_id,
                BudgetAccountRecord.state_version == account.state_version,
            )
            .values(
                reserved_micros=new_reserved,
                state_version=new_version,
                updated_at=_utcnow(),
            )
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict("budget account changed concurrently")
        reservation = BudgetReservationRecord(
            id=reservation_id or uuid4(),
            project_id=project_id,
            account_id=account_id,
            operation_run_id=operation_run_id,
            operation_attempt_id=operation_attempt_id,
            command_idempotency_key=command_idempotency_key,
            amount_micros=amount_micros,
        )
        self.session.add(reservation)
        self.session.flush()
        self.session.add(
            BudgetLedgerEntryRecord(
                id=uuid4(),
                project_id=project_id,
                account_id=account_id,
                reservation_id=reservation.id,
                sequence=1,
                command_idempotency_key=command_idempotency_key,
                entry_type="RESERVE",
                reserved_delta_micros=amount_micros,
                settled_delta_micros=0,
                reserved_balance_micros=new_reserved,
                settled_balance_micros=account.settled_micros,
                metadata_payload=ledger_metadata,
                metadata_digest=metadata_digest,
            )
        )
        self.session.flush()
        return Stored(reservation, True)

    def release(
        self,
        *,
        reservation_id: UUID,
        project_id: UUID,
        command_idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> Stored:
        ledger_metadata = metadata or {}
        replay = self._ledger_replay(
            project_id,
            command_idempotency_key,
            reservation_id,
            "RELEASE",
            canonical_json_digest(ledger_metadata),
        )
        reservation = self._locked_reservation(reservation_id, project_id)
        if replay is not None:
            return Stored(reservation, False)
        if reservation.status == "RELEASED":
            return Stored(reservation, False)
        if reservation.status == "SETTLED":
            raise InvalidState("settled reservation cannot be released")
        account = self._locked_account(reservation.account_id, project_id)
        new_reserved = account.reserved_micros - reservation.amount_micros
        if new_reserved < 0:
            raise PersistenceError("budget reserved balance would become negative")
        self._update_account(
            account,
            reserved_micros=new_reserved,
            settled_micros=account.settled_micros,
        )
        self._update_reservation(
            reservation, status="RELEASED", settled_micros=None
        )
        self._add_ledger(
            reservation=reservation,
            account=account,
            entry_type="RELEASE",
            command_idempotency_key=command_idempotency_key,
            reserved_delta_micros=-reservation.amount_micros,
            settled_delta_micros=0,
            reserved_balance_micros=new_reserved,
            settled_balance_micros=account.settled_micros,
            metadata=ledger_metadata,
        )
        self.session.flush()
        self.session.refresh(reservation)
        return Stored(reservation, True)

    def settle(
        self,
        *,
        reservation_id: UUID,
        project_id: UUID,
        actual_micros: int,
        command_idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> Stored:
        if actual_micros < 0:
            raise ValueError("actual_micros must be nonnegative")
        caller_metadata = metadata or {}
        replay = self.session.scalar(
            select(BudgetLedgerEntryRecord).where(
                BudgetLedgerEntryRecord.project_id == project_id,
                BudgetLedgerEntryRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        reservation = self._locked_reservation(reservation_id, project_id)
        if replay is not None:
            replay_caller_metadata = replay.metadata_payload.get(
                "caller_metadata",
                replay.metadata_payload,
            )
            _require_same(
                replay.reservation_id == reservation_id
                and replay.entry_type == "SETTLE"
                and replay.settled_delta_micros == actual_micros
                and replay_caller_metadata == caller_metadata,
                key=command_idempotency_key,
                entity="settlement",
            )
            return Stored(reservation, False)
        if reservation.status == "RELEASED":
            raise InvalidState("released reservation cannot be settled")
        if reservation.status == "SETTLED":
            if reservation.settled_micros == actual_micros:
                return Stored(reservation, False)
            raise InvalidState("reservation already settled for another amount")
        account = self._locked_account(reservation.account_id, project_id)
        new_reserved = account.reserved_micros - reservation.amount_micros
        new_settled = account.settled_micros + actual_micros
        if new_reserved < 0:
            raise PersistenceError("budget reserved balance would become negative")
        overage_micros = max(0, new_settled - account.limit_micros)
        ledger_metadata = {
            "caller_metadata": caller_metadata,
            "budget_violation": overage_micros > 0,
            "overage_micros": overage_micros,
            "hard_limit_micros": account.limit_micros,
        }
        self._update_account(
            account,
            reserved_micros=new_reserved,
            settled_micros=new_settled,
        )
        self._update_reservation(
            reservation, status="SETTLED", settled_micros=actual_micros
        )
        self._add_ledger(
            reservation=reservation,
            account=account,
            entry_type="SETTLE",
            command_idempotency_key=command_idempotency_key,
            reserved_delta_micros=-reservation.amount_micros,
            settled_delta_micros=actual_micros,
            reserved_balance_micros=new_reserved,
            settled_balance_micros=new_settled,
            metadata=ledger_metadata,
        )
        self.session.flush()
        self.session.refresh(reservation)
        return Stored(reservation, True)

    def _locked_account(
        self, account_id: UUID, project_id: UUID
    ) -> BudgetAccountRecord:
        account = self.session.scalar(
            _locked(
                select(BudgetAccountRecord).where(
                    BudgetAccountRecord.id == account_id,
                    BudgetAccountRecord.project_id == project_id,
                )
            )
        )
        if account is None:
            raise PersistenceError("budget account not found")
        return account

    def _locked_reservation(
        self, reservation_id: UUID, project_id: UUID
    ) -> BudgetReservationRecord:
        reservation = self.session.scalar(
            _locked(
                select(BudgetReservationRecord).where(
                    BudgetReservationRecord.id == reservation_id,
                    BudgetReservationRecord.project_id == project_id,
                )
            )
        )
        if reservation is None:
            raise PersistenceError("budget reservation not found")
        return reservation

    def _ledger_replay(
        self,
        project_id: UUID,
        command_idempotency_key: str,
        reservation_id: UUID,
        entry_type: str,
        metadata_digest: str,
    ) -> BudgetLedgerEntryRecord | None:
        replay = self.session.scalar(
            select(BudgetLedgerEntryRecord).where(
                BudgetLedgerEntryRecord.project_id == project_id,
                BudgetLedgerEntryRecord.command_idempotency_key
                == command_idempotency_key,
            )
        )
        if replay is not None:
            _require_same(
                replay.reservation_id == reservation_id
                and replay.entry_type == entry_type
                and replay.metadata_digest == metadata_digest,
                key=command_idempotency_key,
                entity="budget ledger entry",
            )
        return replay

    def _validate_reservation_replay(
        self,
        reservation: BudgetReservationRecord,
        *,
        account_id: UUID,
        amount_micros: int,
        operation_attempt_id: UUID | None,
        operation_run_id: UUID | None,
        metadata_digest: str,
    ) -> None:
        ledger = self.session.scalar(
            select(BudgetLedgerEntryRecord).where(
                BudgetLedgerEntryRecord.project_id == reservation.project_id,
                BudgetLedgerEntryRecord.command_idempotency_key
                == reservation.command_idempotency_key,
            )
        )
        _require_same(
            reservation.account_id == account_id
            and reservation.amount_micros == amount_micros
            and reservation.operation_attempt_id == operation_attempt_id
            and reservation.operation_run_id == operation_run_id
            and ledger is not None
            and ledger.entry_type == "RESERVE"
            and ledger.metadata_digest == metadata_digest,
            key=reservation.command_idempotency_key,
            entity="budget reservation",
        )

    def _update_account(
        self,
        account: BudgetAccountRecord,
        *,
        reserved_micros: int,
        settled_micros: int,
    ) -> None:
        changed = self.session.execute(
            update(BudgetAccountRecord)
            .where(
                BudgetAccountRecord.id == account.id,
                BudgetAccountRecord.project_id == account.project_id,
                BudgetAccountRecord.state_version == account.state_version,
            )
            .values(
                reserved_micros=reserved_micros,
                settled_micros=settled_micros,
                state_version=account.state_version + 1,
                updated_at=_utcnow(),
            )
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict("budget account changed concurrently")

    def _update_reservation(
        self,
        reservation: BudgetReservationRecord,
        *,
        status: str,
        settled_micros: int | None,
    ) -> None:
        changed = self.session.execute(
            update(BudgetReservationRecord)
            .where(
                BudgetReservationRecord.id == reservation.id,
                BudgetReservationRecord.project_id == reservation.project_id,
                BudgetReservationRecord.state_version
                == reservation.state_version,
            )
            .values(
                status=status,
                settled_micros=settled_micros,
                state_version=reservation.state_version + 1,
                updated_at=_utcnow(),
            )
        )
        if changed.rowcount != 1:
            raise ConcurrentStateConflict(
                "budget reservation changed concurrently"
            )

    def _add_ledger(
        self,
        *,
        reservation: BudgetReservationRecord,
        account: BudgetAccountRecord,
        entry_type: str,
        command_idempotency_key: str,
        reserved_delta_micros: int,
        settled_delta_micros: int,
        reserved_balance_micros: int,
        settled_balance_micros: int,
        metadata: dict[str, Any],
    ) -> None:
        self.session.add(
            BudgetLedgerEntryRecord(
                id=uuid4(),
                project_id=reservation.project_id,
                account_id=account.id,
                reservation_id=reservation.id,
                sequence=2,
                command_idempotency_key=command_idempotency_key,
                entry_type=entry_type,
                reserved_delta_micros=reserved_delta_micros,
                settled_delta_micros=settled_delta_micros,
                reserved_balance_micros=reserved_balance_micros,
                settled_balance_micros=settled_balance_micros,
                metadata_payload=metadata,
                metadata_digest=canonical_json_digest(metadata),
            )
        )


class AtomicPersistenceRepository(
    WorkflowRepository,
    OperationRepository,
    SelectionRepository,
    BudgetRepository,
):
    """Convenience facade for transaction-scoped orchestration writes."""


__all__ = [
    "AtomicPersistenceRepository",
    "BudgetExceeded",
    "BudgetRepository",
    "ConcurrentStateConflict",
    "IdempotencyConflict",
    "InvalidState",
    "OperationRepository",
    "PersistenceError",
    "SelectionRepository",
    "Stored",
    "WorkflowRepository",
    "WorkflowStored",
]
