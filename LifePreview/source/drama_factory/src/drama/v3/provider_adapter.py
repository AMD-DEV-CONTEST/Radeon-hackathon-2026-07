from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from shared_contracts import (
    OperationRequest,
    OperationResult,
    OperationStatus,
    PersistentArtifactRef,
    ProviderState,
    RetryClass,
    SafeErrorV2,
    SchemaRevision,
)

from .domain import GenerationRunStatus
from .durable_comfy import DurableComfyCoordinator


class DramaProviderAction(StrEnum):
    SUBMIT = "submit"
    RECONCILE = "reconcile"


class DramaProviderRejected(RuntimeError):
    """The durable coordinator recorded a known terminal rejection."""


@dataclass(frozen=True, slots=True)
class DurableComfyExecutorContext:
    """Explicit attempt context; no ambient service-locator is consulted."""

    coordinator: DurableComfyCoordinator
    action: DramaProviderAction
    factory_run_id: UUID
    workflow: Mapping[str, Any]
    expected_state_version: int
    clock: Callable[[], datetime]
    instance_id: str | None = None
    gpu_id: str | None = None
    gpu_lease_id: UUID | None = None
    hub_job_lease_id: UUID | None = None
    submission_nonce: str | None = None
    client_id: str | None = None
    committed_output_artifact_refs: tuple[PersistentArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.coordinator, DurableComfyCoordinator):
            raise TypeError("coordinator must be DurableComfyCoordinator")
        if self.expected_state_version < 0:
            raise ValueError("expected state version must be non-negative")
        if not self.workflow:
            raise ValueError("workflow must not be empty")
        if self.action is DramaProviderAction.SUBMIT and any(
            value is None
            for value in (
                self.instance_id,
                self.gpu_id,
                self.gpu_lease_id,
                self.hub_job_lease_id,
                self.submission_nonce,
                self.client_id,
            )
        ):
            raise ValueError("submit context requires provider and both lease identities")
        if not all(
            isinstance(item, PersistentArtifactRef)
            for item in self.committed_output_artifact_refs
        ):
            raise TypeError(
                "committed outputs must contain only PersistentArtifactRefs"
            )


class DurableComfyAtomicExecutor:
    """Atomic façade over the existing crash-safe Comfy coordinator.

    Submission still persists a nonce before transport I/O. Reconciliation
    never opts into ``resubmit_after_confirmed_absence``; a retry decision must
    remain an explicit, separately authorized operation.
    """

    __slots__ = ("_context", "_implementation_digest", "_spec_digest")

    def __init__(
        self,
        context: DurableComfyExecutorContext,
        *,
        spec_digest: str,
        implementation_digest: str,
    ) -> None:
        self._context = context
        self._spec_digest = spec_digest
        self._implementation_digest = implementation_digest

    def execute(self, request: OperationRequest, /) -> OperationResult:
        if (
            request.op_type != "drama.comfy_video_generate"
            or request.op_version != SchemaRevision(major=1, minor=0)
            or request.operation_spec_digest != self._spec_digest
            or request.implementation_digest != self._implementation_digest
        ):
            raise ValueError("request identity does not match drama capability")

        context = self._context
        started_at = context.clock()
        workflow = dict(context.workflow)
        if context.action is DramaProviderAction.SUBMIT:
            state = context.coordinator.submit(
                context.factory_run_id,
                workflow=workflow,
                instance_id=context.instance_id or "",
                gpu_id=context.gpu_id or "",
                gpu_lease_id=context.gpu_lease_id or UUID(int=0),
                hub_job_lease_id=context.hub_job_lease_id or UUID(int=0),
                expected_state_version=context.expected_state_version,
                submission_nonce=context.submission_nonce,
                client_id=context.client_id,
            )
        else:
            # Deliberately no boolean is exposed on this adapter that can
            # silently turn reconciliation into a second provider submission.
            state = context.coordinator.recover_prepared(
                context.factory_run_id,
                workflow=workflow,
                expected_state_version=context.expected_state_version,
                resubmit_after_confirmed_absence=False,
            )

        run = next(
            item for item in state.runs if item.run_id == context.factory_run_id
        )
        if run.status is GenerationRunStatus.FAILED:
            raise DramaProviderRejected("provider submission was rejected")
        checkpoint = next(
            item
            for item in state.checkpoints
            if item.run_id == context.factory_run_id
        )
        completed_at = context.clock()
        committed = context.committed_output_artifact_refs
        materialized_statuses = {
            GenerationRunStatus.CANDIDATE,
            GenerationRunStatus.ELIGIBLE,
            GenerationRunStatus.ACCEPTED,
            GenerationRunStatus.REJECTED,
            GenerationRunStatus.NEEDS_HUMAN,
        }
        if run.status not in materialized_statuses or not committed:
            error = SafeErrorV2(
                error_code="provider_result_not_committed",
                retry_class=RetryClass.RECONCILE_PROVIDER,
                public_message=(
                    "The provider result is not yet committed as an artifact."
                ),
                operator_detail=(
                    "Reconcile the durable provider invocation and artifact "
                    "publication authority; do not advance the DAG or resubmit."
                ),
                provider_state=ProviderState.OUTCOME_UNKNOWN,
                correlation_id=request.trace_id,
            )
            return OperationResult(
                project_id=request.project_id,
                operation_run_id=request.operation_run_id,
                operation_attempt_id=request.operation_attempt_id,
                op_type=request.op_type,
                op_version=request.op_version,
                output_schema_version=SchemaRevision(major=1, minor=0),
                status=OperationStatus.OUTCOME_UNKNOWN,
                structured_output={
                    "factory_run_id": str(context.factory_run_id),
                    "factory_state_version": state.state_version,
                    "generation_status": run.status.value,
                    "provider_prompt_id": checkpoint.prompt_id,
                    "submission_nonce": checkpoint.submission_nonce,
                },
                error=error,
                metrics={},
                started_at=started_at,
                completed_at=completed_at,
                implementation_digest=self._implementation_digest,
            )
        mismatched = [
            str(item.artifact_id)
            for item in committed
            if (
                item.project_id != request.project_id
                or item.produced_by_operation_run_id
                != request.operation_run_id
                or item.produced_by_operation_attempt_id
                != request.operation_attempt_id
            )
        ]
        if mismatched:
            raise ValueError(
                "committed artifact identity does not match operation: "
                + ", ".join(mismatched)
            )
        return OperationResult(
            project_id=request.project_id,
            operation_run_id=request.operation_run_id,
            operation_attempt_id=request.operation_attempt_id,
            op_type=request.op_type,
            op_version=request.op_version,
            output_schema_version=SchemaRevision(major=1, minor=0),
            status=OperationStatus.SUCCEEDED,
            output_artifact_refs=committed,
            structured_output={
                "factory_run_id": str(context.factory_run_id),
                "factory_state_version": state.state_version,
                "generation_status": run.status.value,
                "provider_prompt_id": checkpoint.prompt_id,
                "submission_nonce": checkpoint.submission_nonce,
            },
            metrics={},
            started_at=started_at,
            completed_at=completed_at,
            implementation_digest=self._implementation_digest,
        )


def create_durable_comfy_executor(
    context: DurableComfyExecutorContext,
) -> DurableComfyAtomicExecutor:
    if not isinstance(context, DurableComfyExecutorContext):
        raise TypeError(
            "drama executor requires a DurableComfyExecutorContext"
        )
    from drama.atomic_plugin import (
        comfy_implementation_manifest,
        comfy_operation_spec,
    )

    return DurableComfyAtomicExecutor(
        context,
        spec_digest=comfy_operation_spec().spec_digest,
        implementation_digest=(
            comfy_implementation_manifest().implementation_digest
        ),
    )
