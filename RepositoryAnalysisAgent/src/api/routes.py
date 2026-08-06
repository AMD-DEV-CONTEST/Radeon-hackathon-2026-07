"""FastAPI routes for RepositoryAnalysisAgent.

All endpoints are prefixed with /api. The chat endpoint uses SSE streaming.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..agent.engine import AgentEngine, AgentEvent, EventType, AgentConfig
from ..agent.context import BUDGET_16K, BUDGET_32K, budget_for_context_len
from ..backend import ChatMessage
from ..config import Config
from .schemas import (
    ChatRequest,
    IndexRequest,
    IndexStatusResponse,
    IndexStatsSchema,
    HealthResponse,
    WorkspaceEntry,
    WorkspaceTreeResponse,
    FileContentResponse,
    SessionListResponse,
    SessionDetailResponse,
)

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Shared application state injected into route handlers."""
    config: Config
    backend: Any  # LLMBackend
    indexer: Any  # Indexer
    reranker: Any  # RerankerModel | None
    registry: Any  # ToolRegistry
    sessions: Any  # SessionManager
    repo_path: str = "."


def create_router(state: AppState) -> APIRouter:
    router = APIRouter(prefix="/api")

    # ── Chat (SSE streaming) ──

    @router.post("/chat")
    async def chat(request: ChatRequest):
        """Stream agent responses via Server-Sent Events."""
        repo_path = request.repo_path or state.repo_path

        # Get or create session
        session_id = request.session_id
        if session_id is None:
            session_id = state.sessions.create_session()

        # Load conversation history
        history_msgs = state.sessions.get_messages(session_id)
        history: list[ChatMessage] = []
        for m in history_msgs:
            history.append(ChatMessage(role=m["role"], content=m["content"]))

        # Save user message
        state.sessions.add_message(session_id, "user", request.message)

        async def event_stream():
            full_response_parts: list[str] = []
            try:
                budget = budget_for_context_len(state.config.llm.max_model_len)
                agent_cfg = AgentConfig(
                    max_iterations=state.config.agent.max_iterations,
                    temperature=state.config.agent.temperature,
                    top_p=state.config.agent.top_p,
                    max_tokens=4096,
                    context_budget=budget,
                )

                engine = AgentEngine(
                    backend=state.backend,
                    registry=state.registry,
                    repo_path=repo_path,
                    config=agent_cfg,
                )

                async for event in engine.run(request.message, history):
                    sse = event.to_sse()
                    if event.type in (EventType.TEXT, EventType.DONE):
                        if event.content:
                            full_response_parts.append(event.content)
                    yield sse

                # Save assistant response
                full_response = "".join(full_response_parts).strip()
                if full_response:
                    state.sessions.add_message(session_id, "assistant", full_response)

            except Exception as e:
                logger.error("Chat error: %s", e, exc_info=True)
                error_event = AgentEvent(
                    type=EventType.ERROR,
                    content=f"Internal error: {e}",
                )
                yield error_event.to_sse()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Session-Id": session_id,
            },
        )

    # ── Indexing ──

    @router.post("/index")
    async def trigger_index(request: IndexRequest):
        """Trigger repository indexing (runs in background thread)."""
        if state.indexer.is_indexing:
            return {"status": "already_indexing", "message": "Indexing already in progress"}

        def run_index_sync():
            """Synchronous indexing — must run in a thread to avoid blocking the event loop."""
            try:
                state.config.repo_root = request.repo_path
                state.repo_path = request.repo_path
                stats = state.indexer.index_repository(request.repo_path, force=request.force)
                logger.info("Indexing done: %s", stats)
            except Exception as e:
                logger.error("Indexing failed: %s", e, exc_info=True)

        # Run in a thread pool so the blocking indexing doesn't freeze the event loop
        asyncio.get_event_loop().run_in_executor(None, run_index_sync)

        return {"status": "started", "repo_path": request.repo_path}

    @router.get("/index/status", response_model=IndexStatusResponse)
    async def index_status():
        stats = state.indexer.last_stats
        return IndexStatusResponse(
            is_indexing=state.indexer.is_indexing,
            chunk_count=state.indexer.chunk_count,
            last_stats=IndexStatsSchema(
                files_indexed=stats.files_indexed,
                files_skipped=stats.files_skipped,
                chunks_created=stats.chunks_created,
                elapsed_seconds=stats.elapsed_seconds,
                errors=stats.errors,
            ) if stats else None,
        )

    # ── Health ──

    @router.get("/health", response_model=HealthResponse)
    async def health():
        llm_ok = await state.backend.health()
        gpu_ok = False
        gpu_name = ""
        try:
            import torch
            if torch.cuda.is_available():
                gpu_ok = True
                gpu_name = torch.cuda.get_device_name(0)
        except ImportError:
            pass

        return HealthResponse(
            status="ok" if llm_ok else "degraded",
            llm_available=llm_ok,
            llm_model=state.config.llm.model,
            gpu_available=gpu_ok,
            gpu_name=gpu_name,
            indexing=state.indexer.is_indexing,
            chunk_count=state.indexer.chunk_count,
            backend=state.config.llm.backend,
        )

    # ── Workspace ──

    @router.get("/workspace/tree", response_model=WorkspaceTreeResponse)
    async def workspace_tree(path: str = "."):
        root = Path(state.repo_path).resolve()
        target = (root / path).resolve()
        if not str(target).startswith(str(root)):
            raise HTTPException(403, "Path outside repository root")
        if not target.is_dir():
            raise HTTPException(404, "Directory not found")

        entries: list[WorkspaceEntry] = []
        exclude = set(state.config.index.exclude_dirs)
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.name in exclude or entry.name.startswith("."):
                continue
            entries.append(WorkspaceEntry(
                name=entry.name,
                is_dir=entry.is_dir(),
                size=entry.stat().st_size if entry.is_file() else 0,
            ))
        return WorkspaceTreeResponse(path=path, entries=entries)

    @router.get("/workspace/file", response_model=FileContentResponse)
    async def read_file(path: str):
        root = Path(state.repo_path).resolve()
        target = (root / path).resolve()
        if not str(target).startswith(str(root)):
            raise HTTPException(403, "Path outside repository root")
        if not target.is_file():
            raise HTTPException(404, "File not found")

        content = target.read_text(encoding="utf-8", errors="replace")
        return FileContentResponse(
            path=path,
            content=content,
            lines=len(content.split("\n")),
        )

    # ── Sessions ──

    @router.get("/sessions", response_model=SessionListResponse)
    async def list_sessions():
        sessions = state.sessions.list_sessions()
        return SessionListResponse(
            sessions=[{"session_id": s["session_id"], "created_at": s["created_at"],
                        "message_count": s["message_count"], "title": s["title"]}
                      for s in sessions]
        )

    @router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
    async def get_session(session_id: str):
        messages = state.sessions.get_messages(session_id)
        if not messages:
            raise HTTPException(404, "Session not found")
        return SessionDetailResponse(session_id=session_id, messages=messages)

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        deleted = state.sessions.delete_session(session_id)
        if not deleted:
            raise HTTPException(404, "Session not found")
        return {"status": "deleted"}

    return router
