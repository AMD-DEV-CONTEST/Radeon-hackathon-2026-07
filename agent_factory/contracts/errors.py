"""Structured domain errors for orchestration services."""

from __future__ import annotations

from typing import Any


class DomainError(RuntimeError):
    code = "domain_error"

    def __init__(self, user_message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.user_message, "details": self.details}


class NotFoundError(DomainError):
    code = "not_found"


class ConflictError(DomainError):
    code = "conflict"


class DomainValidationError(DomainError):
    code = "validation_error"


class ServiceUnavailableError(DomainError):
    code = "service_unavailable"


class TaskCancelledError(DomainError):
    code = "task_cancelled"
