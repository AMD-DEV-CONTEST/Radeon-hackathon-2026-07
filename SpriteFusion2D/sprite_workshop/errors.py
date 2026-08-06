"""User-facing errors with stable exit codes.

Every error carries a structured ``code``/``message``/``details`` triple so the
CLI can map it to an exit code and a frontend can react to the code without
parsing English or Chinese prose (BACKEND_CLI_PLAN.md 9.5).
"""

from __future__ import annotations

from typing import Any, Mapping


class ExitCode:
    """Exit codes from BACKEND_CLI_PLAN.md 9.5."""

    OK = 0
    USAGE = 2
    NOT_FOUND = 3
    FAILED = 4
    BACKEND_UNAVAILABLE = 5
    PARTIAL = 6
    REFUSED = 7


class WorkshopError(Exception):
    """Base class for every error a user can legitimately trigger."""

    code = ExitCode.FAILED

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: Mapping[str, Any] = details

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details) or None,
        }


class UsageError(WorkshopError):
    """Invalid arguments, invalid spec, or contradictory options."""

    code = ExitCode.USAGE


class NotFoundError(WorkshopError):
    """A project, asset, frame, or file does not exist or is unreadable."""

    code = ExitCode.NOT_FOUND


class OperationError(WorkshopError):
    """Image processing or a project transaction failed."""

    code = ExitCode.FAILED


class BackendUnavailableError(WorkshopError):
    """An optional dependency is missing or a device is unavailable."""

    code = ExitCode.BACKEND_UNAVAILABLE


class RefusedError(WorkshopError):
    """Refused to overwrite, path escaped the project, or the lock is held."""

    code = ExitCode.REFUSED


class CancelledError(WorkshopError):
    """A queued or running background operation was cancelled by the user."""

    code = ExitCode.PARTIAL
