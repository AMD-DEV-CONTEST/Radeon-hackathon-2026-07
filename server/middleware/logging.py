"""HTTP access-logging middleware."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log method, path, status, duration, and request ID."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        request_id = getattr(request.state, "request_id", "-")
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
