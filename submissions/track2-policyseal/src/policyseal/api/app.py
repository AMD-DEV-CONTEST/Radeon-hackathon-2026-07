from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from policyseal import __version__
from policyseal.api.dependencies import AppServices
from policyseal.api.routes import approvals, copilot, revisions, tasks
from policyseal.config import get_settings
from policyseal.domain.errors import PolicySealError


def create_app(services: AppServices | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PolicySeal API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.services = services

    @app.exception_handler(KeyError)
    async def not_found_handler(_request: Request, _error: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "not_found", "message": "Resource not found."}},
        )

    async def controlled_error_handler(_request: Request, error: Exception) -> JSONResponse:
        code = type(error).__name__.replace("Error", "").casefold()
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": code,
                    "message": "The requested operation is not allowed in the current state.",
                }
            },
        )

    app.add_exception_handler(PolicySealError, controlled_error_handler)
    app.add_exception_handler(ValueError, controlled_error_handler)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "policyseal-api",
            "version": __version__,
            "environment": settings.environment,
            "inference": "local",
        }

    app.include_router(tasks.router)
    app.include_router(revisions.router)
    app.include_router(approvals.router)
    app.include_router(copilot.router)

    return app


app = create_app()
