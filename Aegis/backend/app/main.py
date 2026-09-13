"""
Aegis backend application entrypoint.

Responsibilities of this module, and only this module:
  - Build the FastAPI app via a factory (testable — tests can build fresh app instances).
  - Wire cross-cutting concerns: logging, CORS, exception translation, request-id middleware.
  - Mount the versioned API router.

No business logic lives here.
"""
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AegisError
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "app.startup",
        environment=settings.ENVIRONMENT,
        inference_backend=settings.INFERENCE_BASE_URL,
    )
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="Autonomous, on-prem, multi-agent incident commander running on AMD ROCm.",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        """Binds a request_id to every log line emitted while handling this request,
        and records request latency — the first building block of the observability
        story that Phase 13 extends with full tracing."""
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response

    @app.exception_handler(AegisError)
    async def aegis_error_handler(request: Request, exc: AegisError) -> JSONResponse:
        logger.warning(
            "app.error",
            code=exc.code,
            message=exc.message,
            path=request.url.path,
        )
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "app.unhandled_error",
            error=str(exc),
            error_type=type(exc).__name__,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {} if settings.is_production else {"exception": str(exc)},
                }
            },
        )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # Exposes /metrics in Prometheus format — feeds the GPU/agent benchmarking
    # dashboard built in Phase 14.
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    return app


app = create_app()
