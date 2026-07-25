"""FastAPI application entry point."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from xianglens import __version__
from xianglens.api.routes import router
from xianglens.config import Settings, get_settings
from xianglens.services import AppServices, create_services


def create_app(settings: Settings | None = None, services: AppServices | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services or create_services(settings)
        if settings.llm_probe_on_start and settings.model_configured:
            reachable = await app.state.services.model.health()
            logging.getLogger(__name__).info("Self-hosted model reachable: %s", reachable)
        yield

    app = FastAPI(
        title="XiangLens API",
        version=__version__,
        description="Private, source-backed profile-image analysis.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def api_key_gate(request: Request, call_next):
        # CORS preflight requests do not include the application API key. Let the
        # CORS middleware validate their origin before authenticating the real call.
        if (
            request.method != "OPTIONS"
            and request.url.path.startswith("/api/v1")
            and settings.auth_enabled
        ):
            configured = settings.app_api_key.get_secret_value()
            supplied = request.headers.get("X-App-API-Key", "")
            if not configured or not secrets.compare_digest(configured, supplied):
                return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
        return await call_next(request)

    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    uvicorn.run("xianglens.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
