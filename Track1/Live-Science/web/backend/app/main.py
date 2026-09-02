"""Live-Science web backend — FastAPI application.

Run:
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import health, jobs
from app.auth import router as auth_router, require_token
from app.config import (
    AUTH_ENABLED,
    CORS_ORIGINS,
    DB_PATH,
    FRONTEND_DIST,
    SERVE_FRONTEND,
)
from app.services.job_manager import JobManager
from app.storage import JobStore

logger = logging.getLogger("uvicorn.error")


class _RedactAccessTokenFilter(logging.Filter):
    """Mask access_token query params in uvicorn access logs (no token leak)."""

    _RE = re.compile(r"(access_token=)[^&\" ]+")

    @staticmethod
    def _redact(value: str) -> str:
        return _RedactAccessTokenFilter._RE.sub(r"\1***", value)

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn's AccessFormatter rebuilds the request line from record.args
        # (client_addr, method, full_path, http_version, status_code); the
        # token lives in full_path. Redact the tuple so it never reaches the
        # formatted log line.
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._redact(a) if isinstance(a, str) else a for a in record.args
            )
        for attr in ("msg", "message", "request_line"):
            val = getattr(record, attr, None)
            if isinstance(val, str):
                setattr(record, attr, self._redact(val))
        return True


# uvicorn.access exists after uvicorn configures logging; attach a filter so
# every access-log line (including artifact requests that carry ?access_token=)
# is redacted before formatting.
logging.getLogger("uvicorn.access").addFilter(_RedactAccessTokenFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = JobStore(DB_PATH)
    manager = JobManager(store)
    manager.start()
    app.state.manager = manager
    if AUTH_ENABLED:
        logger.info("Auth enabled. Access token available via LIVE_SCIENCE_AUTH_TOKEN or data/auth_token.txt")
    else:
        logger.warning(
            "Auth DISABLED (LIVE_SCIENCE_AUTH_DISABLED=1) — public URLs will be unprotected!"
        )
    yield
    # allow in-flight work to finish (bounded), then cancel the worker
    await manager.shutdown()


app = FastAPI(
    title="Live-Science API",
    description="Document -> LearningSpec -> animation/video generation web API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public: token login only.
app.include_router(auth_router)
# Everything else under /api/v1 requires a valid token.
app.include_router(jobs.router, dependencies=[Depends(require_token)])
app.include_router(health.router, dependencies=[Depends(require_token)])


if not (SERVE_FRONTEND and FRONTEND_DIST.is_dir()):
    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": "Live-Science API",
            "docs": "/docs",
            "health": "/api/v1/health",
            "jobs": "/api/v1/jobs",
        }


if SERVE_FRONTEND and FRONTEND_DIST.is_dir():
    # Register the static mount AFTER the API routers so /api/* keeps
    # priority, but BEFORE any catch-all root route (which is skipped when
    # the frontend is served, so "/" returns the SPA).
    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIST), html=True),
        name="frontend",
    )
