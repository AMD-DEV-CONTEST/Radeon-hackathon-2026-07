"""HTTP middleware package."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from middleware.logging import RequestLoggingMiddleware
from middleware.request_context import RequestContextMiddleware


def register_middleware(app: FastAPI) -> None:
    """Register application middleware in the correct order."""
    # Starlette executes middleware in reverse add order.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


__all__ = [
    "RequestContextMiddleware",
    "RequestLoggingMiddleware",
    "register_middleware",
]
