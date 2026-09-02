"""Production-only persistence helpers for competition visual preparation.

The image provider and GLM transport live behind
``HistoricalVisualIdentityPreparer``.  This module supplies the missing
PostgreSQL attempt fence used by its CAS publisher.  Constructing the helper
does not perform network, filesystem, or GPU work; ``begin_or_reuse`` creates
one deterministic CPU operation for the exact visual-preparation input.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.orm import Session

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.repositories import OperationRepository, WorkflowRepository

from .visual_identity_preparation import VisualPreparationAttempt


SessionFactory = Callable[[], Session]

_WORKFLOW_KEY = "shidu.visual-preparation.v1"
_SCHEMA_REVISION = "amd.visual-preparation-operation.v1"
_WORKER_ID = "amd.visual-preparation"
_DEFINITION = {
    "schemaVersion": _SCHEMA_REVISION,
    "nodes": [
        {
            "nodeKey": "visual.prepare",
            "operationType": "visual.identity.prepare",
            "operationVersion": "v1",
        }
    ],
}
_IMPLEMENTATION_DIGEST = canonical_json_digest(
    {
        "schemaVersion": "amd.visual-preparation-implementation.v1",
        "workflowKey": _WORKFLOW_KEY,
        "definition": _DEFINITION,
    }
)


class VisualAttemptPersistenceError(RuntimeError):
    """The durable visual-preparation attempt could not be re-attested."""


@dataclass(frozen=True, slots=True)
class PostgresVisualPreparationAttemptSource:
    """Create or replay one fenced CAS attempt for a visual input digest."""

    session_factory: SessionFactory
    actor_id: str
    workflow_repository_factory: Callable[[Session], Any] = WorkflowRepository
    operation_repository_factory: Callable[[Session], Any] = OperationRepository

    def __post_init__(self) -> None:
        if not callable(self.session_factory):
            raise ValueError("visual attempt session factory is invalid")
        if (
            type(self.actor_id) is not str
            or not self.actor_id
            or self.actor_id != self.actor_id.strip()
            or len(self.actor_id) > 160
        ):
            raise ValueError("visual attempt actor is invalid")
        if not callable(self.workflow_repository_factory) or not callable(
            self.operation_repository_factory
        ):
            raise ValueError("visual attempt repository factory is invalid")

    def begin_or_reuse(
        self, *, project_id: UUID, input_digest: str
    ) -> VisualPreparationAttempt:
        if type(project_id) is not UUID:
            raise ValueError("visual attempt project_id is invalid")
        if (
            type(input_digest) is not str
            or len(input_digest) != 64
            or any(character not in "0123456789abcdef" for character in input_digest)
        ):
            raise ValueError("visual attempt input digest is invalid")

        workflow_command = f"amd-visual-prep-definition:{project_id}"
        run_command = f"amd-visual-prep-run:{input_digest}"
        operation_command = f"amd-visual-prep-operation:{input_digest}"
        submission_nonce = uuid5(
            NAMESPACE_URL,
            f"shidu:amd-visual-preparation:{project_id}:{input_digest}",
        )
        request = {
            "schemaVersion": _SCHEMA_REVISION,
            "projectId": str(project_id),
            "inputDigest": input_digest,
        }

        try:
            with self.session_factory() as session, session.begin():
                workflows = self.workflow_repository_factory(session)
                operations = self.operation_repository_factory(session)
                workflow = workflows.create_workflow_definition(
                    project_id=project_id,
                    workflow_key=_WORKFLOW_KEY,
                    name="AMD visual identity preparation",
                    definition=_DEFINITION,
                    schema_revision=_SCHEMA_REVISION,
                    command_idempotency_key=workflow_command,
                    created_by_actor=self.actor_id,
                )
                run = workflows.create_workflow_run(
                    project_id=project_id,
                    workflow_definition_id=workflow.definition.id,
                    workflow_revision_id=workflow.revision.id,
                    command_idempotency_key=run_command,
                    input_payload=request,
                    policy_snapshot={
                        "schemaVersion": "amd.visual-preparation-policy.v1",
                        "networkDiscovery": "wikimedia-plus-glm",
                        "syntheticFallback": False,
                    },
                ).value
                operation = operations.create_operation_run(
                    project_id=project_id,
                    workflow_run_id=run.id,
                    node_key="visual.prepare",
                    op_type="visual.identity.prepare",
                    op_version="v1",
                    command_idempotency_key=operation_command,
                    request_payload=request,
                ).value
                attempt = operations.create_attempt(
                    project_id=project_id,
                    operation_run_id=operation.id,
                    attempt_number=1,
                    fencing_token=1,
                    worker_id=_WORKER_ID,
                    implementation_digest=_IMPLEMENTATION_DIGEST,
                    request_payload=request,
                    submission_nonce=submission_nonce,
                ).value
        except Exception as exc:
            raise VisualAttemptPersistenceError(
                "visual preparation attempt is unavailable"
            ) from exc

        try:
            if (
                attempt.project_id != project_id
                or attempt.operation_run_id != operation.id
                or attempt.attempt_number != 1
                or attempt.fencing_token != 1
                or attempt.request_digest != canonical_json_digest(request)
                or attempt.implementation_digest != _IMPLEMENTATION_DIGEST
                or attempt.submission_nonce != submission_nonce
            ):
                raise ValueError
            return VisualPreparationAttempt(
                project_id=project_id,
                operation_run_id=operation.id,
                attempt_id=attempt.id,
                attempt_number=attempt.attempt_number,
                fencing_token=attempt.fencing_token,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise VisualAttemptPersistenceError(
                "visual preparation attempt authority is invalid"
            ) from exc


__all__ = [
    "PostgresVisualPreparationAttemptSource",
    "VisualAttemptPersistenceError",
]
