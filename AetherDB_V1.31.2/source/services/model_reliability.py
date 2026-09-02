"""Standard model errors, bounded retry, and explicit fallback policy."""

import asyncio
from dataclasses import dataclass
from enum import Enum


class ModelErrorCode(str, Enum):
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    PROVIDER_5XX = "PROVIDER_5XX"
    AUTH_FAILED = "AUTH_FAILED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_DISABLED = "MODEL_DISABLED"
    MODEL_UNSUPPORTED_TASK = "MODEL_UNSUPPORTED_TASK"
    CONTEXT_TOO_LONG = "CONTEXT_TOO_LONG"
    INVALID_INPUT_FORMAT = "INVALID_INPUT_FORMAT"
    OUTPUT_SCHEMA_INVALID = "OUTPUT_SCHEMA_INVALID"
    CONTENT_FILTERED = "CONTENT_FILTERED"
    LOCAL_SERVICE_NOT_RUNNING = "LOCAL_SERVICE_NOT_RUNNING"
    LOCAL_RESOURCE_INSUFFICIENT = "LOCAL_RESOURCE_INSUFFICIENT"
    PRIVACY_BLOCKED = "PRIVACY_BLOCKED"
    COST_BLOCKED = "COST_BLOCKED"
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"
    USER_CANCELLED = "USER_CANCELLED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


RETRYABLE_CODES = {
    ModelErrorCode.NETWORK_ERROR,
    ModelErrorCode.TIMEOUT,
    ModelErrorCode.PROVIDER_5XX,
    ModelErrorCode.RATE_LIMITED,
}


class FallbackPolicy(str, Enum):
    NEVER = "never"
    ASK = "ask"
    AUTO_SAME_PRIVACY = "auto_same_privacy"
    AUTO_SAME_COST_OR_LOWER = "auto_same_cost_or_lower"


class ModelExecutionError(RuntimeError):
    def __init__(
        self,
        code: ModelErrorCode,
        message: str = "Model execution failed",
        *,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class FallbackRequired(ModelExecutionError):
    def __init__(
        self,
        cause: ModelExecutionError,
        candidate_model_ids: tuple[str, ...],
        source_model_profile_id: str | None = None,
    ):
        super().__init__(cause.code, "Fallback requires user confirmation")
        self.cause = cause
        self.candidate_model_ids = candidate_model_ids
        self.source_model_profile_id = source_model_profile_id


def normalize_model_error(exc: Exception) -> ModelExecutionError:
    if isinstance(exc, ModelExecutionError):
        return exc
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in type(exc).__name__.lower():
        return ModelExecutionError(ModelErrorCode.TIMEOUT)
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status in {401, 403}:
        return ModelExecutionError(ModelErrorCode.AUTH_FAILED)
    if status == 404:
        return ModelExecutionError(ModelErrorCode.MODEL_NOT_FOUND)
    if status == 429:
        retry_after = getattr(exc, "retry_after", None)
        try:
            retry_after = float(retry_after) if retry_after is not None else None
        except (TypeError, ValueError):
            retry_after = None
        return ModelExecutionError(ModelErrorCode.RATE_LIMITED, retry_after=retry_after)
    if isinstance(status, int) and status >= 500:
        return ModelExecutionError(ModelErrorCode.PROVIDER_5XX)
    if isinstance(exc, ConnectionError) or "connection" in type(exc).__name__.lower():
        return ModelExecutionError(ModelErrorCode.NETWORK_ERROR)
    return ModelExecutionError(ModelErrorCode.UNKNOWN_ERROR)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay_seconds: float = 0.25
    max_retry_after_seconds: float = 5.0

    def should_retry(self, error: ModelExecutionError, attempt: int) -> bool:
        if attempt >= self.max_attempts or error.code not in RETRYABLE_CODES:
            return False
        if error.code is ModelErrorCode.RATE_LIMITED and error.retry_after is not None:
            return 0 <= error.retry_after <= self.max_retry_after_seconds
        return True

    def delay_seconds(self, error: ModelExecutionError, attempt: int) -> float:
        if error.retry_after is not None:
            return min(error.retry_after, self.max_retry_after_seconds)
        return min(5.0, self.base_delay_seconds * (2 ** (attempt - 1)))
