"""FastAPI service: Insurance RAG Agent Web interface.

The FastAPI app is created via the factory function create_app(), convenient for testing and reuse.

Refer to the pattern of lesson 25 integrated_agent_service/app/api.py:
- StaticFiles for mounting static assets
- StreamingResponse for SSE streaming output
- Factory function + lifespan for lifecycle management
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.api.models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SessionHistoryResponse,
    SessionListResponse,
)

logger = logging.getLogger(__name__)

# Static assets root directory: project root / static
STATIC_ROOT = Path(__file__).resolve().parent.parent.parent / "static"

# Five-step business flow stages (consistent with the TriggerFlow chunks in flow.py)
PIPELINE_STAGES: list[tuple[str, str]] = [
    ("understand", "Understanding"),
    ("plan", "Planning"),
    ("validate", "Validating"),
    ("retrieve", "Retrieving"),
    ("answer", "Answering"),
]


def _format_sse(data: dict[str, Any]) -> str:
    """Serialize a dictionary into an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_trace_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Build a compact trace summary from the query() result."""
    return {
        "task_id": result.get("task_id"),
        "execution_id": result.get("execution_id"),
        "query_type": result.get("query_type"),
        "status": result.get("status"),
        "citation_count": len(result.get("citations", [])),
        "source_count": len(result.get("sources", [])),
        "observation_summary": result.get("observation_summary"),
        "trace_event_count": len(result.get("trace_events", [])),
    }


class AgentHolder:
    """Singleton container with lazy initialization of the InsuranceAgent.

    Avoids loading heavy dependencies such as Agently / FAISS at import time, and makes it convenient to inject mocks in tests.
    """

    def __init__(self) -> None:
        self._agent: Any = None
        self._init_lock = asyncio.Lock()
        self._init_error: str | None = None

    async def get(self) -> Any:
        """Get (and initialize if necessary) the InsuranceAgent instance."""
        if self._agent is not None:
            return self._agent
        async with self._init_lock:
            if self._agent is not None:
                return self._agent
            try:
                from src.agent.main import InsuranceAgent

                agent = InsuranceAgent()
                # lazy initialization of RAG (degrades to pure LLM mode when the index is missing)
                try:
                    agent.init_rag()
                    logger.info("RAG retriever initialization complete")
                except FileNotFoundError as e:
                    logger.warning("RAG not initialized, running in pure LLM mode: %s", e)
                except Exception as e:
                    logger.warning("RAG initialization exception, running in pure LLM mode: %s", e)
                self._agent = agent
            except Exception as e:
                self._init_error = str(e)
                logger.error("InsuranceAgent initialization failed: %s", e, exc_info=True)
                raise
        return self._agent

    @property
    def ready(self) -> bool:
        return self._agent is not None

    @property
    def rag_ready(self) -> bool:
        agent = self._agent
        if agent is None:
            return False
        return getattr(agent, "_rag_retriever", None) is not None

    @property
    def model_info(self) -> dict[str, Any]:
        agent = self._agent
        if agent is None:
            return {"status": "not_initialized"}
        models_cfg = getattr(agent, "models_cfg", {})
        return {
            "chat": models_cfg.get("chat", {}).get("model", "unknown"),
            "embedding": models_cfg.get("embedding", {}).get("model", "unknown"),
            "reasoning": models_cfg.get("reasoning", {}).get("model", "unknown"),
            "rag_ready": self.rag_ready,
        }


def create_app(agent: Any = None, static_root: Path | None = None) -> FastAPI:
    """Create a FastAPI application instance.

    Args:
        agent: optional InsuranceAgent instance. When None, initialize lazily (created on first request).
        static_root: static assets root directory, defaults to project root / static.

    Returns:
        a configured FastAPI application.
    """
    app = FastAPI(
        title="Insurance RAG Agent",
        description="Insurance intelligent Q&A Agent — orchestrated by the Agently TriggerFlow five-step business flow",
        version="1.0.0",
    )

    # CORS middleware (local development)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Agent container
    holder = AgentHolder()
    if agent is not None:
        holder._agent = agent

    # Static assets
    root = static_root or STATIC_ROOT
    if root.exists():
        app.mount("/static", StaticFiles(directory=str(root)), name="static")

    # ── Health check ──
    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            rag_ready=holder.rag_ready,
            model_info=holder.model_info,
        )

    # ── Synchronous chat interface ──
    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        try:
            insurance_agent = await holder.get()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Agent not ready: {e}") from e

        # RAG readiness check: log a warning when RAG is not initialized (the request is still allowed, but citations may be empty)
        if not holder.rag_ready:
            logger.warning(
                "[/api/chat] RAG not ready, request will be handled in pure LLM mode (session=%s): %s",
                request.session_id, request.message[:80],
            )

        try:
            result = await insurance_agent.query(request.message, request.session_id)
        except Exception as e:
            logger.error("query failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"query processing failed: {e}") from e

        return ChatResponse(
            answer=result.get("answer", ""),
            citations=result.get("citations", []),
            sources=result.get("sources", []),
            source_details=result.get("source_details", []),
            status=result.get("status", "unknown"),
            trace_summary=_build_trace_summary(result),
        )

    # ── SSE streaming chat interface ──
    @app.post("/api/chat/stream")
    async def chat_stream(request: ChatRequest) -> StreamingResponse:
        """SSE streaming interface: push the five-step business flow stage progress and the final answer in real time.

        Event format (refer to the lesson 25 SSE pattern)::

            data: {"type": "stage", "stage": "understand", "status": "started"}
            data: {"type": "stage", "stage": "understand", "status": "completed"}
            data: {"type": "answer", "content": "...", "citations": [...]}
            data: {"type": "done"}
        """

        async def event_stream() -> AsyncIterator[str]:
            # get the Agent
            try:
                insurance_agent = await holder.get()
            except Exception as e:
                yield _format_sse({"type": "error", "message": f"Agent not ready: {e}"})
                yield _format_sse({"type": "done"})
                return

            # start the real query in the background (the TriggerFlow five-step flow executes inside query())
            query_task = asyncio.create_task(
                insurance_agent.query(request.message, request.session_id)
            )

            yield _format_sse({"type": "stage", "stage": "pipeline", "status": "started"})

            # push progress stage by stage (corresponding to understand→plan→validate→fetch→answer in flow.py)
            for stage_key, stage_label in PIPELINE_STAGES:
                if query_task.done():
                    break
                yield _format_sse({
                    "type": "stage",
                    "stage": stage_key,
                    "label": stage_label,
                    "status": "started",
                })
                # visualize the stage progress while detecting whether the query has completed
                sleep_task = asyncio.create_task(asyncio.sleep(0.6))
                done, _pending = await asyncio.wait(
                    {query_task, sleep_task},
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=0.8,
                )
                if sleep_task in done:
                    pass  # normal timeout, continue to the next stage
                if query_task.done():
                    break
                yield _format_sse({
                    "type": "stage",
                    "stage": stage_key,
                    "label": stage_label,
                    "status": "completed",
                })

            # wait for the real query to complete
            try:
                result = await query_task
            except Exception as e:
                logger.error("streaming query failed: %s", e, exc_info=True)
                yield _format_sse({"type": "error", "message": f"query processing failed: {e}"})
                yield _format_sse({"type": "done"})
                return

            # push the final answer
            yield _format_sse({
                "type": "answer",
                "content": result.get("answer", ""),
                "citations": result.get("citations", []),
                "sources": result.get("sources", []),
                "source_details": result.get("source_details", []),
                "status": result.get("status", "unknown"),
                "trace_summary": _build_trace_summary(result),
            })
            yield _format_sse({"type": "done"})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Session history ──
    @app.get(
        "/api/sessions/{session_id}/history",
        response_model=SessionHistoryResponse,
    )
    async def session_history(session_id: str) -> SessionHistoryResponse:
        try:
            insurance_agent = await holder.get()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Agent not ready: {e}") from e

        registry = getattr(insurance_agent, "session_registry", None)
        if registry is None:
            return SessionHistoryResponse(
                session_id=session_id, history=[], session_ids=[]
            )

        session_ids: list[str] = []
        if hasattr(registry, "get_all_session_ids"):
            session_ids = registry.get_all_session_ids()

        history: list[dict[str, Any]] = []
        session = registry._sessions.get(session_id) if hasattr(registry, "_sessions") else None
        if session is not None:
            context_window = getattr(session, "context_window", [])
            if context_window:
                for item in context_window:
                    if isinstance(item, dict):
                        history.append(item)
                    else:
                        history.append({"role": "unknown", "content": str(item)})
            memo = getattr(session, "memo", {})
            if isinstance(memo, dict) and memo:
                history.append({"role": "system", "content": json.dumps(memo, ensure_ascii=False)})

        return SessionHistoryResponse(
            session_id=session_id,
            history=history,
            session_ids=session_ids,
        )

    # ── Recent session list (top5 + model topic) ──
    @app.get("/api/sessions", response_model=SessionListResponse)
    async def sessions_list() -> SessionListResponse:
        """Return the recent top-5 sessions and the topics distilled by the model.

        The topic is generated by the main model, limited to 15 tokens.
        On generation failure, fall back to a truncated first user question.
        """
        try:
            insurance_agent = await holder.get()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Agent not ready: {e}") from e

        sessions = await insurance_agent.list_recent_sessions(limit=5)
        return SessionListResponse(sessions=sessions)

    # ── IM webhook route (optional integration) ──
    from src.api.im_router import IMRouter

    im_router = IMRouter(holder)

    @app.post("/api/im/webhook")
    async def im_webhook(
        payload: dict[str, Any],
        platform: str = "wecom",
    ) -> dict[str, Any]:
        """Receive an IM platform webhook callback, route to the Agent and return a platform-format response."""
        try:
            return await im_router.dispatch(payload, platform=platform)
        except Exception as e:
            logger.error("IM webhook processing failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"IM processing failed: {e}") from e

    # ── Frontend homepage ──
    @app.get("/", response_class=FileResponse, include_in_schema=False)
    async def index() -> FileResponse:
        index_path = root / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="index.html not found")
        return FileResponse(str(index_path))

    return app