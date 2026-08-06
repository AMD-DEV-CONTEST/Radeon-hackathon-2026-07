"""Adapters from existing runtimes to the unified background-task lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from agent_factory.collaboration_system.task_service import TaskExecutionContext, TaskExecutor
from agent_factory.collaboration_system.progress_summary import progress_summary_session
from agent_factory.contracts import BackgroundTask, BackgroundTaskResult
from agent_factory.create_agent.runtime import CreateAgentRuntime
from agent_factory.evolution.runtime import AgentEvolutionRuntime
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.runtime_events import (
    INTERRUPT_TERMINAL_EVENT_TYPES,
    RUN_TERMINAL_EVENT_TYPES,
    runtime_stream_status,
)
from agent_factory.runtime_kernel.session import COLLABORATION_WORKER_SESSION_KIND


@dataclass(frozen=True, slots=True)
class RuntimeBundle:
    agent_package_runtime: AgentPackageRuntimeManager
    create_agent_runtime: CreateAgentRuntime
    evolution_runtime: AgentEvolutionRuntime

    def task_executors(self) -> dict[str, TaskExecutor]:
        return {
            "sub_agent": SubAgentTaskExecutor(self.agent_package_runtime),
            "manufacture": ManufactureTaskExecutor(self.create_agent_runtime),
            "evolve": EvolutionTaskExecutor(self.evolution_runtime),
        }


class SubAgentTaskExecutor:
    def __init__(self, runtime: AgentPackageRuntimeManager) -> None:
        self.runtime = runtime

    def run(self, task: BackgroundTask, context: TaskExecutionContext) -> BackgroundTaskResult:
        package_id = _required(task.assignee_package_id, "assignee_package_id")
        payload = dict(task.payload)
        session_id = task.assignee_session_id

        def start(request_id: str) -> Any:
            run = self.runtime.stream(
                package_id,
                user_input=task.task_text,
                session_id=session_id,
                request_id=request_id,
                user_config=_dict(payload.get("user_config")),
                runtime_request=_dict(payload.get("runtime_request")),
                attachments=payload.get("attachments"),
                workdir_root=_path(payload.get("workdir_root")),
                session_kind=COLLABORATION_WORKER_SESSION_KIND,
                visible_in_agent_session_list=True,
            )
            resolved_session_id = str(run.session.get("session_id") or "").strip()
            if resolved_session_id and resolved_session_id != task.assignee_session_id:
                context.update_task(assignee_session_id=resolved_session_id)
            return run

        def resume(request_id: str, resume_payload: dict[str, Any]) -> Any:
            resolved_session_id = _required(task.assignee_session_id, "assignee_session_id")
            return self.runtime.resume_stream(
                package_id,
                session_id=resolved_session_id,
                resume_payload=resume_payload,
                request_id=request_id,
                runtime_request=_dict(payload.get("runtime_request")),
                workdir_root=_path(payload.get("workdir_root")),
            )

        return _consume_runtime(
            task,
            context,
            start=start,
            resume=resume,
            cancel=lambda request_id, reason: self.runtime.cancel_active_requests(
                reason=reason,
                request_id=request_id,
                package_id=package_id,
                session_id=task.assignee_session_id,
            ),
        )


class ManufactureTaskExecutor:
    def __init__(self, runtime: CreateAgentRuntime) -> None:
        self.runtime = runtime

    def run(self, task: BackgroundTask, context: TaskExecutionContext) -> BackgroundTaskResult:
        payload = dict(task.payload)
        session_id = task.assignee_session_id or f"manufacture_{task.task_id}"
        if task.assignee_session_id is None:
            context.update_task(assignee_session_id=session_id)
        return _consume_runtime(
            task,
            context,
            start=lambda request_id: self.runtime.stream(
                user_input=task.task_text,
                session_id=session_id,
                request_id=request_id,
                attachments=payload.get("attachments"),
                user_config=_dict(payload.get("user_config")),
            ),
            resume=lambda request_id, resume_payload: self.runtime.resume_stream(
                session_id=session_id,
                resume_payload=resume_payload,
                request_id=request_id,
            ),
            cancel=lambda request_id, reason: self.runtime.cancel_active_requests(
                reason=reason,
                request_id=request_id,
            ),
        )


class EvolutionTaskExecutor:
    def __init__(self, runtime: AgentEvolutionRuntime) -> None:
        self.runtime = runtime

    def run(self, task: BackgroundTask, context: TaskExecutionContext) -> BackgroundTaskResult:
        package_id = _required(task.assignee_package_id, "assignee_package_id")
        payload = dict(task.payload)
        session_id = task.assignee_session_id or f"evolve_{task.task_id}"
        if task.assignee_session_id is None:
            context.update_task(assignee_session_id=session_id)
        return _consume_runtime(
            task,
            context,
            start=lambda request_id: self.runtime.stream(
                package_id=package_id,
                user_input=task.task_text,
                request_id=request_id,
                session_id=session_id,
                attachments=payload.get("attachments"),
                user_config=_dict(payload.get("user_config")),
            ),
            resume=lambda request_id, resume_payload: self.runtime.resume_stream(
                package_id=package_id,
                session_id=session_id,
                resume_payload=resume_payload,
                request_id=request_id,
            ),
            cancel=lambda request_id, reason: self.runtime.cancel_active_requests(
                reason=reason,
                request_id=request_id,
            ),
        )


def _consume_runtime(
    task: BackgroundTask,
    context: TaskExecutionContext,
    *,
    start: Callable[[str], Any],
    resume: Callable[[str, dict[str, Any]], Any],
    cancel: Callable[[str, str], int],
) -> BackgroundTaskResult:
    resume_state = dict(task.resume_payload or {})
    request_id = str(resume_state.get("runtime_request_id") or task.request_id)
    runtime_resume_payload = _dict(resume_state.get("resume"))
    current_request = {"id": request_id}
    context.register_cancel_callback(
        lambda reason: cancel(str(current_request["id"]), reason)
    )
    run = resume(request_id, runtime_resume_payload) if resume_state else start(request_id)
    current_request["id"] = str(getattr(run, "request_id", request_id) or request_id)
    final_event: FactoryFrontendEvent | None = None
    summaries: list[str] = []
    artifacts: list[dict[str, Any]] = []
    progress = progress_summary_session(task.type, task.task_text)
    events = getattr(run, "events")
    try:
        for item in _frontend_events(events):
            context.raise_if_interrupted()
            final_event = item
            report = progress.observe(item)
            if report is not None:
                context.submit_progress(report)
            _collect_result(item, summaries, artifacts)
            if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
                interrupt_payload = {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "request_id": item.request_id,
                    "payload": dict(item.payload or {}),
                }
                if item.event_type == "tool_approval_requested":
                    context.suspend_for_approval(
                        interrupt_payload,
                        request_id=str(item.payload.get("approval_id") or item.event_id),
                    )
                else:
                    context.suspend_for_external(interrupt_payload, request_id=item.event_id)
            if item.event_type in RUN_TERMINAL_EVENT_TYPES:
                finish_status = str(item.payload.get("finish_status") or item.payload.get("status") or "")
                if item.event_type == "run_completed" and finish_status == "waiting_for_workers":
                    context.suspend_for_external(
                        {
                            "event_id": item.event_id,
                            "event_type": "waiting_for_workers",
                            "request_id": item.request_id,
                            "payload": dict(item.payload or {}),
                        },
                        request_id=item.event_id,
                    )
                break
    finally:
        close = getattr(events, "close", None)
        if callable(close):
            close()

    if final_event is None:
        return BackgroundTaskResult(
            status="failed",
            summary="运行没有产生事件。",
            error={"code": "empty_runtime_stream"},
        )
    report = progress.flush(final_event)
    if report is not None:
        context.submit_progress(report)
    if final_event.event_type not in RUN_TERMINAL_EVENT_TYPES:
        return BackgroundTaskResult(
            status="failed",
            summary="运行流在没有终态事件的情况下结束。",
            artifacts=artifacts,
            error={"code": "runtime_stream_without_terminal_event"},
        )
    status = runtime_stream_status(final_event)
    if status == "cancelled":
        return BackgroundTaskResult(
            status="cancelled",
            summary=_summary(summaries, "任务已取消。"),
            artifacts=artifacts,
        )
    if status == "failed":
        return BackgroundTaskResult(
            status="failed",
            summary=_summary(summaries, "任务执行失败。"),
            artifacts=artifacts,
            error={
                "code": "runtime_failed",
                "message": final_event.message or "运行失败。",
                "payload": dict(final_event.payload or {}),
            },
        )
    return BackgroundTaskResult(
        status="succeeded",
        summary=_summary(summaries, "任务执行完成。"),
        artifacts=artifacts,
        result={
            "runtime_event": final_event.model_dump(mode="json"),
            "request_id": final_event.request_id,
            "session_id": final_event.session_id,
        },
    )


def _frontend_events(events: Iterator[tuple[str, Any]]) -> Iterator[FactoryFrontendEvent]:
    for stream_mode, raw in events:
        if stream_mode != "frontend_event":
            continue
        yield raw if isinstance(raw, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(raw)


def _collect_result(
    item: FactoryFrontendEvent,
    summaries: list[str],
    artifacts: list[dict[str, Any]],
) -> None:
    if item.message and item.event_type in {"node_completed", "run_completed", "run_failed", "run_cancelled"}:
        summaries.append(str(item.message))
    payload = item.payload if isinstance(item.payload, dict) else {}
    for artifact in payload.get("artifacts") or []:
        if isinstance(artifact, dict):
            artifacts.append(dict(artifact))


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _path(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser() if text else None


def _required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _summary(values: list[str], fallback: str) -> str:
    for value in reversed(values):
        if value.strip():
            return value.strip()
    return fallback
