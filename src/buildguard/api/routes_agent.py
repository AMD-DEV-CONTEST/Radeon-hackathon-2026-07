"""Agent HTTP routes."""

import json
from collections.abc import Iterator
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from buildguard.agent.graph import BuildGuardAgent
from buildguard.integration.service import MvpWorkflow

CHAT_HEARTBEAT_SECONDS = 5.0


def _public_agent_state(raw: dict[str, Any]) -> dict[str, Any]:
    """Expose the graph state through the established chat/UI result contract."""

    state = dict(raw)
    state["inspections"] = state.get("inspection_results", [])
    state["risks"] = state.get("risk_results", [])
    plan = state.get("plan")
    if isinstance(plan, BaseModel):
        state["plan"] = plan.model_dump(mode="json")
    visual_evidence = state.get("visual_evidence")
    if isinstance(visual_evidence, list):
        state["visual_evidence"] = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in visual_evidence
        ]
    for result in reversed(state.get("tool_results", [])):
        output = getattr(result, "output", None)
        if output is None and isinstance(result, dict):
            output = result.get("output")
        if not isinstance(output, dict):
            continue
        for key in (
            "event_ids",
            "report_id",
            "report_path",
            "html_path",
            "pdf_path",
            "verified_citation_count",
        ):
            if output.get(key) is not None:
                state[key] = output[key]
        if output.get("report_path") is not None:
            break
    return state


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    session_id: str | None = None
    action: Literal["inspect", "high_risk", "report", "history", "event_report"] | None = None
    image_paths: list[Path] = Field(default_factory=list, max_length=1000)


class ConfirmationRequest(BaseModel):
    task_id: str
    approved: bool


def create_agent_router(
    agent: BuildGuardAgent,
    workflow: MvpWorkflow | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/agent", tags=["agent"])

    def execute_chat(
        request: ChatRequest,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_session_id = session_id or request.session_id
        if request.action == "inspect" and not request.image_paths:
            raise ValueError(
                "inspect action requires at least one image_path or video attachment path"
            )
        agent_kwargs: dict[str, Any] = {"task_id": task_id}
        if request.action is not None:
            agent_kwargs["requested_action"] = request.action
        if request.image_paths:
            agent_kwargs["image_paths"] = request.image_paths
        state = _public_agent_state(dict(
            agent.chat(
                request.message,
                resolved_session_id,
                **agent_kwargs,
            )
        ))
        if (
            request.action == "event_report"
            and state.get("status") == "WAIT_FOR_CONFIRMATION"
            and workflow is not None
            and workflow.event_provider is not None
        ):
            state["event_ids"] = [item.id for item in workflow.event_provider()]
        return state

    def sse(event: str, payload: dict[str, Any]) -> str:
        data = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
        return f"event: {event}\ndata: {data}\n\n"

    def sse_keepalive() -> str:
        """Keep the transport alive without emitting a user-visible event."""
        return ": keep-alive\n\n"

    @router.post("/chat")
    def chat(request: ChatRequest) -> dict[str, Any]:
        try:
            return execute_chat(request)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/chat/stream")
    def stream_chat(request: ChatRequest) -> StreamingResponse:
        session_id = request.session_id or str(uuid4())
        task_id = str(uuid4())

        def generate() -> Iterator[str]:
            yield sse(
                "accepted",
                {"session_id": session_id, "task_id": task_id},
            )
            action = request.action or ("inspect" if request.image_paths else "auto")
            has_video = any(
                path.suffix.casefold() in {".mp4", ".avi", ".mov", ".mkv"}
                for path in request.image_paths
            )
            action_label = {
                "auto": "自动规划",
                "inspect": "视频巡检" if has_video else "图片巡检",
                "high_risk": "高风险查询",
                "report": "巡检报告生成",
                "history": "历史查询",
                "event_report": "事件报告生成",
            }.get(action, action)
            yield sse(
                "phase",
                {
                    "session_id": session_id,
                    "task_id": task_id,
                    "phase": "executing",
                    "status": "running",
                    "message": f"正在执行{action_label}任务…",
                },
            )
            outcomes: Queue[tuple[str, dict[str, Any]]] = Queue(maxsize=1)

            def run_task() -> None:
                try:
                    result = execute_chat(
                        request,
                        session_id=session_id,
                        task_id=task_id,
                    )
                    outcomes.put(("complete", result))
                except Exception as exc:  # noqa: BLE001 - streamed as a bounded error event
                    outcomes.put(
                        (
                            "error",
                            {
                                "session_id": session_id,
                                "task_id": task_id,
                                "message": str(exc),
                                "retryable": not isinstance(
                                    exc,
                                    (ValueError, PermissionError),
                                ),
                            },
                        )
                    )

            worker = Thread(
                target=run_task,
                name=f"chat-stream-{task_id}",
                daemon=True,
            )
            worker.start()
            while True:
                try:
                    event_name, result = outcomes.get(timeout=CHAT_HEARTBEAT_SECONDS)
                    break
                except Empty:
                    yield sse_keepalive()
            worker.join(timeout=0)
            if event_name == "error":
                yield sse("error", result)
                return
            if result.get("status") == "WAIT_FOR_CONFIRMATION":
                yield sse(
                    "confirmation_required",
                    {
                        "session_id": session_id,
                        "task_id": task_id,
                        "pending_confirmation": result.get("pending_confirmation"),
                    },
                )
            yield sse("complete", result)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/confirm")
    def confirm(request: ConfirmationRequest) -> dict[str, Any]:
        try:
            # Both Agent and the deterministic workflow persist tasks in the same
            # SQLite table.  Route by the Agent's persisted state marker instead
            # of treating every stored task as an MVP workflow report task.
            if agent.get_task(request.task_id) is not None:
                return _public_agent_state(
                    dict(agent.confirm(request.task_id, request.approved))
                )
            if workflow is not None:
                return workflow.confirm(request.task_id, request.approved)
            return dict(agent.confirm(request.task_id, request.approved))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        state = agent.get_task(task_id)
        if state is None and workflow is not None:
            stored = workflow.memory.get_task(task_id)
            if stored is not None:
                return stored.model_dump(mode="json")
        if state is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return _public_agent_state(dict(state))

    return router
