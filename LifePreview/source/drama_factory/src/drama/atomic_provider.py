from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
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

from .v3.durable_provider import (
    DurableProviderCoordinator,
    ProviderActionGrant,
    ProviderGrantAction,
    ProviderInvocation,
    ProviderInvocationPhase,
    ProviderTerminalOutcome,
)
from .atomic_factory import VIDEO_GENERATION_MODES, _reject_path_fields


ArtifactResolver = Callable[
    [ProviderInvocation],
    tuple[PersistentArtifactRef, ...],
]
ProviderMaterializer = Callable[
    [ProviderInvocation],
    Mapping[str, object],
]


class DurableProviderAtomicContractError(ValueError):
    """A generalized provider invocation failed exact atomic validation."""


@dataclass(frozen=True, slots=True)
class DurableProviderAtomicExecutorContext:
    """Injected bridge to the provider-agnostic T6 durable authority."""

    coordinator: DurableProviderCoordinator
    invocation_id: UUID
    workflow_run_id: UUID
    grant: ProviderActionGrant
    artifact_resolver: ArtifactResolver
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    materializer: ProviderMaterializer | None = None
    actual_cost_micros: int | None = None
    allow_idempotent_replay_after_absence: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.coordinator, DurableProviderCoordinator):
            raise TypeError("coordinator must be DurableProviderCoordinator")
        if self.grant.invocation_id != self.invocation_id:
            raise ValueError("provider grant belongs to another invocation")
        if not callable(self.artifact_resolver):
            raise TypeError("artifact resolver must be callable")
        if (
            self.grant.action is ProviderGrantAction.MATERIALIZE
            and self.materializer is None
        ):
            raise ValueError("materialize grant requires a materializer")
        if (
            self.grant.action is not ProviderGrantAction.MATERIALIZE
            and self.materializer is not None
        ):
            raise ValueError("materializer is valid only for materialize action")
        if self.actual_cost_micros is not None and self.actual_cost_micros < 0:
            raise ValueError("actual cost must be non-negative")


class DurableProviderAtomicExecutor:
    """Fail-closed atomic projection of one generalized durable invocation."""

    __slots__ = (
        "_context",
        "_implementation_digest",
        "_op_type",
        "_provider_identity",
        "_spec_digest",
    )

    def __init__(
        self,
        context: DurableProviderAtomicExecutorContext,
        *,
        op_type: str,
        spec_digest: str,
        implementation_digest: str,
        provider_identity: str,
    ) -> None:
        self._context = context
        self._op_type = op_type
        self._spec_digest = spec_digest
        self._implementation_digest = implementation_digest
        self._provider_identity = provider_identity

    @staticmethod
    def _validate_invocation_identity(
        request: OperationRequest,
        invocation: ProviderInvocation,
    ) -> None:
        if (
            invocation.project_id != request.project_id
            or invocation.operation_run_id != request.operation_run_id
            or invocation.operation_attempt_id
            != request.operation_attempt_id
        ):
            raise DurableProviderAtomicContractError(
                "durable provider invocation does not match operation identity"
            )

    def _pending_result(
        self,
        request: OperationRequest,
        invocation: ProviderInvocation,
        *,
        started_at: datetime,
    ) -> OperationResult:
        human_required = invocation.human_required
        error = SafeErrorV2(
            error_code=(
                invocation.safe_reason_code or "provider_result_not_committed"
            ),
            retry_class=(
                RetryClass.HUMAN_REQUIRED
                if human_required
                else RetryClass.RECONCILE_PROVIDER
            ),
            public_message=(
                "The provider result requires operator review."
                if human_required
                else "The provider result is not yet committed as an artifact."
            ),
            operator_detail=(
                "Use the persisted generalized provider invocation authority; "
                "do not advance the DAG or submit a second provider task."
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
                "provider_invocation_id": str(invocation.invocation_id),
                "provider": invocation.provider,
                "provider_phase": invocation.phase.value,
                "provider_task_id": invocation.provider_task_id,
                "provider_state_version": invocation.state_version,
            },
            error=error,
            started_at=started_at,
            completed_at=self._context.clock(),
            implementation_digest=self._implementation_digest,
        )

    def _terminal_failure(
        self,
        request: OperationRequest,
        invocation: ProviderInvocation,
        *,
        started_at: datetime,
    ) -> OperationResult:
        cancelled = (
            invocation.terminal_outcome is ProviderTerminalOutcome.CANCELLED
        )
        error = SafeErrorV2(
            error_code=(
                "provider_cancelled" if cancelled else "provider_terminal_failure"
            ),
            retry_class=RetryClass.NEVER,
            public_message=(
                "The provider operation was cancelled."
                if cancelled
                else "The provider operation failed."
            ),
            operator_detail=(
                "The generalized provider authority recorded a terminal outcome."
            ),
            provider_state=ProviderState.OBSERVED_TERMINAL,
            correlation_id=request.trace_id,
        )
        return OperationResult(
            project_id=request.project_id,
            operation_run_id=request.operation_run_id,
            operation_attempt_id=request.operation_attempt_id,
            op_type=request.op_type,
            op_version=request.op_version,
            output_schema_version=SchemaRevision(major=1, minor=0),
            status=(
                OperationStatus.CANCELLED
                if cancelled
                else OperationStatus.FAILED
            ),
            structured_output={
                "provider_invocation_id": str(invocation.invocation_id),
                "provider": invocation.provider,
                "provider_phase": invocation.phase.value,
                "provider_state_version": invocation.state_version,
            },
            error=error,
            started_at=started_at,
            completed_at=self._context.clock(),
            implementation_digest=self._implementation_digest,
        )

    def execute(self, request: OperationRequest, /) -> OperationResult:
        if (
            request.op_type != self._op_type
            or request.op_version != SchemaRevision(major=1, minor=0)
            or request.operation_spec_digest != self._spec_digest
            or request.implementation_digest != self._implementation_digest
        ):
            raise DurableProviderAtomicContractError(
                "request identity does not match drama capability"
            )
        if request.workflow_run_id != self._context.workflow_run_id:
            raise DurableProviderAtomicContractError(
                "request workflow run does not match durable provider context"
            )
        if self._op_type == "video.generate":
            _reject_path_fields(
                request.structured_inputs,
                location="structured inputs",
            )
            _reject_path_fields(
                request.parameter_snapshot,
                location="parameter snapshot",
            )
            if request.structured_inputs.get("mode") not in VIDEO_GENERATION_MODES:
                raise DurableProviderAtomicContractError(
                    "video.generate mode must be t2v, i2v, or first_last_frame"
                )
            seed = request.parameter_snapshot.get("seed")
            if (
                isinstance(seed, bool)
                or not isinstance(seed, int)
                or seed < 0
                or seed > 2**63 - 1
            ):
                raise DurableProviderAtomicContractError(
                    "video.generate requires a pinned integer seed"
                )
        context = self._context
        started_at = context.clock()
        action = context.grant.action
        if action is ProviderGrantAction.SUBMIT:
            invocation = context.coordinator.submit(
                context.invocation_id,
                grant=context.grant,
            )
        elif action is ProviderGrantAction.RECONCILE:
            invocation = context.coordinator.reconcile(
                context.invocation_id,
                grant=context.grant,
                allow_idempotent_replay_after_absence=(
                    context.allow_idempotent_replay_after_absence
                ),
            )
        else:
            invocation = context.coordinator.materialize(
                context.invocation_id,
                grant=context.grant,
                materializer=context.materializer,  # type: ignore[arg-type]
                actual_cost_micros=context.actual_cost_micros,
            )
        self._validate_invocation_identity(request, invocation)
        if invocation.provider != self._provider_identity:
            raise DurableProviderAtomicContractError(
                "durable provider identity does not match implementation manifest"
            )

        if (
            invocation.phase is ProviderInvocationPhase.OBSERVED_TERMINAL
            and invocation.terminal_outcome
            in {
                ProviderTerminalOutcome.FAILED,
                ProviderTerminalOutcome.CANCELLED,
            }
        ):
            return self._terminal_failure(
                request,
                invocation,
                started_at=started_at,
            )
        if invocation.phase is not ProviderInvocationPhase.COMMITTED:
            return self._pending_result(
                request,
                invocation,
                started_at=started_at,
            )

        output_refs = tuple(context.artifact_resolver(invocation))
        if not output_refs:
            return self._pending_result(
                request,
                invocation,
                started_at=started_at,
            )
        if not all(
            isinstance(artifact, PersistentArtifactRef)
            for artifact in output_refs
        ):
            raise DurableProviderAtomicContractError(
                "artifact resolver must return PersistentArtifactRefs"
            )
        mismatched = [
            str(artifact.artifact_id)
            for artifact in output_refs
            if (
                artifact.project_id != request.project_id
                or artifact.produced_by_operation_run_id
                != request.operation_run_id
                or artifact.produced_by_operation_attempt_id
                != request.operation_attempt_id
            )
        ]
        if mismatched:
            raise DurableProviderAtomicContractError(
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
            output_artifact_refs=output_refs,
            structured_output={
                "provider_invocation_id": str(invocation.invocation_id),
                "provider": invocation.provider,
                "provider_phase": invocation.phase.value,
                "provider_state_version": invocation.state_version,
                "committed_result_digest": invocation.committed_result_digest,
                "implementation_manifest": {
                    "operation_spec_digest": request.operation_spec_digest,
                    "implementation_digest": request.implementation_digest,
                    "determinism_class": "seeded",
                    "seed": request.parameter_snapshot.get("seed"),
                    "provider_identity": invocation.provider,
                },
            },
            metrics={
                "actual_cost_micros": invocation.cost_micros,
            },
            started_at=started_at,
            completed_at=context.clock(),
            implementation_digest=self._implementation_digest,
        )


def create_durable_provider_executor(
    context: DurableProviderAtomicExecutorContext,
) -> DurableProviderAtomicExecutor:
    if not isinstance(context, DurableProviderAtomicExecutorContext):
        raise TypeError(
            "drama provider executor requires DurableProviderAtomicExecutorContext"
        )
    from drama.atomic_plugin import (
        comfy_implementation_manifest,
        comfy_operation_spec,
    )

    return DurableProviderAtomicExecutor(
        context,
        op_type="drama.comfy_video_generate",
        spec_digest=comfy_operation_spec().spec_digest,
        implementation_digest=(
            comfy_implementation_manifest().implementation_digest
        ),
        provider_identity=(
            comfy_implementation_manifest().provider_identity or ""
        ),
    )


def create_factory_video_provider_executor(
    context: DurableProviderAtomicExecutorContext,
) -> DurableProviderAtomicExecutor:
    if not isinstance(context, DurableProviderAtomicExecutorContext):
        raise TypeError(
            "video.generate requires DurableProviderAtomicExecutorContext"
        )
    from drama.atomic_plugin import factory_registrations

    registration = next(
        item
        for item in factory_registrations()
        if item.spec.op_type == "video.generate"
    )
    return DurableProviderAtomicExecutor(
        context,
        op_type="video.generate",
        spec_digest=registration.spec.spec_digest,
        implementation_digest=(
            registration.implementation_manifest.implementation_digest
        ),
        provider_identity=(
            registration.implementation_manifest.provider_identity or ""
        ),
    )


__all__ = [
    "ArtifactResolver",
    "DurableProviderAtomicContractError",
    "DurableProviderAtomicExecutor",
    "DurableProviderAtomicExecutorContext",
    "ProviderMaterializer",
    "create_durable_provider_executor",
    "create_factory_video_provider_executor",
]
