"""
Application-wide exception hierarchy.

Every raised exception carries a machine-readable `code` (stable, used by the
frontend and by API consumers to branch on error type) and an `http_status`,
so the FastAPI exception handler (registered in main.py) can translate any
AegisError into a consistent JSON error envelope without per-endpoint boilerplate.
"""
from typing import Any, Dict, Optional


class AegisError(Exception):
    """Base class for all application-raised (as opposed to unexpected) errors."""

    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class NotFoundError(AegisError):
    code = "not_found"
    http_status = 404


class ValidationError(AegisError):
    code = "validation_error"
    http_status = 422


class AuthenticationError(AegisError):
    code = "authentication_error"
    http_status = 401


class AuthorizationError(AegisError):
    code = "authorization_error"
    http_status = 403


class ConflictError(AegisError):
    code = "conflict"
    http_status = 409


class RateLimitedError(AegisError):
    code = "rate_limited"
    http_status = 429


class InferenceEngineError(AegisError):
    """Raised when the local ROCm/vLLM inference backend is unreachable or errors."""

    code = "inference_engine_error"
    http_status = 502


class AgentExecutionError(AegisError):
    """Raised when a LangGraph agent node fails after exhausting its retry policy."""

    code = "agent_execution_error"
    http_status = 500


class ToolExecutionError(AegisError):
    """Raised when an agent tool call fails (e.g. remediation action rejected)."""

    code = "tool_execution_error"
    http_status = 502
