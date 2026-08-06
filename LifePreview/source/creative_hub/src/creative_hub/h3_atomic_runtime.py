"""Frozen capabilities and the executor boundary for the H3 workflow.

The durable workflow records the exact revision of each capability here before
any worker may claim it. Provider execution remains adapter-owned and is
supplied explicitly through :class:`H3AtomicExecutorContext`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol, runtime_checkable
from uuid import UUID

from atomic_runtime import (
    CapabilityPlugin,
    CapabilityRegistration,
    UpcasterRegistry,
)
from shared_contracts import (
    AtomicArtifactRef,
    CacheMode,
    CachePolicy,
    DeterminismClass,
    ImplementationManifest,
    InfrastructureRetryPolicy,
    OperationRequest,
    OperationResult,
    OperationStatus,
    PersistentArtifactRef,
    ProviderState,
    ReplayClass,
    ResourceClass,
    ResourceRequirement,
    RetentionClass,
    RetryClass,
    SafeErrorV2,
    SchemaRevision,
    TimeoutPolicy,
    build_implementation_digest,
    build_operation_spec_digest,
    OperationSpec,
)


H3_OPERATION_TYPES = (
    "project_ir.generate",
    "character_reference.generate",
    "character_reference.qc",
    "character_reference.freeze",
    "episode_ir.generate",
    "h3.sequence.execute",
    "h3.attempt.select",
)

_FLUX_REFERENCE_OPERATION = "character_reference.generate"
_H3_SEQUENCE_OPERATION = "h3.sequence.execute"
_FLUX_WORKFLOW_DIGEST = (
    "60a8681d63ce3c01f43047b2bb137bfc327041e271e3b38d3fa974abeb012b87"
)
_H3_WORKFLOW_DIGEST = (
    "f85fc557edcb22f2ca191867e96bc4551ba32755b133271e295a5ff471018789"
)
_FLUX_MODEL_DIGEST = (
    "863a82e4ff950a42a6b0e80bea824828f129eb1a8fbbdbd9e8cb29859127b486"
)
_FLUX_MODEL_WEIGHT_DIGESTS = (
    _FLUX_MODEL_DIGEST,
    "e3467b7d912a234fb929cdf215dc08efdb011810b44bc21081c4234cc75b370e",
    "d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5",
)
_H3_MODEL_DIGEST = (
    "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779"
)
_H3_MODEL_WEIGHT_DIGESTS = (
    "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779",
    "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6",
    "7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522",
    "8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48",
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _gpu_requirement(op_type: str) -> ResourceRequirement:
    if op_type == _FLUX_REFERENCE_OPERATION:
        return ResourceRequirement(
            device_type="cuda",
            minimum_vram_mb=20_000,
            target_vram_mb=45_000,
            model_digest=_FLUX_MODEL_DIGEST,
            workflow_digest=_FLUX_WORKFLOW_DIGEST,
            custom_node_environment_digest=_digest(
                "comfyui-flux2-amd-rocm-v1"
            ),
            estimated_duration_seconds=900,
            warm_model_affinity=("flux2-dev",),
            gpu_pin="cuda0",
        )
    if op_type == _H3_SEQUENCE_OPERATION:
        return ResourceRequirement(
            device_type="cuda",
            minimum_vram_mb=20_000,
            target_vram_mb=45_000,
            model_digest=_H3_MODEL_DIGEST,
            workflow_digest=_H3_WORKFLOW_DIGEST,
            custom_node_environment_digest=_digest(
                "comfyui-minimax-h3-amd-rocm-v1"
            ),
            estimated_duration_seconds=21_600,
            warm_model_affinity=("minimax-h3",),
            gpu_pin="cuda0",
        )
    raise ValueError("unsupported H3 GPU operation type")


def _resource_class(op_type: str) -> ResourceClass:
    if op_type in {_FLUX_REFERENCE_OPERATION, _H3_SEQUENCE_OPERATION}:
        return ResourceClass.LOCAL_GPU
    if op_type in H3_OPERATION_TYPES:
        return ResourceClass.CPU
    raise ValueError("unsupported H3 operation type")


def _determinism(op_type: str) -> DeterminismClass:
    if op_type in {_FLUX_REFERENCE_OPERATION, _H3_SEQUENCE_OPERATION}:
        return DeterminismClass.NONDETERMINISTIC
    if op_type in {"character_reference.freeze", "h3.attempt.select"}:
        return DeterminismClass.DETERMINISTIC
    return DeterminismClass.NONDETERMINISTIC


def _timeout_policy(op_type: str) -> TimeoutPolicy:
    if op_type == _FLUX_REFERENCE_OPERATION:
        return TimeoutPolicy(
            execution_timeout_seconds=1_800,
            heartbeat_timeout_seconds=30,
            reconciliation_timeout_seconds=300,
        )
    if op_type == _H3_SEQUENCE_OPERATION:
        return TimeoutPolicy(
            execution_timeout_seconds=25_200,
            heartbeat_timeout_seconds=30,
            reconciliation_timeout_seconds=600,
        )
    return TimeoutPolicy(
        execution_timeout_seconds=300,
        heartbeat_timeout_seconds=30,
        reconciliation_timeout_seconds=None,
    )


@lru_cache(maxsize=len(H3_OPERATION_TYPES))
def operation_spec(op_type: str) -> OperationSpec:
    resource_class = _resource_class(op_type)
    requirement = (
        _gpu_requirement(op_type)
        if resource_class is ResourceClass.LOCAL_GPU
        else None
    )
    values = {
        "op_type": op_type,
        "op_version": SchemaRevision(major=1, minor=0),
        "input_schema_version": SchemaRevision(major=1, minor=0),
        "output_schema_version": SchemaRevision(major=1, minor=0),
        "resource_class": resource_class,
        "resource_requirement": requirement,
        "determinism_class": _determinism(op_type),
        "cache_policy": CachePolicy(mode=CacheMode.DISABLED),
        "timeout_policy": _timeout_policy(op_type),
        "infrastructure_retry_policy": InfrastructureRetryPolicy(
            maximum_attempts=1,
            initial_backoff_seconds=0,
            maximum_backoff_seconds=0,
        ),
        "implementation_entrypoint": (
            "creative_hub.h3_atomic_runtime:create_h3_executor"
        ),
    }
    return OperationSpec(
        **values,
        spec_digest=build_operation_spec_digest(**values),
    )


@lru_cache(maxsize=len(H3_OPERATION_TYPES))
def implementation_manifest(op_type: str) -> ImplementationManifest:
    resource_class = _resource_class(op_type)
    requirement = (
        _gpu_requirement(op_type)
        if resource_class is ResourceClass.LOCAL_GPU
        else None
    )
    values = {
        "manifest_schema_version": SchemaRevision(major=1, minor=0),
        "replay_class": (
            ReplayClass.REPLAYABLE
            if requirement is not None
            else ReplayClass.IDENTIFIABLE_ONLY
        ),
        "code_image_digest": _digest("douyin-creative-hub:h3-amd-v1"),
        "adapter_digest": _digest(f"h3-atomic-adapter:{op_type}:v1"),
        "comfy_workflow_digest": (
            requirement.workflow_digest if requirement is not None else None
        ),
        "custom_node_set_digest": (
            requirement.custom_node_environment_digest
            if requirement is not None
            else None
        ),
        "model_weight_digests": (
            _FLUX_MODEL_WEIGHT_DIGESTS
            if op_type == _FLUX_REFERENCE_OPERATION
            else (
                _H3_MODEL_WEIGHT_DIGESTS
                if op_type == _H3_SEQUENCE_OPERATION
                else ()
            )
        ),
        "upcaster_digest": UpcasterRegistry().registry_digest(),
        "provider_identity": (
            "local-flux2-dev-rocm"
            if op_type == _FLUX_REFERENCE_OPERATION
            else (
                "local-minimax-h3-rocm"
                if op_type == _H3_SEQUENCE_OPERATION
                else "creative-hub-h3-core"
            )
        ),
    }
    return ImplementationManifest(
        **values,
        implementation_digest=build_implementation_digest(**values),
    )


class H3AtomicContractError(RuntimeError):
    """The request, backend, or artifact authority violated the H3 contract."""


@dataclass(frozen=True, slots=True)
class H3ProducedArtifact:
    """A path-free artifact payload returned by an H3 backend."""

    payload: bytes
    mime_type: str
    logical_role: str
    retention_class: RetentionClass = RetentionClass.WORKFLOW

    def __post_init__(self) -> None:
        if not isinstance(self.payload, (bytes, bytearray, memoryview)):
            raise H3AtomicContractError(
                "H3 produced artifact payload must be bytes"
            )
        try:
            payload = bytes(self.payload)
        except (TypeError, ValueError) as exc:
            raise H3AtomicContractError(
                "H3 produced artifact payload must be bytes"
            ) from exc
        if not payload:
            raise H3AtomicContractError("H3 produced artifact payload is empty")
        for label, value in (
            ("MIME type", self.mime_type),
            ("logical role", self.logical_role),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise H3AtomicContractError(
                    f"H3 produced artifact {label} must be pinned"
                )
        if not isinstance(self.retention_class, RetentionClass):
            raise H3AtomicContractError(
                "H3 produced artifact retention class is invalid"
            )
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True)
class H3CoreOutput:
    """One backend result before artifacts are published by the authority."""

    artifacts: tuple[H3ProducedArtifact, ...] = ()
    structured_output: Mapping[str, object] = field(default_factory=dict)
    metrics: Mapping[str, object] = field(default_factory=dict)
    provider_identity: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            artifacts = tuple(self.artifacts)
        except TypeError as exc:
            raise H3AtomicContractError(
                "H3 backend artifacts must be a sequence"
            ) from exc
        if not all(isinstance(item, H3ProducedArtifact) for item in artifacts):
            raise H3AtomicContractError(
                "H3 backend output contains an invalid produced artifact"
            )
        if not isinstance(self.structured_output, Mapping):
            raise H3AtomicContractError(
                "H3 backend structured output must be a mapping"
            )
        if not isinstance(self.metrics, Mapping):
            raise H3AtomicContractError("H3 backend metrics must be a mapping")
        provider = self.provider_identity
        if provider is not None and (
            not isinstance(provider, str)
            or not provider.strip()
            or provider != provider.strip()
        ):
            raise H3AtomicContractError(
                "H3 backend provider identity must be pinned"
            )
        if isinstance(self.warnings, str):
            raise H3AtomicContractError("H3 backend warnings are invalid")
        try:
            warnings = tuple(self.warnings)
        except TypeError as exc:
            raise H3AtomicContractError(
                "H3 backend warnings are invalid"
            ) from exc
        if not all(
            isinstance(item, str) and item.strip() for item in warnings
        ):
            raise H3AtomicContractError("H3 backend warnings are invalid")
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "structured_output", dict(self.structured_output))
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True, slots=True)
class H3CoreDeferred:
    """A provider submission that must reconcile without republishing."""

    error: SafeErrorV2
    metrics: Mapping[str, object] = field(default_factory=dict)
    provider_identity: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.error, SafeErrorV2):
            raise H3AtomicContractError(
                "H3 deferred output requires SafeErrorV2"
            )
        if (
            self.error.retry_class is not RetryClass.RECONCILE_PROVIDER
            or self.error.provider_state
            not in {ProviderState.SUBMITTED, ProviderState.OUTCOME_UNKNOWN}
        ):
            raise H3AtomicContractError(
                "H3 deferred output requires provider reconciliation"
            )
        if not isinstance(self.metrics, Mapping):
            raise H3AtomicContractError(
                "H3 deferred metrics must be a mapping"
            )
        provider = self.provider_identity
        if provider is not None and (
            not isinstance(provider, str)
            or not provider.strip()
            or provider != provider.strip()
        ):
            raise H3AtomicContractError(
                "H3 deferred provider identity must be pinned"
            )
        if isinstance(self.warnings, str):
            raise H3AtomicContractError("H3 deferred warnings are invalid")
        try:
            warnings = tuple(self.warnings)
        except TypeError as exc:
            raise H3AtomicContractError(
                "H3 deferred warnings are invalid"
            ) from exc
        if not all(
            isinstance(item, str) and item.strip() for item in warnings
        ):
            raise H3AtomicContractError(
                "H3 deferred warnings are invalid"
            )
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "warnings", warnings)


@runtime_checkable
class H3ArtifactPublicationBatch(Protocol):
    """Invisible staged refs that become visible in one atomic commit."""

    refs: tuple[PersistentArtifactRef, ...]

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@runtime_checkable
class H3ArtifactGateway(Protocol):
    """The sole read/publication authority visible to an H3 backend."""

    def read_bytes(self, artifact: AtomicArtifactRef, /) -> bytes: ...

    def stage_batch(
        self,
        artifacts: tuple[H3ProducedArtifact, ...],
        /,
        *,
        request: OperationRequest,
        created_at: datetime,
    ) -> H3ArtifactPublicationBatch: ...


@runtime_checkable
class H3AtomicBackend(Protocol):
    """An injected H3 implementation with no orchestration authority."""

    def run(
        self,
        request: OperationRequest,
        artifacts: H3ArtifactGateway,
        /,
    ) -> H3CoreOutput | H3CoreDeferred: ...


@dataclass(frozen=True, slots=True)
class H3AtomicExecutorContext:
    """Exact invocation identity and explicitly injected H3 dependencies."""

    op_type: str
    project_id: UUID
    workflow_run_id: UUID
    operation_run_id: UUID
    operation_attempt_id: UUID
    operation_spec_digest: str
    implementation_digest: str
    backend: H3AtomicBackend
    artifacts: H3ArtifactGateway
    provider_identity: str
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        if self.op_type not in H3_OPERATION_TYPES:
            raise H3AtomicContractError(
                f"unsupported H3 operation: {self.op_type}"
            )
        if (
            not isinstance(self.provider_identity, str)
            or not self.provider_identity.strip()
            or self.provider_identity != self.provider_identity.strip()
        ):
            raise H3AtomicContractError("H3 provider identity must be pinned")
        if not callable(self.clock):
            raise H3AtomicContractError("H3 context clock must be callable")


def _path_key(key: str) -> bool:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key.strip())
    normalized = re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")
    exact = {
        "path",
        "paths",
        "file",
        "files",
        "filepath",
        "filepaths",
        "filename",
        "filenames",
    }
    return normalized in exact or normalized.endswith(
        tuple(f"_{suffix}" for suffix in exact)
    )


_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_path(value: str) -> bool:
    return (
        bool(_WINDOWS_PATH.match(value))
        or value.startswith(("/", "\\\\", "file://"))
        or "\\" in value
        or any(segment == ".." for segment in value.split("/"))
    )


def _reject_path_fields(value: object, *, location: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            rendered_key = str(key)
            if _path_key(rendered_key):
                raise H3AtomicContractError(
                    f"{location} must use ArtifactRefs, not path field "
                    f"{rendered_key!r}"
                )
            _reject_path_fields(item, location=location)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_path_fields(item, location=location)
    elif isinstance(value, str) and _looks_like_path(value):
        raise H3AtomicContractError(
            f"{location} must use ArtifactRefs, not path-like string values"
        )


class H3AtomicExecutor:
    """Validate one pinned H3 invocation and publish its path-free outputs."""

    __slots__ = ("_context",)

    def __init__(self, context: H3AtomicExecutorContext) -> None:
        self._context = context

    def _validate_request(self, request: OperationRequest) -> None:
        if not isinstance(request, OperationRequest):
            raise H3AtomicContractError(
                "H3 executor requires an OperationRequest"
            )
        context = self._context
        mismatches = {
            "op_type": request.op_type != context.op_type,
            "project_id": request.project_id != context.project_id,
            "workflow_run_id": request.workflow_run_id != context.workflow_run_id,
            "operation_run_id": request.operation_run_id != context.operation_run_id,
            "operation_attempt_id": (
                request.operation_attempt_id != context.operation_attempt_id
            ),
            "operation_spec_digest": (
                request.operation_spec_digest != context.operation_spec_digest
            ),
            "implementation_digest": (
                request.implementation_digest != context.implementation_digest
            ),
        }
        failed = tuple(key for key, mismatch in mismatches.items() if mismatch)
        if failed:
            raise H3AtomicContractError(
                "H3 invocation identity mismatch: " + ", ".join(failed)
            )
        if request.op_type not in H3_OPERATION_TYPES:
            raise H3AtomicContractError(
                f"unsupported H3 operation: {request.op_type}"
            )
        if not isinstance(context.backend, H3AtomicBackend):
            raise H3AtomicContractError(
                "H3 context backend does not implement H3AtomicBackend"
            )
        if not isinstance(context.artifacts, H3ArtifactGateway):
            raise H3AtomicContractError(
                "H3 context artifacts does not implement H3ArtifactGateway"
            )

        spec = operation_spec(request.op_type)
        manifest = implementation_manifest(request.op_type)
        if (
            request.op_version != spec.op_version
            or request.input_schema_version != spec.input_schema_version
            or request.required_output_schema_version != spec.output_schema_version
            or request.operation_spec_digest != spec.spec_digest
            or request.implementation_digest != manifest.implementation_digest
        ):
            raise H3AtomicContractError(
                "H3 request identity does not match the registered capability"
            )
        if context.provider_identity != manifest.provider_identity:
            raise H3AtomicContractError(
                "H3 provider identity does not match the registered implementation"
            )
        _reject_path_fields(request.structured_inputs, location="structured inputs")
        _reject_path_fields(request.parameter_snapshot, location="parameter snapshot")

    def _clock(self) -> datetime:
        value = self._context.clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise H3AtomicContractError(
                "H3 context clock must return an aware timestamp"
            )
        return value

    @staticmethod
    def _validate_published(
        artifact: PersistentArtifactRef,
        *,
        produced: H3ProducedArtifact,
        request: OperationRequest,
    ) -> None:
        if not isinstance(artifact, PersistentArtifactRef):
            raise H3AtomicContractError(
                "H3 artifact gateway did not return PersistentArtifactRef"
            )
        expected_digest = hashlib.sha256(produced.payload).hexdigest()
        if (
            artifact.project_id != request.project_id
            or artifact.produced_by_operation_run_id != request.operation_run_id
            or artifact.produced_by_operation_attempt_id
            != request.operation_attempt_id
            or artifact.content_digest != expected_digest
            or artifact.mime_type != produced.mime_type
            or artifact.logical_role != produced.logical_role
            or artifact.byte_size != len(produced.payload)
            or artifact.retention_class != produced.retention_class
        ):
            raise H3AtomicContractError(
                "published H3 artifact identity does not match the operation output"
            )

    @staticmethod
    def _rollback_batch(batch: object, *, cause: BaseException) -> None:
        rollback = getattr(batch, "rollback", None)
        if not callable(rollback):
            raise H3AtomicContractError(
                "H3 artifact publication batch cannot roll back"
            ) from cause
        try:
            rollback()
        except Exception as rollback_error:
            raise H3AtomicContractError(
                "H3 artifact publication batch rollback failed"
            ) from rollback_error

    def execute(self, request: OperationRequest, /) -> OperationResult:
        self._validate_request(request)
        started_at = self._clock()
        core = self._context.backend.run(request, self._context.artifacts)
        if not isinstance(core, (H3CoreOutput, H3CoreDeferred)):
            raise H3AtomicContractError(
                "H3 backend did not return an H3 core result"
            )
        provider = core.provider_identity or self._context.provider_identity
        if provider != self._context.provider_identity:
            raise H3AtomicContractError(
                "H3 backend provider does not match the pinned provider identity"
            )
        _reject_path_fields(core.metrics, location="metrics")

        metrics = dict(core.metrics)
        metric_provider = metrics.get("provider_identity")
        if metric_provider is not None and metric_provider != provider:
            raise H3AtomicContractError(
                "H3 metrics provider does not match the pinned provider identity"
            )
        metrics["provider_identity"] = provider

        if isinstance(core, H3CoreDeferred):
            _reject_path_fields(
                core.error.public_message,
                location="deferred error public message",
            )
            _reject_path_fields(
                core.error.operator_detail,
                location="deferred error operator detail",
            )
            _reject_path_fields(core.warnings, location="deferred warnings")
            if core.error.correlation_id != request.trace_id:
                raise H3AtomicContractError(
                    "H3 deferred error correlation does not match the request"
                )
            completed_at = self._clock()
            if completed_at < started_at:
                raise H3AtomicContractError(
                    "H3 operation completion cannot precede its start"
                )
            try:
                return OperationResult(
                    project_id=request.project_id,
                    operation_run_id=request.operation_run_id,
                    operation_attempt_id=request.operation_attempt_id,
                    op_type=request.op_type,
                    op_version=request.op_version,
                    output_schema_version=(
                        request.required_output_schema_version
                    ),
                    status=OperationStatus.OUTCOME_UNKNOWN,
                    output_artifact_refs=(),
                    structured_output={},
                    metrics=metrics,
                    warnings=core.warnings,
                    error=core.error,
                    started_at=started_at,
                    completed_at=completed_at,
                    implementation_digest=request.implementation_digest,
                )
            except Exception as exc:
                raise H3AtomicContractError(
                    "H3 deferred operation result is invalid"
                ) from exc

        _reject_path_fields(core.structured_output, location="structured output")

        batch: object | None = None
        published: tuple[PersistentArtifactRef, ...] = ()
        if core.artifacts:
            try:
                batch = self._context.artifacts.stage_batch(
                    core.artifacts,
                    request=request,
                    created_at=self._clock(),
                )
            except Exception as exc:
                raise H3AtomicContractError(
                    "H3 artifact batch staging failed"
                ) from exc
            try:
                refs = getattr(batch, "refs", None)
                if (
                    type(refs) is not tuple
                    or len(refs) != len(core.artifacts)
                    or not callable(getattr(batch, "commit", None))
                    or not callable(getattr(batch, "rollback", None))
                ):
                    raise H3AtomicContractError(
                        "H3 artifact publication batch is invalid"
                    )
                for produced, ref in zip(core.artifacts, refs, strict=True):
                    self._validate_published(
                        ref,
                        produced=produced,
                        request=request,
                    )
                published = refs
            except Exception as exc:
                self._rollback_batch(batch, cause=exc)
                raise

        completed_at = self._clock()
        if completed_at < started_at:
            if batch is not None:
                clock_error = H3AtomicContractError(
                    "H3 operation completion cannot precede its start"
                )
                self._rollback_batch(batch, cause=clock_error)
            raise H3AtomicContractError(
                "H3 operation completion cannot precede its start"
            )
        try:
            result = OperationResult(
                project_id=request.project_id,
                operation_run_id=request.operation_run_id,
                operation_attempt_id=request.operation_attempt_id,
                op_type=request.op_type,
                op_version=request.op_version,
                output_schema_version=request.required_output_schema_version,
                status=OperationStatus.SUCCEEDED,
                output_artifact_refs=published,
                structured_output=dict(core.structured_output),
                metrics=metrics,
                warnings=core.warnings,
                started_at=started_at,
                completed_at=completed_at,
                implementation_digest=request.implementation_digest,
            )
        except Exception as exc:
            if batch is not None:
                self._rollback_batch(batch, cause=exc)
            raise H3AtomicContractError("H3 operation result is invalid") from exc
        if batch is not None:
            try:
                batch.commit()  # type: ignore[attr-defined]
            except Exception as exc:
                self._rollback_batch(batch, cause=exc)
                raise H3AtomicContractError(
                    "H3 artifact batch commit failed"
                ) from exc
        return result


def create_h3_executor(
    context: H3AtomicExecutorContext,
    /,
) -> H3AtomicExecutor:
    """Create an H3 executor from an exact, explicitly injected context."""

    if not isinstance(context, H3AtomicExecutorContext):
        raise H3AtomicContractError(
            "H3 executor requires H3AtomicExecutorContext"
        )
    if not isinstance(context.backend, H3AtomicBackend):
        raise H3AtomicContractError(
            "H3 context backend does not implement H3AtomicBackend"
        )
    if not isinstance(context.artifacts, H3ArtifactGateway):
        raise H3AtomicContractError(
            "H3 context artifacts does not implement H3ArtifactGateway"
        )
    return H3AtomicExecutor(context)


@lru_cache(maxsize=1)
def build_plugin() -> CapabilityPlugin:
    return CapabilityPlugin(
        name="douyin-creative-hub-h3",
        registrations=tuple(
            CapabilityRegistration(
                spec=operation_spec(op_type),
                implementation_manifest=implementation_manifest(op_type),
            )
            for op_type in H3_OPERATION_TYPES
        ),
    )


__all__ = [
    "H3ArtifactGateway",
    "H3ArtifactPublicationBatch",
    "H3AtomicBackend",
    "H3AtomicContractError",
    "H3AtomicExecutor",
    "H3AtomicExecutorContext",
    "H3CoreDeferred",
    "H3CoreOutput",
    "H3_OPERATION_TYPES",
    "H3ProducedArtifact",
    "build_plugin",
    "create_h3_executor",
    "implementation_manifest",
    "operation_spec",
]
