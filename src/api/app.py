"""FastAPI application factory and entrypoint.

Why a factory: lets tests spin up an isolated `app` instance with overridden
dependencies, and lets the Gradio UI mount this same app under a sub-path
without a second uvicorn process.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import log
from src.core.pipeline_factory import load_default_registry


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup / shutdown hooks. Keeps things cheap — model load is lazy."""
    log.info("api startup: loading model registry")
    load_default_registry()
    log.info("api ready: %s", app.title)
    yield
    log.info("api shutdown")


def create_app() -> FastAPI:
    """Build the FastAPI app with all routes mounted.

    Routes are added in D2/D3/D4 as capabilities come online. For now we
    ship a `/healthz` so the app is runnable end-to-end.
    """
    app = FastAPI(
        title="AMD Radeon Studio API",
        version="0.1.0",
        description="多模态 AI 创作工坊 — 文生图 / 图生图 / 风格迁移",
        lifespan=_lifespan,
    )

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict:
        """Liveness probe — returns 200 OK if the process is up."""
        return {"status": "ok", "version": app.version}

    # Mount capability routes. Each is a no-op placeholder until D2-D4 lands.
    # Uncomment as the corresponding module is implemented.
    # from src.api.routes import text2image, img2img, style
    # app.include_router(text2image.router, prefix="/api/text2image", tags=["text2image"])
    # app.include_router(img2img.router,  prefix="/api/img2img",  tags=["img2img"])
    # app.include_router(style.router,    prefix="/api/style",    tags=["style"])

    return app


# Module-level instance for `uvicorn src.api.app:app`
app = create_app()


def run() -> None:  # pragma: no cover — exercised by `radeon-studio-api` script
    """CLI entrypoint: `uv run radeon-studio-api`."""
    import uvicorn
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
