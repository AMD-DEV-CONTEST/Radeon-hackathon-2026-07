"""RepositoryAnalysisAgent server: FastAPI application entry point.

Wires together config, backend, indexer, reranker, tools, and routes.
Serves the web UI from static/ and the API from /api.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import get_config, Config
from .backend import create_backend
from .index.indexer import Indexer
from .index.reranker import RerankerModel
from .tools.registry import ToolRegistry
from .tools.search import register_search_tools
from .tools.files import register_file_tools
from .tools.ast_tools import register_ast_tools
from .tools.exec import register_exec_tools
from .session.manager import SessionManager
from .api.routes import create_router, AppState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("raa")


def create_app(config_path: str = "config.yaml", repo_path: str = ".") -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config(config_path)
    config.repo_root = repo_path

    app = FastAPI(
        title="RepositoryAnalysisAgent",
        description="Privacy-first local code repository intelligence agent",
        version="0.1.0",
    )

    # ── Core components ──
    logger.info("Initializing RepositoryAnalysisAgent (backend=%s, model=%s)",
                config.llm.backend, config.llm.model)

    backend = create_backend(config.llm)
    indexer = Indexer(config)
    reranker = RerankerModel(config.reranker)

    # ── Tool registry ──
    registry = ToolRegistry()
    register_search_tools(registry, indexer, reranker)
    register_file_tools(registry, config)
    register_ast_tools(registry, config, indexer)
    register_exec_tools(registry, config)

    # ── Session manager ──
    sessions = SessionManager(
        persist_dir=config.session.persist_dir,
        max_recent=config.session.max_recent,
    )

    # ── API routes ──
    state = AppState(
        config=config,
        backend=backend,
        indexer=indexer,
        reranker=reranker,
        registry=registry,
        sessions=sessions,
        repo_path=repo_path,
    )
    app.include_router(create_router(state))

    # ── Static frontend ──
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/")
        async def index():
            return FileResponse(str(static_dir / "index.html"))

    # ── CORS (localhost only — privacy-first) ──
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://{config.server.host}:{config.server.port}",
                       "http://localhost", "http://127.0.0.1"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    # Store state in app for access from CLI
    app.state.raa = state

    logger.info("RepositoryAnalysisAgent ready at http://%s:%d", config.server.host, config.server.port)
    return app


def main():
    """CLI entry point: python -m src.server [repo_path] [--config path] [--port N]"""
    import argparse

    parser = argparse.ArgumentParser(description="RepositoryAnalysisAgent server")
    parser.add_argument("repo_path", nargs="?", default=".",
                        help="Path to the repository to analyze")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--host", default=None, help="Override bind host")
    parser.add_argument("--port", type=int, default=None, help="Override port")
    args = parser.parse_args()

    config = get_config(args.config)
    host = args.host or config.server.host
    port = args.port or config.server.port

    app = create_app(args.config, args.repo_path)

    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
