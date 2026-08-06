"""FastAPI application factory for PolicyCut.

Mounts the /api/v1 routers, a permissive CORS policy for local development,
and the static web frontend at ``/`` (mounted last so API routes win).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


def _version() -> str:
    try:
        import policycut

        return getattr(policycut, "__version__", "1.0.0")
    except Exception:  # pragma: no cover - defensive
        return "1.0.0"


def create_app() -> FastAPI:
    """Create the PolicyCut FastAPI app with store/queue/settings on app.state."""
    from policycut.config import get_settings
    from policycut.core.queue import JobQueue
    from policycut.core.storage import ProjectStore

    from policycut.api import artifacts, events, jobs, projects, system

    settings = get_settings()
    store = ProjectStore(Path(settings.data_dir))
    try:
        queue = JobQueue()
    except TypeError:
        # Tolerate a constructor that wants the store.
        queue = JobQueue(store)  # type: ignore[call-arg]

    app = FastAPI(title="PolicyCut", version=_version())
    app.state.store = store
    app.state.queue = queue
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        recover = getattr(queue, "recover", None)
        if callable(recover):
            try:
                recover(store)
            except Exception:
                logger.exception("job queue recovery failed")
        start = getattr(queue, "start", None)
        if callable(start):
            try:
                start()
            except Exception:
                logger.debug("job queue start() failed or not needed", exc_info=True)

    for module in (system, projects, jobs, events, artifacts):
        app.include_router(module.router, prefix="/api/v1")

    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    if static_dir.is_dir():
        # Mounted last so /api/v1 routes take precedence.
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        logger.warning("static frontend directory missing: %s", static_dir)

        @app.get("/")
        def _root() -> dict:
            return {"app": "PolicyCut", "version": _version(), "api": "/api/v1"}

    return app


app = create_app()
