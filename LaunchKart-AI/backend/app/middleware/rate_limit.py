"""
LaunchKart AI 2.0 — Rate Limiting Middleware

In-memory sliding window rate limiter per client IP.
Uses Redis in production for distributed rate limiting.
"""

from __future__ import annotations

import time
from collections import defaultdict

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.exceptions import RateLimitExceededError

logger = structlog.get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter.
    
    In development mode, uses in-memory tracking.
    In production, this should be backed by Redis for distributed deployments.
    """

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()

        # Skip rate limiting for health checks and CORS preflight
        if request.url.path in ("/health",) or request.method == "OPTIONS":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = settings.rate_limit_window_seconds
        max_requests = settings.rate_limit_requests

        # Clean old entries outside the window
        self._requests[client_ip] = [
            ts for ts in self._requests[client_ip] if ts > now - window
        ]

        if len(self._requests[client_ip]) >= max_requests:
            logger.warning(
                "Rate limit exceeded",
                client=client_ip,
                requests=len(self._requests[client_ip]),
                window=window,
            )
            raise RateLimitExceededError(
                detail={
                    "limit": max_requests,
                    "window_seconds": window,
                    "retry_after": window,
                }
            )

        self._requests[client_ip].append(now)

        response = await call_next(request)

        # Add rate limit headers
        remaining = max_requests - len(self._requests[client_ip])
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now + window))

        return response
