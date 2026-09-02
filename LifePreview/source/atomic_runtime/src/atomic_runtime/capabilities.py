from __future__ import annotations

import hmac
import importlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, Protocol, TypeVar, runtime_checkable

from shared_contracts import (
    ImplementationManifest,
    OperationRequest,
    OperationResult,
    OperationSpec,
    ReplayClass,
    ResourceClass,
    SchemaRevision,
    build_implementation_digest,
    build_operation_spec_digest,
)

from .errors import (
    ErrorContext,
    SafeErrorMapper,
    operation_status_for_error,
)
from .upcasting import UpcasterSnapshot


ContextT_contra = TypeVar("ContextT_contra", contravariant=True)


@runtime_checkable
class AtomicExecutor(Protocol):
    """The deliberately narrow operation executor ABI."""

    def execute(self, request: OperationRequest, /) -> OperationResult: ...


@runtime_checkable
class ExecutorFactory(Protocol, Generic[ContextT_contra]):
    """Build an executor from one explicit, adapter-owned typed context."""

    def __call__(self, context: ContextT_contra, /) -> AtomicExecutor: ...


@dataclass(frozen=True, slots=True)
class CapabilityKey:
    op_type: str
    op_version: SchemaRevision
    spec_digest: str
    implementation_digest: str

    def __hash__(self) -> int:
        return hash(
            (
                self.op_type,
                self.op_version.major,
                self.op_version.minor,
                self.spec_digest,
                self.implementation_digest,
            )
        )


class InvalidCapabilityError(ValueError):
    """A capability failed immutable identity or executor ABI validation."""


class InvalidOperationRequestError(ValueError):
    """The executor boundary rejected an invalid or unpinned request."""


class InvalidExecutorResultError(ValueError):
    """The executor boundary rejected an invalid or identity-confused result."""


class UnboundCapabilityError(RuntimeError):
    """Execution was attempted before registry/upcaster freeze binding."""


def revalidate_operation_spec(spec: OperationSpec) -> OperationSpec:
    """Return a fresh, fully validated spec and verify its self-digest.

    ``model_construct`` and stale objects from extension boundaries must not
    bypass the contract's validators.
    """

    try:
        revalidated = OperationSpec.model_validate(spec.model_dump(mode="python"))
    except Exception as exc:
        raise InvalidCapabilityError("operation spec validation failed") from exc

    expected_spec = build_operation_spec_digest(
        op_type=revalidated.op_type,
        op_version=revalidated.op_version,
        input_schema_version=revalidated.input_schema_version,
        output_schema_version=revalidated.output_schema_version,
        resource_class=revalidated.resource_class,
        resource_requirement=revalidated.resource_requirement,
        determinism_class=revalidated.determinism_class,
        cache_policy=revalidated.cache_policy,
        timeout_policy=revalidated.timeout_policy,
        infrastructure_retry_policy=revalidated.infrastructure_retry_policy,
        supported_defect_codes=revalidated.supported_defect_codes,
        supported_repair_actions=revalidated.supported_repair_actions,
        implementation_entrypoint=revalidated.implementation_entrypoint,
    )
    if not hmac.compare_digest(expected_spec, revalidated.spec_digest):
        raise InvalidCapabilityError("operation spec digest mismatch")
    return revalidated


def revalidate_implementation_manifest(
    manifest: ImplementationManifest,
) -> ImplementationManifest:
    """Return a fresh manifest whose independent digest has been rechecked."""

    try:
        revalidated = ImplementationManifest.model_validate(
            manifest.model_dump(mode="python")
        )
    except Exception as exc:
        raise InvalidCapabilityError(
            "implementation manifest validation failed"
        ) from exc
    expected_implementation = build_implementation_digest(
        manifest_schema_version=revalidated.manifest_schema_version,
        replay_class=revalidated.replay_class,
        code_image_digest=revalidated.code_image_digest,
        adapter_digest=revalidated.adapter_digest,
        comfy_workflow_digest=revalidated.comfy_workflow_digest,
        custom_node_set_digest=revalidated.custom_node_set_digest,
        model_weight_digests=revalidated.model_weight_digests,
        prompt_digest=revalidated.prompt_digest,
        rubric_digest=revalidated.rubric_digest,
        upcaster_digest=revalidated.upcaster_digest,
        provider_identity=revalidated.provider_identity,
    )
    if not hmac.compare_digest(
        expected_implementation,
        revalidated.implementation_digest,
    ):
        raise InvalidCapabilityError("implementation manifest digest mismatch")
    return revalidated


def _load_object(entrypoint: str) -> object:
    module_name, separator, attribute_path = entrypoint.partition(":")
    if not separator:
        raise InvalidCapabilityError("executor entrypoint must use module:attribute")
    try:
        value: object = importlib.import_module(module_name)
        for attribute in attribute_path.split("."):
            value = getattr(value, attribute)
    except (ImportError, AttributeError) as exc:
        raise InvalidCapabilityError(
            f"executor entrypoint could not be loaded: {entrypoint}"
        ) from exc
    return value


@dataclass(frozen=True, slots=True)
class CapabilityRegistration:
    """One immutable, exactly pinned implementation registration."""

    spec: OperationSpec
    implementation_manifest: ImplementationManifest
    error_mapper: SafeErrorMapper = field(default_factory=SafeErrorMapper)
    _upcaster_snapshot: UpcasterSnapshot | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.spec, OperationSpec):
            raise InvalidCapabilityError("registration spec must be OperationSpec")
        if not isinstance(self.error_mapper, SafeErrorMapper):
            raise InvalidCapabilityError(
                "registration error mapper must be SafeErrorMapper"
            )
        object.__setattr__(self, "spec", revalidate_operation_spec(self.spec))
        if not isinstance(self.implementation_manifest, ImplementationManifest):
            raise InvalidCapabilityError(
                "registration implementation_manifest must be ImplementationManifest"
            )
        object.__setattr__(
            self,
            "implementation_manifest",
            revalidate_implementation_manifest(self.implementation_manifest),
        )
        if self.spec.resource_class is ResourceClass.LOCAL_GPU:
            requirement = self.spec.resource_requirement
            if requirement is None:  # OperationSpec also enforces this.
                raise InvalidCapabilityError(
                    "local GPU registration requires resource requirements"
                )
            manifest = self.implementation_manifest
            if manifest.replay_class is not ReplayClass.REPLAYABLE:
                raise InvalidCapabilityError(
                    "local GPU implementation must be replayable"
                )
            if (
                manifest.comfy_workflow_digest != requirement.workflow_digest
                or manifest.custom_node_set_digest
                != requirement.custom_node_environment_digest
                or requirement.model_digest not in manifest.model_weight_digests
            ):
                raise InvalidCapabilityError(
                    "local GPU spec and implementation manifest do not describe "
                    "the same pinned workflow, nodes, and model"
                )

    @property
    def key(self) -> CapabilityKey:
        return CapabilityKey(
            op_type=self.spec.op_type,
            op_version=self.spec.op_version,
            spec_digest=self.spec.spec_digest,
            implementation_digest=self.implementation_manifest.implementation_digest,
        )

    @property
    def executor_factory_entrypoint(self) -> str:
        return self.spec.implementation_entrypoint

    @property
    def is_bound(self) -> bool:
        return self._upcaster_snapshot is not None

    @property
    def upcaster_snapshot(self) -> UpcasterSnapshot:
        if self._upcaster_snapshot is None:
            raise UnboundCapabilityError(
                "capability registration is not bound to a frozen upcaster snapshot"
            )
        return self._upcaster_snapshot

    def _bind(self, snapshot: UpcasterSnapshot) -> CapabilityRegistration:
        if snapshot.digest != self.implementation_manifest.upcaster_digest:
            raise InvalidCapabilityError(
                "upcaster snapshot does not match implementation manifest"
            )
        bound = CapabilityRegistration(
            spec=self.spec,
            implementation_manifest=self.implementation_manifest,
            error_mapper=self.error_mapper,
        )
        object.__setattr__(bound, "_upcaster_snapshot", snapshot)
        return bound

    def load_executor_factory(self) -> ExecutorFactory[object]:
        """Import the implementation only when execution is requested."""

        value = _load_object(self.executor_factory_entrypoint)
        if not callable(value):
            raise InvalidCapabilityError("executor factory entrypoint is not callable")
        return value  # type: ignore[return-value]

    def build_executor(self, context: object, /) -> AtomicExecutor:
        self.upcaster_snapshot
        executor = self.load_executor_factory()(context)
        if not isinstance(executor, AtomicExecutor):
            raise InvalidCapabilityError(
                "executor factory result does not implement execute(request)"
            )
        return _PinnedExecutor(self, executor)

    def invoke(
        self,
        request: OperationRequest,
        context: object,
        /,
        *,
        error_context: ErrorContext | None = None,
    ) -> OperationResult:
        self.upcaster_snapshot
        validated_request = _PinnedExecutor.validate_request(self, request)
        started_at = datetime.now(timezone.utc)
        try:
            return self.build_executor(context).execute(validated_request)
        except InvalidOperationRequestError:
            raise
        except Exception as exc:
            safe_error = self.error_mapper.map(
                exc,
                error_context
                or ErrorContext(correlation_id=validated_request.trace_id),
            )
            completed_at = datetime.now(timezone.utc)
            return OperationResult(
                project_id=validated_request.project_id,
                operation_run_id=validated_request.operation_run_id,
                operation_attempt_id=validated_request.operation_attempt_id,
                op_type=validated_request.op_type,
                op_version=validated_request.op_version,
                output_schema_version=self.spec.output_schema_version,
                status=operation_status_for_error(safe_error),
                error=safe_error,
                started_at=started_at,
                completed_at=completed_at,
                implementation_digest=(
                    self.implementation_manifest.implementation_digest
                ),
            )


class _PinnedExecutor:
    """Validation and identity boundary around an untrusted plugin executor."""

    __slots__ = ("_delegate", "_registration")

    def __init__(
        self,
        registration: CapabilityRegistration,
        delegate: AtomicExecutor,
    ) -> None:
        self._registration = registration
        self._delegate = delegate

    @staticmethod
    def validate_request(
        registration: CapabilityRegistration,
        request: OperationRequest,
    ) -> OperationRequest:
        if not isinstance(request, OperationRequest):
            raise InvalidOperationRequestError(
                "executor request is not an OperationRequest"
            )
        try:
            validated_request = OperationRequest.model_validate(
                request.model_dump(mode="json")
            )
        except Exception:
            raise InvalidOperationRequestError(
                "executor request failed contract revalidation"
            ) from None

        key = registration.key
        if (
            validated_request.op_type != key.op_type
            or validated_request.op_version != key.op_version
            or validated_request.operation_spec_digest != key.spec_digest
            or validated_request.implementation_digest
            != key.implementation_digest
        ):
            raise InvalidOperationRequestError(
                "executor request does not match its pinned registration"
            )
        return validated_request

    def execute(self, request: OperationRequest, /) -> OperationResult:
        validated_request = self.validate_request(self._registration, request)
        key = self._registration.key
        candidate = self._delegate.execute(validated_request)
        if not isinstance(candidate, OperationResult):
            raise InvalidExecutorResultError(
                "plugin executor did not return OperationResult"
            )
        try:
            result = OperationResult.model_validate(
                candidate.model_dump(mode="json")
            )
        except Exception:
            raise InvalidExecutorResultError(
                "plugin result failed contract revalidation"
            ) from None

        if (
            result.project_id != validated_request.project_id
            or result.operation_run_id != validated_request.operation_run_id
            or result.operation_attempt_id
            != validated_request.operation_attempt_id
            or result.op_type != key.op_type
            or result.op_version != key.op_version
            or result.output_schema_version
            != self._registration.spec.output_schema_version
            or result.implementation_digest != key.implementation_digest
        ):
            raise InvalidExecutorResultError(
                "plugin result identity does not match its pinned request"
            )
        return result


@dataclass(frozen=True, slots=True)
class CapabilityPlugin:
    """A lightweight immutable bundle exposed through package metadata."""

    name: str
    registrations: tuple[CapabilityRegistration, ...]

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise InvalidCapabilityError("plugin name must be non-empty and trimmed")
        registrations = tuple(self.registrations)
        if not registrations:
            raise InvalidCapabilityError("capability plugin must register at least one item")
        if not all(
            isinstance(registration, CapabilityRegistration)
            for registration in registrations
        ):
            raise InvalidCapabilityError(
                "plugin registrations must be CapabilityRegistration objects"
            )
        keys = tuple(registration.key for registration in registrations)
        if len(keys) != len(set(keys)):
            raise InvalidCapabilityError("plugin contains a capability key collision")
        object.__setattr__(self, "registrations", registrations)
