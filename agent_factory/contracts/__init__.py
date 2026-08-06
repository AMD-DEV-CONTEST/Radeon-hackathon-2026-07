"""Runtime-independent contracts shared by orchestration layers."""

from agent_factory.contracts.background_tasks import (
    ACTIVE_TASK_STATUSES,
    BACKGROUND_TASK_STATUSES,
    BACKGROUND_TASK_TYPES,
    LEASE_TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    BackgroundTask,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskType,
    can_transition_task,
    task_request_fingerprint,
)
from agent_factory.contracts.errors import (
    ConflictError,
    DomainError,
    DomainValidationError,
    NotFoundError,
    ServiceUnavailableError,
    TaskCancelledError,
)
from agent_factory.contracts.events import EventEnvelope

__all__ = [
    "ACTIVE_TASK_STATUSES",
    "BACKGROUND_TASK_STATUSES",
    "BACKGROUND_TASK_TYPES",
    "LEASE_TASK_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "BackgroundTask",
    "BackgroundTaskResult",
    "BackgroundTaskStatus",
    "BackgroundTaskType",
    "ConflictError",
    "DomainError",
    "DomainValidationError",
    "EventEnvelope",
    "NotFoundError",
    "ServiceUnavailableError",
    "TaskCancelledError",
    "can_transition_task",
    "task_request_fingerprint",
]
