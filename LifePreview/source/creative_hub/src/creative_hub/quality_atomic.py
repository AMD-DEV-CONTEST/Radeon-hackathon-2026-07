from __future__ import annotations

import hashlib
import importlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from atomic_runtime import (
    CapabilityPlugin,
    CapabilityRegistration,
    SafeErrorMapper,
    SafeErrorTemplate,
    UpcasterRegistry,
)
from shared_contracts import (
    CacheMode,
    CachePolicy,
    DeterminismClass,
    ImplementationManifest,
    InfrastructureRetryPolicy,
    OperationRequest,
    OperationResult,
    OperationSpec,
    OperationStatus,
    ProviderState,
    ReplayClass,
    ResourceClass,
    RetryClass,
    SchemaRevision,
    TimeoutPolicy,
    build_implementation_digest,
    build_operation_spec_digest,
)

from .quality import QCEvaluatorResult, QualityStage


QUALITY_EVALUATOR_OPERATION_TYPES = tuple(
    f"qc.evaluate.{stage.value}" for stage in QualityStage
)


class QualityEvaluatorUnavailable(RuntimeError):
    pass


class QualityEvaluatorOutputInvalid(ValueError):
    pass


class QualityEvaluatorBackend(Protocol):
    def evaluate(
        self,
        request: OperationRequest,
        /,
    ) -> Mapping[str, object] | QCEvaluatorResult: ...


class QualityEvaluatorBackendFactory(Protocol):
    def __call__(
        self,
        *,
        request: OperationRequest,
        artifact_gateway: object,
        credential_resolver: Callable[[str, str], str] | None,
    ) -> QualityEvaluatorBackend: ...


@dataclass(frozen=True, slots=True)
class QualityExecutorContext:
    backend: QualityEvaluatorBackend
    clock: Callable[[], datetime]


class UnavailableQualityEvaluatorBackend:
    """Production fail-closed backend until an evaluator adapter is supplied."""

    def evaluate(self, request: OperationRequest, /) -> Mapping[str, object]:
        del request
        raise QualityEvaluatorUnavailable(
            "the machine quality evaluator backend is not configured"
        )


def configured_quality_backend_factory(
) -> QualityEvaluatorBackendFactory | None:
    """Load the operator-pinned backend adapter from the runtime image."""

    reference = os.getenv("CREATIVE_HUB_QC_BACKEND_ENTRYPOINT")
    if not reference:
        return None
    module_name, separator, attribute_path = reference.partition(":")
    if not separator or not module_name or not attribute_path:
        raise RuntimeError(
            "CREATIVE_HUB_QC_BACKEND_ENTRYPOINT must use module:attribute"
        )
    try:
        value: object = importlib.import_module(module_name)
        for attribute in attribute_path.split("."):
            value = getattr(value, attribute)
    except (ImportError, AttributeError):
        raise RuntimeError(
            "configured quality evaluator backend could not be loaded"
        ) from None
    if not callable(value):
        raise RuntimeError(
            "configured quality evaluator backend factory is not callable"
        )
    return value


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@lru_cache(maxsize=len(QUALITY_EVALUATOR_OPERATION_TYPES))
def quality_operation_spec(op_type: str) -> OperationSpec:
    if op_type not in QUALITY_EVALUATOR_OPERATION_TYPES:
        raise ValueError("unsupported quality evaluator operation type")
    values = {
        "op_type": op_type,
        "op_version": SchemaRevision(major=1, minor=0),
        "input_schema_version": SchemaRevision(major=1, minor=0),
        "output_schema_version": SchemaRevision(major=1, minor=0),
        "resource_class": ResourceClass.LLM,
        "determinism_class": DeterminismClass.NONDETERMINISTIC,
        "cache_policy": CachePolicy(mode=CacheMode.DISABLED),
        "timeout_policy": TimeoutPolicy(
            execution_timeout_seconds=600,
            heartbeat_timeout_seconds=30,
            reconciliation_timeout_seconds=None,
        ),
        "infrastructure_retry_policy": InfrastructureRetryPolicy(
            maximum_attempts=1,
            initial_backoff_seconds=0,
            maximum_backoff_seconds=0,
        ),
        "supported_defect_codes": (
            "quality_evaluator_output_invalid",
            "quality_evaluator_unavailable",
        ),
        "supported_repair_actions": ("same_stage_repair",),
        "implementation_entrypoint": (
            "creative_hub.quality_atomic:create_quality_executor"
        ),
    }
    return OperationSpec(
        **values,
        spec_digest=build_operation_spec_digest(**values),
    )


@lru_cache(maxsize=len(QUALITY_EVALUATOR_OPERATION_TYPES))
def quality_implementation_manifest(op_type: str) -> ImplementationManifest:
    if op_type not in QUALITY_EVALUATOR_OPERATION_TYPES:
        raise ValueError("unsupported quality evaluator operation type")
    values = {
        "manifest_schema_version": SchemaRevision(major=1, minor=0),
        "replay_class": ReplayClass.IDENTIFIABLE_ONLY,
        "code_image_digest": _digest("douyin-creative-hub:image:v1"),
        "adapter_digest": _digest(f"quality-atomic-adapter:{op_type}:v1"),
        "upcaster_digest": UpcasterRegistry().registry_digest(),
        "provider_identity": "creative-hub-machine-qc",
    }
    return ImplementationManifest(
        **values,
        implementation_digest=build_implementation_digest(**values),
    )


class QualityAtomicExecutor:
    __slots__ = ("_context",)

    def __init__(self, context: QualityExecutorContext) -> None:
        self._context = context

    def execute(self, request: OperationRequest, /) -> OperationResult:
        if request.op_type not in QUALITY_EVALUATOR_OPERATION_TYPES:
            raise QualityEvaluatorOutputInvalid(
                "request is not a quality evaluator capability"
            )
        spec = quality_operation_spec(request.op_type)
        manifest = quality_implementation_manifest(request.op_type)
        if (
            request.op_version != spec.op_version
            or request.operation_spec_digest != spec.spec_digest
            or request.implementation_digest
            != manifest.implementation_digest
        ):
            raise QualityEvaluatorOutputInvalid(
                "request identity does not match quality capability"
            )
        started_at = self._context.clock()
        raw = self._context.backend.evaluate(request)
        try:
            result = (
                raw
                if isinstance(raw, QCEvaluatorResult)
                else QCEvaluatorResult.model_validate(dict(raw))
            )
        except Exception:
            raise QualityEvaluatorOutputInvalid(
                "quality evaluator result failed contract validation"
            ) from None
        return OperationResult(
            project_id=request.project_id,
            operation_run_id=request.operation_run_id,
            operation_attempt_id=request.operation_attempt_id,
            op_type=request.op_type,
            op_version=request.op_version,
            output_schema_version=spec.output_schema_version,
            status=OperationStatus.SUCCEEDED,
            structured_output=result.model_dump(mode="json"),
            metrics={
                "quality_score": result.quality_score,
                "confidence": result.confidence,
            },
            started_at=started_at,
            completed_at=self._context.clock(),
            implementation_digest=manifest.implementation_digest,
        )


def create_quality_executor(
    context: QualityExecutorContext,
) -> QualityAtomicExecutor:
    if not isinstance(context, QualityExecutorContext):
        raise TypeError("quality executor requires QualityExecutorContext")
    return QualityAtomicExecutor(context)


def _error_mapper() -> SafeErrorMapper:
    unavailable = SafeErrorTemplate(
        error_code="quality_evaluator_unavailable",
        retry_class=RetryClass.NEVER,
        public_message="The machine quality evaluator is unavailable.",
        operator_detail=(
            "The registered quality capability has no available evaluator "
            "backend; the gate remains fail-closed."
        ),
        provider_state=ProviderState.NOT_APPLICABLE,
    )
    invalid = SafeErrorTemplate(
        error_code="quality_evaluator_output_invalid",
        retry_class=RetryClass.NEVER,
        public_message="The machine quality result is invalid.",
        operator_detail=(
            "The evaluator output did not satisfy the frozen quality contract."
        ),
        provider_state=ProviderState.OBSERVED_TERMINAL,
    )
    return SafeErrorMapper(
        {
            (
                "creative_hub.quality_atomic:"
                "QualityEvaluatorUnavailable"
            ): unavailable,
            (
                "creative_hub.quality_atomic:"
                "QualityEvaluatorOutputInvalid"
            ): invalid,
        }
    )


@lru_cache(maxsize=1)
def build_plugin() -> CapabilityPlugin:
    mapper = _error_mapper()
    return CapabilityPlugin(
        name="douyin-creative-hub",
        registrations=tuple(
            CapabilityRegistration(
                spec=quality_operation_spec(op_type),
                implementation_manifest=quality_implementation_manifest(
                    op_type
                ),
                error_mapper=mapper,
            )
            for op_type in QUALITY_EVALUATOR_OPERATION_TYPES
        ),
    )
