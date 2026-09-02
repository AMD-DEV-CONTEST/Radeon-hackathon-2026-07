"""Stable model execution contracts for backend business workflows."""

from services.model_execution.compatibility import (
    LegacyLLMCompatibilityGateway,
    get_default_gateway,
)
from services.model_execution.gateway import ModelExecutionGateway, execute_sync
from services.model_execution.requests import ModelTaskRequest, sanitize_client_metadata
from services.model_execution.results import (
    ModelTaskResult,
    NormalizedProviderResponse,
    NormalizedUsage,
    normalize_provider_response,
    normalize_usage,
)
from services.model_execution.task_types import (
    CANONICAL_TASK_TYPES,
    LEGACY_TASK_ALIASES,
    TaskTypeResolution,
    accepted_task_types,
    resolve_task_type,
    task_type_catalog,
)

__all__ = [
    "LegacyLLMCompatibilityGateway",
    "ModelExecutionGateway",
    "ModelTaskRequest",
    "ModelTaskResult",
    "NormalizedProviderResponse",
    "NormalizedUsage",
    "CANONICAL_TASK_TYPES",
    "LEGACY_TASK_ALIASES",
    "TaskTypeResolution",
    "accepted_task_types",
    "execute_sync",
    "get_default_gateway",
    "sanitize_client_metadata",
    "normalize_provider_response",
    "normalize_usage",
    "resolve_task_type",
    "task_type_catalog",
]
