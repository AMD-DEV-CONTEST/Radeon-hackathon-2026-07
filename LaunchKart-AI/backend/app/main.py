"""
LaunchKart AI 2.0 — FastAPI Application Factory

Creates and configures the FastAPI application with all middleware,
exception handlers, routes, and lifecycle events.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import get_settings
from app.exceptions import LaunchKartError
from app.infrastructure.database.session import engine
from app.infrastructure.logging.logger import set_correlation_id, setup_logging
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

settings = get_settings()

# Initialize structured logging
setup_logging(env=settings.app_env, debug=settings.is_development)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager — startup and shutdown events."""
    logger.info(
        "Starting LaunchKart AI 2.0",
        env=settings.app_env,
        host=settings.app_host,
        port=settings.app_port,
    )

    # Create upload directory
    settings.upload_path.mkdir(parents=True, exist_ok=True)

    # Initialize database tables (auto-create for SQLite / Docker-less setup)
    from app.infrastructure.database.session import init_db
    await init_db()

    logger.info("Application startup complete")
    yield

    # Shutdown
    logger.info("Shutting down LaunchKart AI 2.0")
    await engine.dispose()
    logger.info("Application shutdown complete")


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Autonomous AI E-commerce Team powered by AMD Radeon GPUs",
        version="2.0.0",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
        default_response_class=JSONResponse,
        lifespan=lifespan,
    )

    # ---- Middleware (order matters — outermost first) ----
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Mount static uploads directory for serving uploaded product images to frontend
    app.mount("/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")

    # ---- Exception Handlers ----
    @app.exception_handler(LaunchKartError)
    async def launchkart_error_handler(request: Request, exc: LaunchKartError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": True,
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "message": "An unexpected internal error occurred",
                "detail": str(exc) if settings.is_development else None,
            },
        )

    # ---- Routes ----
    app.include_router(api_router, prefix="/api")

    # ---- Health Check ----
    @app.get("/health", tags=["System"])
    async def health_check() -> dict[str, str]:
        return {"status": "healthy", "service": settings.app_name, "version": "2.0.0"}

    return app


app = create_application()
