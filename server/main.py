"""AgentVox FastAPI application entrypoint.

Wires lifespan (agents), middleware, exception handlers, and versioned API
routers. Run with ``uv run main.py``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from agents.registry import get_agent_registry
from api import api_router
from core.config import settings
from core.constants import HEALTH_PATH
from core.exception_handlers import register_exception_handlers
from core.logger import logger
from middleware import register_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)

    registry = get_agent_registry()
    await registry.initialize_all()
    logger.info(
        "Starting %s [%s] on %s:%s | agents=%s",
        settings.app_name,
        settings.app_env,
        settings.host,
        settings.port,
        [agent.agent_type.value for agent in registry.all()],
    )
    try:
        yield
    finally:
        await registry.shutdown_all()
        logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description=(
            "AgentVox backend API — auth, CRUD, agents, LangGraph workflows, "
            "and realtime websockets."
        ),
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    register_middleware(app)
    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get(HEALTH_PATH, tags=["health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe for orchestrators and load balancers."""
        return {"status": "ok", "service": settings.app_name}

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        """API root welcome payload."""
        return {"message": f"Welcome to {settings.app_name} API"}

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
