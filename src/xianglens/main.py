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
from xianglens.auth import SessionIssueLimiter, SessionTokenError, SessionTokenManager
from xianglens.config import Settings, get_settings
from xianglens.services import AppServices, create_services


def create_app(settings: Settings | None = None, services: AppServices | None = None) -> FastAPI:
    settings = settings or get_settings()
    permanent_key = settings.app_api_key.get_secret_value()
    session_tokens = None
    if settings.public_sessions_enabled and permanent_key:
        session_tokens = SessionTokenManager(permanent_key, settings.access_token_ttl_minutes)

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
    app.state.session_tokens = session_tokens
    app.state.session_limiter = SessionIssueLimiter(settings.session_issue_limit_per_minute)

    @app.middleware("http")
    async def api_key_gate(request: Request, call_next):
        # CORS preflight requests do not include the application API key. Let the
        # CORS middleware validate their origin before authenticating the real call.
        if (
            request.method != "OPTIONS"
            and request.url.path.startswith("/api/v1")
            and request.url.path != "/api/v1/session"
            and settings.auth_enabled
        ):
            supplied_key = request.headers.get("X-App-API-Key", "")
            if permanent_key and secrets.compare_digest(permanent_key, supplied_key):
                request.state.auth_mode = "permanent_key"
                request.state.session_user_id = None
                return await call_next(request)

            authorization = request.headers.get("Authorization", "")
            scheme, _, token = authorization.partition(" ")
            if session_tokens is not None and scheme.lower() == "bearer" and token:
                try:
                    claims = session_tokens.verify(token)
                except SessionTokenError:
                    pass
                else:
                    request.state.auth_mode = "access_session"
                    request.state.session_user_id = claims.session_id
                    request.state.session_token_id = claims.token_id
                    return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"detail": "A valid access session is required"},
                headers={
                    "WWW-Authenticate": "Bearer",
                    "Cache-Control": "no-store",
                },
            )
        return await call_next(request)

    # Starlette executes the most recently registered middleware first. Register
    # CORS after the authentication gate so even direct 401 responses include
    # Access-Control-Allow-Origin instead of appearing as opaque browser errors.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    uvicorn.run("xianglens.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
