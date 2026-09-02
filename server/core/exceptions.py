"""Domain exceptions for service-layer error handling.

Services raise these instead of FastAPI ``HTTPException``. Global handlers in
``core.exception_handlers`` map them to HTTP responses without leaking
transport concerns into business logic.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error."""

    status_code: int = 500
    code: str = "app_error"

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        errors: list[Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        self.headers = headers
        self.errors = errors or []


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"
