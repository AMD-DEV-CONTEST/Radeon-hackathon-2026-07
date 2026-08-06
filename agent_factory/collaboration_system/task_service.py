"""One persistent scheduler and lifecycle for every background-task type."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Protocol
from uuid import uuid4

from agent_factory.collaboration_system.execution_registry import ExecutionRegistry, ManagedProcess
from agent_factory.collaboration_system.progress_summary import (
    ProgressReport,
    ProgressSummaryCandidate,
    ProgressSummaryDispatcher,
    deterministic_progress_report,
)
from agent_factory.collaboration_system.persistence import (
    EventRepository,
    SchedulerSettingsRepository,
    SessionRepository,
    TaskRepository,
    ensure_background_task_schema,
)
from agent_factory.collaboration_system.persistence.task_repository import utc_now_text
from agent_factory.contracts import (
    BACKGROUND_TASK_TYPES,
    BackgroundTask,
    BackgroundTaskResult,
    ConflictError,
    DomainValidationError,
    TaskCancelledError,
    TERMINAL_TASK_STATUSES,
)
from agent_factory.exception_details import exception_summary


DEFAULT_LEASE_SECONDS = 30
DEFAULT_MAX_LEASE_REQUEUES = 3
DISPATCH_POLL_SECONDS = 0.5


class TaskExecutor(Protocol):
    def run(self, task: BackgroundTask, context: "TaskExecutionContext") -> BackgroundTaskResult: ...


@dataclass(frozen=True, slots=True)
class TaskSuspended(RuntimeError):
    status: str
    request_id: str
    payload: dict[str, Any]


class TaskRequeueRequested(RuntimeError):
    pass


class TaskExecutionContext:
    """Executor capabilities fenced to a single task lease."""

    def __init__(
        self,
        *,
        task_id: str,
        session_id: str,
        cancel_event: threading.Event,
        shutdown_event: threading.Event,
        emit: Callable[[str, dict[str, Any]], dict[str, Any]],
        heartbeat: Callable[[], None],
        update_fields: Callable[[dict[str, Any]], None],
        register_cancel: Callable[[Callable[[str], None]], None],
        register_cleanup: Callable[[Callable[[], None]], None],
        register_process: Callable[[ManagedProcess], None],
        set_waiting: Callable[[str | None], None],
        submit_progress: Callable[[ProgressSummaryCandidate], bool],
    ) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.cancel_event = cancel_event
        self.shutdown_event = shutdown_event
        self._emit = emit
        self._heartbeat = heartbeat
        self._update_fields = update_fields
        self._register_cancel = register_cancel
        self._register_cleanup = register_cleanup
        self._register_process = register_process
        self._set_waiting = set_waiting
        self._submit_progress = submit_progress

    def raise_if_interrupted(self) -> None:
        if self.cancel_event.is_set():
            raise TaskCancelledError("后台任务已取消。", details={"task_id": self.task_id})
        if self.shutdown_event.is_set():
            raise TaskRequeueRequested("background-task service is stopping")

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._emit(event_type, dict(payload or {}))

    def report_progress(self, report: ProgressReport) -> dict[str, Any]:
        """Persist one user-facing semantic progress report for this task."""

        self.raise_if_interrupted()
        return self._emit("background_task_progress_report", report.model_dump(mode="json"))

    def submit_progress(self, candidate: ProgressSummaryCandidate) -> bool:
        return self._submit_progress(candidate)

    def heartbeat(self) -> None:
        self.raise_if_interrupted()
        self._heartbeat()

    def update_task(self, **fields: Any) -> None:
        self.raise_if_interrupted()
        self._update_fields(fields)

    def register_cancel_callback(self, callback: Callable[[str], None]) -> None:
        self._register_cancel(callback)

    def register_cleanup(self, callback: Callable[[], None]) -> None:
        self._register_cleanup(callback)

    def register_process(self, process: ManagedProcess) -> None:
        self._register_process(process)

    def suspend_for_approval(
        self,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> None:
        self.raise_if_interrupted()
        self._set_waiting("approval")
        raise TaskSuspended(
            status="waiting_approval",
            request_id=str(request_id or uuid4().hex),
            payload=dict(payload),
        )

    def suspend_for_external(
        self,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> None:
        self.raise_if_interrupted()
        self._set_waiting("external")
        raise TaskSuspended(
            status="waiting_external",
            request_id=str(request_id or uuid4().hex),
            payload=dict(payload),
        )


class BackgroundTaskService:
    """Application-scoped scheduler shared by sub-agent, manufacture and evolve."""

    def __init__(
        self,
        store_path: str | Path,
        executors: dict[str, TaskExecutor],
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_lease_requeues: int = DEFAULT_MAX_LEASE_REQUEUES,
        logger: logging.Logger | None = None,
    ) -> None:
        self.store_path = ensure_background_task_schema(store_path)
        required_types = BACKGROUND_TASK_TYPES
        if set(executors) != required_types:
            raise ValueError(
                "background-task executors must be exactly: " + ", ".join(sorted(required_types))
            )
        self.executors = dict(executors)
        self.tasks = TaskRepository(self.store_path)
        self.sessions = SessionRepository(self.store_path)
        self.events = EventRepository(self.store_path)
        self.settings = SchedulerSettingsRepository(self.store_path)
        self.registry = ExecutionRegistry()
        self.lease_seconds = max(5, int(lease_seconds))
        self.max_lease_requeues = max(1, int(max_lease_requeues))
        self.owner = f"{os.getpid()}:{uuid4().hex}"
        self.logger = logger or logging.getLogger(__name__)
        self.progress_summaries = ProgressSummaryDispatcher(logger=self.logger)
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._dispatcher: threading.Thread | None = None
        self._lifecycle_lock = threading.RLock()
        self._event_listeners: set[Callable[[dict[str, Any]], None]] = set()

    def create_session(self, **values: Any) -> dict[str, Any]:
        session, created = self.sessions.create(**values)
        if created:
            self._publish("background_task_session_created", session_id=str(session["session_id"]), payload={"session": session})
        return session

    def submit(self, **values: Any) -> BackgroundTask:
        task, created = self.tasks.create(**values)
        if created:
            self._publish_task("background_task_created", task, {"status": task.status, "type": task.type})
            self._wake_event.set()
        return task

    def get(self, task_id: str) -> BackgroundTask:
        return self.tasks.get(task_id)

    def list(self, **filters: Any) -> list[BackgroundTask]:
        return self.tasks.list(**filters)

    def configure_max_parallel_sub_agents(
        self,
        value: int,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, int | str]:
        settings = self.settings.update_max_parallel(value, expected_revision=expected_revision)
        self._wake_event.set()
        self._publish(
            "background_task_scheduler_configured",
            payload={"max_parallel_sub_agents": settings["max_parallel_sub_agents"]},
        )
        return settings

    def scheduler_settings(self) -> dict[str, int | str]:
        return self.settings.get()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._dispatcher is not None and self._dispatcher.is_alive():
                return
            self._stop_event.clear()
            self.progress_summaries.start()
            self._publish_recovery(self.tasks.recover_expired(max_requeues=self.max_lease_requeues))
            self._dispatcher = threading.Thread(
                target=self._dispatch_loop,
                name="background-task-dispatcher",
                daemon=True,
            )
            self._dispatcher.start()

    def stop(self, *, timeout: float = 15.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        dispatcher = self._dispatcher
        if dispatcher is not None and dispatcher is not threading.current_thread():
            dispatcher.join(timeout=max(0.0, float(timeout)))
        self.registry.request_shutdown_all()
        deadline = time.monotonic() + max(0.0, float(timeout))
        for task_id in self.registry.active_ids():
            remaining = max(0.0, deadline - time.monotonic())
            self.registry.reclaim(task_id, join_timeout=remaining)

    def cancel(self, task_id: str, *, reason: str = "user_cancelled") -> BackgroundTask:
        cancelled, changed = self.tasks.request_cancel(task_id, reason=reason)
        if cancelled.status == "cancelling":
            self.registry.request_cancel(cancelled.task_id, reason=reason)
        if not changed:
            return cancelled
        self._publish_task(
            "background_task_status_changed",
            cancelled,
            {"status": cancelled.status, "reason": reason},
        )
        self._wake_event.set()
        return cancelled

    def approve(
        self,
        task_id: str,
        *,
        decision: str,
        payload: dict[str, Any] | None = None,
    ) -> BackgroundTask:
        task = self.tasks.get(task_id)
        if task.status != "waiting_approval" or task.pending_approval is None:
            raise ConflictError(
                "后台任务当前不在等待批准状态。",
                details={"task_id": task_id, "status": task.status},
            )
        if decision not in {"approve", "deny", "trust_tool", "revise"}:
            raise DomainValidationError("审批动作无效。", details={"decision": decision})
        request_id = str(task.pending_approval.get("request_id") or "").strip()
        decision_payload = {**dict(payload or {}), "decision": decision}
        resume = {
            "runtime_request_id": task.pending_approval.get("runtime_request_id"),
            "resume": decision_payload,
        }
        queued = self.tasks.resolve_approval_and_queue(
            task.task_id,
            request_id=request_id,
            decision=decision,
            decision_payload=decision_payload,
            resume_payload=resume,
        )
        self._publish_task("background_task_approval_resolved", queued, decision_payload)
        self._wake_event.set()
        return queued

    def resume_external(self, task_id: str, payload: dict[str, Any]) -> BackgroundTask:
        task = self.tasks.get(task_id)
        pending = task.pending_external or {}
        queued = self.tasks.resolve_external_and_queue(
            task.task_id,
            resume_payload={
                "runtime_request_id": pending.get("runtime_request_id"),
                "resume": dict(payload),
            },
        )
        self._publish_task("background_task_external_resolved", queued, dict(payload))
        self._wake_event.set()
        return queued

    def resolve_interaction(
        self,
        task_id: str,
        *,
        interaction_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> BackgroundTask:
        task = self.tasks.get(task_id)
        pending = task.pending_approval if task.status == "waiting_approval" else task.pending_external
        pending_id = str((pending or {}).get("request_id") or "").strip()
        if not pending_id or pending_id != str(interaction_id or "").strip():
            raise ConflictError(
                "待处理交互不存在或已经被处理。",
                details={"task_id": task_id, "interaction_id": interaction_id},
            )
        if task.status == "waiting_approval":
            return self.approve(task_id, decision=action, payload=payload)
        if task.status != "waiting_external":
            raise ConflictError(
                "后台任务当前没有等待用户处理的交互。",
                details={"task_id": task_id, "status": task.status},
            )
        if action not in {"answer", "continue"}:
            raise DomainValidationError("等待交互动作无效。", details={"action": action})
        answer_payload = dict(payload)
        if action == "answer":
            answer = str(payload.get("answer") or payload.get("input_text") or "").strip()
            if not answer:
                raise DomainValidationError("回答内容不能为空。")
            answer_payload.update({"action": "answer", "answer": answer, "input_text": answer, "message": answer})
        else:
            answer_payload["action"] = "continue"
        return self.resume_external(task_id, answer_payload)

    def delete_task(self, task_id: str, *, timeout: float = 15.0) -> BackgroundTask:
        task = self.cancel(task_id, reason="delete_requested")
        deadline = time.monotonic() + max(0.0, float(timeout))
        while task.status not in TERMINAL_TASK_STATUSES or task.resources_released_at is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConflictError(
                    "后台任务仍在取消或资源回收中。",
                    details={"task_id": task_id, "status": task.status},
                )
            self.registry.reclaim(task_id, join_timeout=min(remaining, 0.25))
            time.sleep(min(remaining, 0.05))
            task = self.tasks.get(task_id)
        deleted = self.tasks.delete_reclaimed(task_id)
        self._publish(
            "background_task_deleted",
            session_id=deleted.session_id,
            payload={"task_id": deleted.task_id, "status": deleted.status},
        )
        return deleted

    def delete_session(self, session_id: str, *, timeout: float = 15.0) -> dict[str, Any]:
        self.sessions.mark_deleting(session_id)
        tasks = self._all_session_tasks(session_id)
        for task in tasks:
            if task.status not in TERMINAL_TASK_STATUSES:
                self.cancel(task.task_id, reason="session_delete_requested")
        deadline = time.monotonic() + max(0.0, float(timeout))
        try:
            while True:
                tasks = self._all_session_tasks(session_id)
                pending = [
                    task
                    for task in tasks
                    if task.status not in TERMINAL_TASK_STATUSES or task.resources_released_at is None
                ]
                if not pending:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ConflictError(
                        "后台任务会话仍在取消或资源回收中。",
                        details={"session_id": session_id, "task_ids": [task.task_id for task in pending]},
                    )
                for task in pending:
                    self.registry.reclaim(task.task_id, join_timeout=min(remaining, 0.1))
                time.sleep(min(remaining, 0.05))
            deleted = self.sessions.delete_reclaimed(session_id)
        except BaseException:
            self.sessions.restore_active(session_id)
            raise
        self._publish(
            "background_task_session_deleted",
            payload={"session_id": session_id, "task_count": len(tasks)},
        )
        return {**deleted, "deleted_task_count": len(tasks)}

    def add_event_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with self._lifecycle_lock:
            self._event_listeners.add(listener)

    def remove_event_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with self._lifecycle_lock:
            self._event_listeners.discard(listener)

    def _dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._publish_recovery(self.tasks.recover_expired(max_requeues=self.max_lease_requeues))
                self._signal_persisted_cancellations()
                setting = self.settings.get()
                claimed, dependency_failed = self.tasks.claim(
                    owner=self.owner,
                    max_parallel=int(setting["max_parallel_sub_agents"]),
                    lease_seconds=self.lease_seconds,
                )
                for task in dependency_failed:
                    self._publish_task(
                        "background_task_result",
                        task,
                        {"status": "failed", "error": task.error},
                    )
                for task in claimed:
                    self._publish_task("background_task_status_changed", task, {"status": "claimed"})
                    self._start_worker(task)
            except Exception:
                self.logger.exception("background-task dispatcher failed")
            self._wake_event.wait(DISPATCH_POLL_SECONDS)
            self._wake_event.clear()

    def _signal_persisted_cancellations(self) -> None:
        offset = 0
        while True:
            page = self.tasks.list(statuses=["cancelling"], limit=500, offset=offset)
            for task in page:
                self.registry.request_cancel(
                    task.task_id,
                    reason=task.cancel_reason or "cancel_requested",
                )
            if len(page) < 500:
                return
            offset += len(page)

    def _start_worker(self, task: BackgroundTask) -> None:
        if task.lease_owner is None or task.lease_token is None:
            raise RuntimeError(f"claimed task has no lease: {task.task_id}")
        handle = self.registry.register(
            task.task_id,
            lease_owner=task.lease_owner,
            lease_token=task.lease_token,
        )
        thread = threading.Thread(
            target=self._run_task,
            args=(task.task_id,),
            name=f"background-task-{task.task_id[:12]}",
            daemon=True,
        )
        self.registry.attach_thread(task.task_id, thread)
        try:
            thread.start()
        except BaseException:
            self.registry.reclaim(task.task_id, join_timeout=0)
            current = self.tasks.get(task.task_id)
            if current.status == "claimed":
                self.tasks.transition(
                    current.task_id,
                    to_status="queued",
                    lease_owner=task.lease_owner,
                    lease_token=task.lease_token,
                    fields={
                        "lease_owner": None,
                        "lease_token": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                    },
                )
            elif current.status == "cancelling":
                self.tasks.transition(
                    current.task_id,
                    to_status="cancelled",
                    lease_owner=task.lease_owner,
                    lease_token=task.lease_token,
                    fields={
                        "lease_owner": None,
                        "lease_token": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                        "completed_at": utc_now_text(),
                        "resources_released_at": utc_now_text(),
                    },
                )
            raise

    def _run_task(self, task_id: str) -> None:
        handle = self.registry.get(task_id)
        if handle is None:
            return
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(task_id, handle.lease_owner, handle.lease_token, heartbeat_stop),
            name=f"background-task-heartbeat-{task_id[:12]}",
            daemon=True,
        )
        terminal = False
        suspension: TaskSuspended | None = None
        requeue_reason: str | None = None
        try:
            task = self.tasks.transition(
                task_id,
                to_status="running",
                lease_owner=handle.lease_owner,
                lease_token=handle.lease_token,
                fields={"started_at": utc_now_text()},
            )
            self._publish_task("background_task_status_changed", task, {"status": "running"})
            heartbeat_thread.start()
            context = self._execution_context(task, handle)
            result = self.executors[task.type].run(task, context)
            context.raise_if_interrupted()
            if result.status == "succeeded":
                self._finish_success(task_id, handle.lease_owner, handle.lease_token, result)
            elif result.status == "cancelled":
                self._finish_cancelled(task_id, handle.lease_owner, handle.lease_token)
            else:
                self._finish_failed(
                    task_id,
                    handle.lease_owner,
                    handle.lease_token,
                    result.error or {"code": "executor_failed", "message": result.summary or "后台任务执行失败。"},
                )
            terminal = True
        except TaskSuspended as caught_suspension:
            suspension = caught_suspension
        except TaskRequeueRequested:
            requeue_reason = "service_stopping"
        except TaskCancelledError:
            self._finish_cancelled(task_id, handle.lease_owner, handle.lease_token)
            terminal = True
        except Exception as exc:
            self.logger.exception("background task failed: %s", task_id)
            self._finish_failed(
                task_id,
                handle.lease_owner,
                handle.lease_token,
                {
                    "code": "executor_error",
                    "message": exception_summary(exc),
                    "details": {"type": type(exc).__name__},
                },
            )
            terminal = True
        finally:
            heartbeat_stop.set()
            if heartbeat_thread.is_alive():
                heartbeat_thread.join(timeout=2.0)
            reclaimed = self.registry.reclaim(task_id, join_timeout=0)
            if reclaimed:
                try:
                    if suspension is not None:
                        self._suspend(
                            task_id,
                            handle.lease_owner,
                            handle.lease_token,
                            suspension,
                            resources_released_at=utc_now_text(),
                        )
                    elif requeue_reason is not None:
                        self._requeue(
                            task_id,
                            handle.lease_owner,
                            handle.lease_token,
                            reason=requeue_reason,
                            resources_released_at=utc_now_text(),
                        )
                    else:
                        released = self.tasks.mark_resources_released(task_id)
                        self._publish_task(
                            "background_task_resources_released",
                            released,
                            {"terminal": terminal},
                        )
                except ConflictError:
                    self.logger.warning("task outcome could not be persisted after resource cleanup: %s", task_id)
            else:
                self.logger.error("task resources could not be reclaimed: %s", task_id)
            self._wake_event.set()

    def _execution_context(self, task: BackgroundTask, handle: Any) -> TaskExecutionContext:
        return TaskExecutionContext(
            task_id=task.task_id,
            session_id=task.session_id,
            cancel_event=handle.cancel_event,
            shutdown_event=handle.shutdown_event,
            emit=lambda event_type, payload: self._publish(
                event_type,
                task_id=task.task_id,
                session_id=task.session_id,
                request_id=task.request_id,
                payload=payload,
            ),
            heartbeat=lambda: self.tasks.heartbeat(
                task.task_id,
                owner=handle.lease_owner,
                token=handle.lease_token,
                lease_seconds=self.lease_seconds,
            ),
            update_fields=lambda fields: self.tasks.update_fields(
                task.task_id,
                fields=fields,
                lease_owner=handle.lease_owner,
                lease_token=handle.lease_token,
            ),
            register_cancel=lambda callback: self.registry.register_cancel_callback(task.task_id, callback),
            register_cleanup=lambda callback: self.registry.register_cleanup(task.task_id, callback),
            register_process=lambda process: self.registry.register_process(task.task_id, process),
            set_waiting=lambda waiting_for: self.registry.set_waiting(task.task_id, waiting_for),
            submit_progress=lambda candidate: self._submit_progress_summary(task, candidate),
        )

    def _submit_progress_summary(
        self,
        task: BackgroundTask,
        candidate: ProgressSummaryCandidate,
    ) -> bool:
        def publish(report: ProgressReport) -> None:
            self._publish(
                "background_task_progress_report",
                task_id=task.task_id,
                session_id=task.session_id,
                request_id=task.request_id,
                payload=report.model_dump(mode="json"),
            )

        publish(deterministic_progress_report(candidate))
        return self.progress_summaries.submit(candidate, publish)

    def _heartbeat_loop(self, task_id: str, owner: str, token: str, stop: threading.Event) -> None:
        while not stop.wait(self.lease_seconds / 3):
            try:
                self.tasks.heartbeat(
                    task_id,
                    owner=owner,
                    token=token,
                    lease_seconds=self.lease_seconds,
                )
            except ConflictError:
                return

    def _suspend(
        self,
        task_id: str,
        owner: str,
        token: str,
        suspended: TaskSuspended,
        *,
        resources_released_at: str,
    ) -> None:
        current = self.tasks.get(task_id)
        if current.status == "cancelling":
            task = self.tasks.complete_execution(
                task_id,
                outcome="cancelled",
                lease_owner=owner,
                lease_token=token,
            )
            self._publish_task("background_task_result", task, {"status": "cancelled"})
            self.tasks.mark_resources_released(task_id)
            return
        runtime_request_id = f"{current.request_id}:resume:{suspended.request_id}"
        pending = {
            "request_id": suspended.request_id,
            "runtime_request_id": runtime_request_id,
            "payload": suspended.payload,
        }
        task = self.tasks.suspend(
            task_id,
            status=suspended.status,
            request_id=suspended.request_id,
            pending_payload=pending,
            approval_payload=suspended.payload if suspended.status == "waiting_approval" else None,
            lease_owner=owner,
            lease_token=token,
            resources_released_at=resources_released_at,
        )
        self._publish_task(
            "background_task_status_changed",
            task,
            {"status": task.status, "request_id": suspended.request_id, "payload": suspended.payload},
        )

    def _requeue(
        self,
        task_id: str,
        owner: str,
        token: str,
        *,
        reason: str,
        resources_released_at: str,
    ) -> None:
        current = self.tasks.get(task_id)
        if current.status == "cancelling":
            self._finish_cancelled(task_id, owner, token)
            self.tasks.mark_resources_released(task_id)
            return
        task = self.tasks.transition(
            task_id,
            to_status="queued",
            lease_owner=owner,
            lease_token=token,
            fields={
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
                "resources_released_at": resources_released_at,
                "visible_context": {**current.visible_context, "recovery_reason": reason},
            },
        )
        self._publish_task("background_task_requeued", task, {"reason": reason})

    def _finish_success(self, task_id: str, owner: str, token: str, result: BackgroundTaskResult) -> None:
        task = self.tasks.complete_execution(
            task_id,
            outcome="succeeded",
            lease_owner=owner,
            lease_token=token,
            fields={
                "result_summary": result.summary,
                "artifact_refs": result.artifacts,
                "result": result.result,
                "error": None,
            },
        )
        self._publish_task(
            "background_task_result",
            task,
            {"status": task.status, "result": result.model_dump(mode="json") if task.status == "succeeded" else None},
        )

    def _finish_failed(self, task_id: str, owner: str, token: str, error: dict[str, Any]) -> None:
        task = self.tasks.complete_execution(
            task_id,
            outcome="failed",
            lease_owner=owner,
            lease_token=token,
            fields={
                "result_summary": str(error.get("message") or "后台任务执行失败。"),
                "error": error,
            },
        )
        self._publish_task(
            "background_task_result",
            task,
            {"status": task.status, "error": error if task.status == "failed" else None},
        )

    def _finish_cancelled(self, task_id: str, owner: str, token: str) -> None:
        task = self.tasks.complete_execution(
            task_id,
            outcome="cancelled",
            lease_owner=owner,
            lease_token=token,
        )
        self._publish_task("background_task_result", task, {"status": "cancelled"})

    def _publish_recovery(self, recovered: list[dict[str, str]]) -> None:
        for item in recovered:
            task = self.tasks.get(item["task_id"])
            self._publish_task("background_task_recovered", task, item)

    def _publish_task(self, event_type: str, task: BackgroundTask, payload: dict[str, Any]) -> dict[str, Any]:
        return self._publish(
            event_type,
            task_id=task.task_id,
            session_id=task.session_id,
            request_id=task.request_id,
            payload=payload,
        )

    def _publish(
        self,
        event_type: str,
        *,
        task_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.events.append(
            event_type=event_type,
            task_id=task_id,
            session_id=session_id,
            request_id=request_id,
            payload=payload,
        )
        serialized = event.model_dump(mode="json")
        with self._lifecycle_lock:
            listeners = tuple(self._event_listeners)
        for listener in listeners:
            try:
                listener(serialized)
            except Exception:
                self.logger.exception("background-task event listener failed")
        return serialized

    def _all_session_tasks(self, session_id: str) -> list[BackgroundTask]:
        result: list[BackgroundTask] = []
        offset = 0
        while True:
            page = self.tasks.list(session_id=session_id, limit=500, offset=offset)
            result.extend(page)
            if len(page) < 500:
                return result
            offset += len(page)
