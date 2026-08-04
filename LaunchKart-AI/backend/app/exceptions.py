"""
LaunchKart AI 2.0 — Custom Exception Hierarchy

Structured exceptions for clean error handling across all layers.
Each exception maps to a specific HTTP status code.
"""

from __future__ import annotations

from typing import Any


class LaunchKartError(Exception):
    """Base exception for all LaunchKart errors."""

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        detail: Any = None,
        status_code: int = 500,
    ) -> None:
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(self.message)


# ---- Authentication Errors ----


class AuthenticationError(LaunchKartError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed", detail: Any = None) -> None:
        super().__init__(message=message, detail=detail, status_code=401)


class AuthorizationError(LaunchKartError):
    """Raised when user lacks required permissions."""

    def __init__(self, message: str = "Insufficient permissions", detail: Any = None) -> None:
        super().__init__(message=message, detail=detail, status_code=403)


class TokenExpiredError(AuthenticationError):
    """Raised when JWT token has expired."""

    def __init__(self) -> None:
        super().__init__(message="Token has expired")


class InvalidTokenError(AuthenticationError):
    """Raised when JWT token is malformed or invalid."""

    def __init__(self) -> None:
        super().__init__(message="Invalid or malformed token")


# ---- Resource Errors ----


class NotFoundError(LaunchKartError):
    """Raised when a requested resource is not found."""

    def __init__(self, resource: str = "Resource", resource_id: str = "") -> None:
        detail = {"resource": resource, "id": resource_id} if resource_id else {"resource": resource}
        super().__init__(
            message=f"{resource} not found",
            detail=detail,
            status_code=404,
        )


class ConflictError(LaunchKartError):
    """Raised when a resource already exists or state conflict occurs."""

    def __init__(self, message: str = "Resource conflict", detail: Any = None) -> None:
        super().__init__(message=message, detail=detail, status_code=409)


class ValidationError(LaunchKartError):
    """Raised when input validation fails."""

    def __init__(self, message: str = "Validation error", detail: Any = None) -> None:
        super().__init__(message=message, detail=detail, status_code=422)


# ---- Service Errors ----


class ServiceUnavailableError(LaunchKartError):
    """Raised when an external service is unavailable."""

    def __init__(self, service: str = "External service", detail: Any = None) -> None:
        super().__init__(
            message=f"{service} is currently unavailable",
            detail=detail,
            status_code=503,
        )


class RateLimitExceededError(LaunchKartError):
    """Raised when rate limit is exceeded."""

    def __init__(self, detail: Any = None) -> None:
        super().__init__(
            message="Rate limit exceeded. Please try again later.",
            detail=detail,
            status_code=429,
        )


# ---- AI / Agent Errors ----


class AgentExecutionError(LaunchKartError):
    """Raised when an AI agent fails during execution."""

    def __init__(self, agent_name: str, message: str = "", detail: Any = None) -> None:
        super().__init__(
            message=f"Agent '{agent_name}' execution failed: {message}",
            detail=detail,
            status_code=500,
        )


class ModelNotAvailableError(ServiceUnavailableError):
    """Raised when the required AI model is not available."""

    def __init__(self, model_name: str) -> None:
        super().__init__(
            service=f"AI Model '{model_name}'",
            detail={"model": model_name, "hint": "Ensure the model is pulled in Ollama"},
        )


class GPUNotAvailableError(LaunchKartError):
    """Raised when AMD GPU / ROCm is not detected."""

    def __init__(self) -> None:
        super().__init__(
            message="AMD GPU with ROCm support not detected. Falling back to CPU inference.",
            detail={"hint": "Install ROCm drivers and ensure GPU is properly configured"},
            status_code=200,  # Not a failure, just a warning
        )


# ---- File Errors ----


class FileUploadError(LaunchKartError):
    """Raised when file upload fails."""

    def __init__(self, message: str = "File upload failed", detail: Any = None) -> None:
        super().__init__(message=message, detail=detail, status_code=400)


class FileTooLargeError(FileUploadError):
    """Raised when uploaded file exceeds size limit."""

    def __init__(self, max_size_mb: int) -> None:
        super().__init__(
            message=f"File exceeds maximum size of {max_size_mb}MB",
            detail={"max_size_mb": max_size_mb},
        )


class UnsupportedFileTypeError(FileUploadError):
    """Raised when uploaded file type is not supported."""

    def __init__(self, file_type: str, allowed_types: list[str]) -> None:
        super().__init__(
            message=f"File type '{file_type}' is not supported",
            detail={"file_type": file_type, "allowed_types": allowed_types},
        )


# ---- Launch Errors ----


class LaunchAlreadyRunningError(ConflictError):
    """Raised when trying to start a launch that's already running."""

    def __init__(self, launch_id: str) -> None:
        super().__init__(
            message="A launch is already in progress for this product",
            detail={"launch_id": launch_id},
        )


class LaunchNotRetryableError(LaunchKartError):
    """Raised when trying to retry a launch that can't be retried."""

    def __init__(self, launch_id: str, status: str) -> None:
        super().__init__(
            message=f"Launch cannot be retried in '{status}' state",
            detail={"launch_id": launch_id, "current_status": status},
            status_code=400,
        )
