"""
LaunchKart AI 2.0 — Request Logging Middleware

Logs every HTTP request with timing, status codes, and structured metadata.
Generates unique request IDs for tracing.
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs all HTTP requests with timing and tracing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        # Attach request ID to request state
        request.state.request_id = request_id

        # Skip logging for health checks, static assets, CORS preflight, and WebSocket upgrades
        path = request.url.path
        if path in ("/health", "/favicon.ico") or request.method == "OPTIONS":
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        logger.info(
            "Request started",
            request_id=request_id,
            method=request.method,
            path=path,
            client=request.client.host if request.client else "unknown",
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Request failed",
                request_id=request_id,
                method=request.method,
                path=path,
                duration_ms=round(duration_ms, 2),
            )
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id

        log_method = logger.info if response.status_code < 400 else logger.warning
        log_method(
            "Request completed",
            request_id=request_id,
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

        return response
