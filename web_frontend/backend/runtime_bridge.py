from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
import logging
import os
import threading
import uuid
from typing import Any, Callable

from fastapi import HTTPException

from agent_factory.collaboration_system.task_runtime import background_task_service
from agent_factory.contracts import NotFoundError, ServiceUnavailableError
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    event,
)
from agent_factory.model_pool.usage import record_model_usage_frontend_event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter import FactoryRuntimeAdapter
from web_frontend.backend.runtime_event_journal import RuntimeEventJournal
from web_frontend.backend.runtime_event_pipeline import RuntimeEventPipeline

logger = logging.getLogger(__name__)


ALWAYS_LONG_RUNNING_COMMANDS = {
    "send_message",
    "resume_interrupt",
    "initialize_agent_package",
    "send_agent_package_message",
    "run_agent_package",
    "run_agent_evolution",
    "run_agent_group_member",
}

LONG_RUNNING_ACTIONS = {
    "knowledge_manage": {"confirm_source", "reindex"},
    "extensions_manage": {"install_mcp", "test_mcp"},
    "scheduler_manage": {"run_now"},
}

COMMAND_MODE_HINTS = {
    "initialize_agent_package": "agent_package",
    "send_agent_package_message": "agent_package",
    "run_agent_package": "agent_package",
    "run_agent_evolution": "evolve_agent",
    "run_agent_group_member": "agent_group",
}

ACTIVE_REQUEST_METADATA_EVENTS = {
    "run_started",
    "session_started",
    "session_switched",
    "agent_package_selected",
    "agent_package_session_loaded",
    "mode_changed",
    "runtime_resumed",
    "interrupt_requested",
}

TERMINAL_REQUEST_EVENTS = {
    "run_completed",
    "run_cancelled",
    "run_failed",
    "error",
}

RUNTIME_EVENT_PIPELINE_CAPACITY_ENV = "AGENTFACTORY_RUNTIME_EVENT_PIPELINE_CAPACITY"
DEFAULT_RUNTIME_EVENT_PIPELINE_CAPACITY = 2048


class RuntimeBridge:
    """Owns the in-process factory runtime and SSE event fan-out."""

    def __init__(self) -> None:
        self.adapter: FactoryRuntimeAdapter | None = None
        self.event_history: deque[dict[str, Any]] = deque(maxlen=500)
        self.event_journal = RuntimeEventJournal()
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.event_observers: set[Callable[[dict[str, Any]], None]] = set()
        self._background_threads: dict[str, threading.Thread] = {}
        self._background_commands: dict[str, FactoryFrontendCommand] = {}
        self._active_requests: dict[str, dict[str, Any]] = {}
        self._session_dispatch_queues: dict[str, deque[str]] = {}
        self._session_running_requests: dict[str, str] = {}
        self._deleting_session_ids: set[str] = set()
        self._session_cleanup_tasks: dict[str, asyncio.Task[None]] = {}
        self._background_lock = threading.Lock()
        self._dispatch_condition = threading.Condition(self._background_lock)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event_pipeline = RuntimeEventPipeline(
            prepare=self._prepare_runtime_event,
            deliver=self._schedule_runtime_event_delivery,
            report_failure=self._report_event_pipeline_failure,
            capacity=_runtime_event_pipeline_capacity(),
        )

    @property
    def active(self) -> bool:
        return self.adapter is not None

    async def start(self) -> None:
        if self.adapter is not None:
            logger.warning("Runtime service already started")
            return

        self._loop = asyncio.get_running_loop()
        self._event_pipeline.start()
        self.adapter = await asyncio.to_thread(FactoryRuntimeAdapter, emit=self._emit_from_runtime)
        self._emit_from_runtime(self._runtime_ready_event())
        logger.info("Runtime service started")

    async def stop(self) -> None:
        adapter = self.adapter
        if adapter is None:
            await asyncio.to_thread(self._event_pipeline.stop, drain=True)
            self._loop = None
            logger.info("Runtime service already stopped")
            return

        shutdown_cmd = FactoryFrontendCommand(
            type="shutdown",
            request_id=str(uuid.uuid4()),
        )
        await asyncio.to_thread(adapter.handle, shutdown_cmd)
        self.adapter = None
        await asyncio.to_thread(self._event_pipeline.stop, drain=True)
        self._loop = None
        with self._background_lock:
            self._background_threads.clear()
            self._background_commands.clear()
            self._active_requests.clear()
            self._session_dispatch_queues.clear()
            self._session_running_requests.clear()
            self._deleting_session_ids.clear()
        self._session_cleanup_tasks.clear()
        logger.info("Runtime service stopped")

    async def send_frontend_command(self, command: FactoryFrontendCommand) -> None:
        if self.adapter is None:
            raise RuntimeError("Runtime service not started")

        command = self._resolve_cancel_command(command)
        command_session_id = _command_session_id(command)
        with self._background_lock:
            session_is_deleting = bool(
                command_session_id and command_session_id in self._deleting_session_ids
            )
        if session_is_deleting and command.type in {
            "delete_session",
            "delete_agent_package_session",
        }:
            self._emit_from_runtime(
                _logical_session_deletion_event(command, session_id=command_session_id)
            )
            return
        if session_is_deleting and command.type not in {
            "steer_runtime_request",
            "cancel_runtime_request",
            "delete_session",
            "delete_agent_package_session",
        }:
            raise RuntimeError(f"session is being deleted: {command_session_id}")
        if command.type == "steer_runtime_request":
            await asyncio.to_thread(self._steer_queued_request, command)
            return
        if _is_long_running_command(command):
            self._start_background(command)
            return

        if command.type in {"delete_session", "delete_agent_package_session"}:
            await self._cancel_and_join_deleted_session_requests(command)
            return
        await asyncio.to_thread(self._handle_command, command)

    async def send_and_wait(
        self,
        command: FactoryFrontendCommand,
        *,
        event_types: set[str],
        timeout_seconds: float | None = 30.0,
        event_filter: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        event_queue = self.subscribe(replay_history=False)
        try:
            await self.send_frontend_command(command)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout_seconds if timeout_seconds is not None else None
            while True:
                remaining = deadline - loop.time() if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    raise HTTPException(status_code=504, detail=f"Timed out waiting for {command.type}")
                try:
                    event_payload = (
                        await event_queue.get()
                        if remaining is None
                        else await asyncio.wait_for(event_queue.get(), timeout=remaining)
                    )
                except TimeoutError as exc:
                    raise HTTPException(status_code=504, detail=f"Timed out waiting for {command.type}") from exc
                if event_payload.get("request_id") != command.request_id:
                    continue
                if event_payload.get("event_type") == "error":
                    raise HTTPException(
                        status_code=400,
                        detail=event_payload.get("message") or "Runtime command failed",
                    )
                if event_payload.get("event_type") in event_types and (
                    event_filter is None or event_filter(event_payload)
                ):
                    return event_payload
        finally:
            self.unsubscribe(event_queue)

    async def delete_session_and_wait(
        self,
        command: FactoryFrontendCommand,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        session_id = _deleted_session_id(command)
        if not session_id:
            raise ValueError("session deletion requires session_id")
        if self.adapter is None:
            raise RuntimeError("Runtime service not started")
        cleanup_task = await self._cancel_and_join_deleted_session_requests(
            self._resolve_cancel_command(command)
        )
        if cleanup_task is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(cleanup_task),
                timeout=max(0.1, float(timeout_seconds)),
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"session cleanup timed out: {session_id}") from exc

    def subscribe(
        self,
        *,
        replay_history: bool = True,
        after_event_id: str | None = None,
    ) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        replay_gap = False
        if replay_history:
            history = list(self.event_history)
            if after_event_id:
                cursor_index = next(
                    (
                        index
                        for index, item in enumerate(history)
                        if str(item.get("event_id") or "") == after_event_id
                    ),
                    -1,
                )
                replay_gap = cursor_index < 0
                history = history[cursor_index + 1 :] if cursor_index >= 0 else []
            for event_payload in history:
                queue.put_nowait(event_payload)
        snapshot = self._runtime_ready_event(
            replay_gap=replay_gap,
            replay_after_event_id=after_event_id,
        )
        if snapshot is not None:
            queue.put_nowait(snapshot.model_dump(mode="json"))
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    def add_event_observer(self, observer: Callable[[dict[str, Any]], None]) -> None:
        self.event_observers.add(observer)

    def remove_event_observer(self, observer: Callable[[dict[str, Any]], None]) -> None:
        self.event_observers.discard(observer)

    def _start_background(self, command: FactoryFrontendCommand) -> None:
        request_id = command.request_id or f"{command.type}-{id(command)}"
        if command.request_id != request_id:
            command = command.model_copy(update={"request_id": request_id})
        dispatch_event = None
        with self._background_lock:
            session_id = _command_session_id(command)
            if session_id and session_id in self._deleting_session_ids:
                raise RuntimeError(f"session is being deleted: {session_id}")
            request = _active_request_from_command(command, request_id)
            serialized = bool(session_id and not request["background"])
            queued = serialized and session_id in self._session_running_requests
            if serialized:
                if queued:
                    queue = self._session_dispatch_queues.setdefault(session_id, deque())
                    queue.append(request_id)
                    request["payload"]["queue_position"] = len(queue)
                else:
                    self._session_running_requests[session_id] = request_id
                    request["payload"]["queue_position"] = 0
            request["payload"]["dispatch_state"] = "queued" if queued else "running"
            self._active_requests[request_id] = request
            thread = threading.Thread(
                target=self._run_background_command,
                args=(command, request_id),
                name=f"factory-runtime-command-{request_id}",
                daemon=True,
            )
            self._background_threads[request_id] = thread
            self._background_commands[request_id] = command
            if queued:
                dispatch_event = _runtime_request_dispatch_event(
                    command=command,
                    request_id=request_id,
                    event_type="runtime_request_queued",
                    dispatch_state="queued",
                    queue_position=int(request["payload"]["queue_position"]),
                )
        if dispatch_event is not None:
            self._emit_from_runtime(dispatch_event)
        thread.start()

    async def _cancel_and_join_deleted_session_requests(
        self,
        command: FactoryFrontendCommand,
    ) -> asyncio.Task[None] | None:
        session_id = _deleted_session_id(command)
        if not session_id:
            await asyncio.to_thread(self._handle_command, command)
            return None
        with self._background_lock:
            existing_cleanup = self._session_cleanup_tasks.get(session_id)
            if existing_cleanup is not None:
                return existing_cleanup
            self._deleting_session_ids.add(session_id)
            active = [
                (request_id, thread)
                for request_id, thread in self._background_threads.items()
                if (
                    _command_session_id(self._background_commands.get(request_id)) == session_id
                    or _active_request_session_id(self._active_requests.get(request_id)) == session_id
                )
            ]
        self._emit_from_runtime(_logical_session_deletion_event(command, session_id=session_id))
        cleanup_task = asyncio.create_task(
            self._finish_deleted_session_cleanup(
                command=command,
                session_id=session_id,
                active=active,
            ),
            name=f"session-cleanup-{session_id}",
        )
        with self._background_lock:
            self._session_cleanup_tasks[session_id] = cleanup_task
        cleanup_task.add_done_callback(
            lambda completed, cleanup_session_id=session_id: self._finish_cleanup_task(
                cleanup_session_id,
                completed,
            )
        )
        return cleanup_task

    def _finish_cleanup_task(
        self,
        session_id: str,
        completed: asyncio.Task[None],
    ) -> None:
        with self._background_lock:
            if self._session_cleanup_tasks.get(session_id) is completed:
                self._session_cleanup_tasks.pop(session_id, None)
        if not completed.cancelled():
            completed.exception()

    async def _finish_deleted_session_cleanup(
        self,
        *,
        command: FactoryFrontendCommand,
        session_id: str,
        active: list[tuple[str, threading.Thread]],
    ) -> None:
        try:
            for request_id, _thread in active:
                cancel_command = self._resolve_cancel_command(
                    FactoryFrontendCommand(
                        type="cancel_runtime_request",
                        request_id=f"{command.request_id or uuid.uuid4().hex}:cancel:{request_id}",
                        session_id=session_id,
                        mode=command.mode,
                        payload={
                            **dict(command.payload or {}),
                            "target_request_id": request_id,
                            "reason": "session_deleted",
                        },
                    )
                )
                await asyncio.to_thread(self._handle_command, cancel_command)
            if active:
                await asyncio.gather(
                    *(asyncio.to_thread(thread.join) for _request_id, thread in active)
                )
            try:
                await asyncio.to_thread(background_task_service().delete_session, session_id)
            except (NotFoundError, ServiceUnavailableError):
                pass
            cleanup_command = command.model_copy(
                update={"request_id": f"{command.request_id or uuid.uuid4().hex}:cleanup"}
            )
            await asyncio.to_thread(self._handle_command, cleanup_command)
        except Exception:
            logger.exception("Deferred session cleanup failed: %s", session_id)
            raise
        finally:
            with self._background_lock:
                self._deleting_session_ids.discard(session_id)

    def _run_background_command(
        self,
        command: FactoryFrontendCommand,
        request_id: str,
    ) -> None:
        try:
            if not self._wait_for_dispatch(request_id):
                return
            with self._background_lock:
                active_request = self._active_requests.get(request_id)
                dispatch_payload = dict(active_request.get("payload") or {}) if active_request else {}
            self._emit_from_runtime(
                _runtime_request_dispatch_event(
                    command=command,
                    request_id=request_id,
                    event_type="runtime_request_dispatched",
                    dispatch_state="running",
                    queue_position=0,
                    extra_payload={
                        key: dispatch_payload[key]
                        for key in ("steer_from_request_id", "steer_requested_at")
                        if dispatch_payload.get(key)
                    },
                )
            )
            self._handle_command(command)
        except Exception as exc:
            logger.exception("Runtime command failed in background: %s", command.type)
            self._emit_from_runtime(
                event(
                    "error",
                    request_id=command.request_id,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
        finally:
            with self._background_lock:
                self._release_dispatch_slot(command, request_id)
                self._background_threads.pop(request_id, None)
                self._background_commands.pop(request_id, None)
                self._active_requests.pop(request_id, None)
                self._dispatch_condition.notify_all()

    def _wait_for_dispatch(self, request_id: str) -> bool:
        with self._dispatch_condition:
            while True:
                request = self._active_requests.get(request_id)
                if request is None:
                    return False
                payload = request.setdefault("payload", {})
                if payload.get("queue_cancel_requested_at"):
                    self._remove_queued_request(request_id, _active_request_session_id(request))
                    return False
                session_id = _active_request_session_id(request)
                if (
                    not session_id
                    or bool(request.get("background"))
                    or self._session_running_requests.get(session_id) == request_id
                ):
                    payload["dispatch_state"] = "running"
                    payload["queue_position"] = 0
                    return True
                self._dispatch_condition.wait()

    def _release_dispatch_slot(self, command: FactoryFrontendCommand, request_id: str) -> None:
        session_id = _command_session_id(command)
        self._release_session_dispatch_slot(session_id=session_id, request_id=request_id)

    def _release_session_dispatch_slot(self, *, session_id: str, request_id: str) -> None:
        if not session_id or self._session_running_requests.get(session_id) != request_id:
            self._remove_queued_request(request_id, session_id)
            return
        self._session_running_requests.pop(session_id, None)
        queue = self._session_dispatch_queues.get(session_id)
        while queue:
            next_request_id = queue.popleft()
            next_request = self._active_requests.get(next_request_id)
            if next_request is None or next_request.get("payload", {}).get("queue_cancel_requested_at"):
                continue
            self._session_running_requests[session_id] = next_request_id
            break
        if queue is not None and not queue:
            self._session_dispatch_queues.pop(session_id, None)

    def _remove_queued_request(self, request_id: str, session_id: str) -> None:
        queue = self._session_dispatch_queues.get(session_id)
        if queue is None:
            return
        try:
            queue.remove(request_id)
        except ValueError:
            return
        if not queue:
            self._session_dispatch_queues.pop(session_id, None)

    def _steer_queued_request(self, command: FactoryFrontendCommand) -> None:
        queued_request_id = str(command.payload.get("queued_request_id") or "").strip()
        if not queued_request_id:
            raise ValueError("steer_runtime_request requires queued_request_id")
        with self._dispatch_condition:
            queued_request = self._active_requests.get(queued_request_id)
            if queued_request is None:
                raise ValueError(f"queued runtime request is unavailable: {queued_request_id}")
            queued_payload = queued_request.setdefault("payload", {})
            if queued_payload.get("dispatch_state") != "queued":
                raise ValueError(f"runtime request is not queued: {queued_request_id}")
            session_id = _active_request_session_id(queued_request)
            running_request_id = self._session_running_requests.get(session_id, "")
            queue = self._session_dispatch_queues.get(session_id)
            if not session_id or not running_request_id or queue is None:
                raise ValueError(f"queued runtime request has no active predecessor: {queued_request_id}")
            queued_command = self._background_commands.get(queued_request_id)
            if queued_command is None:
                raise ValueError(f"queued runtime command is unavailable: {queued_request_id}")
            self._remove_queued_request(queued_request_id, session_id)
            queue = self._session_dispatch_queues.setdefault(session_id, deque())
            queue.appendleft(queued_request_id)
            steer_requested_at = datetime.now(UTC).isoformat()
            queued_payload.update(
                {
                    "dispatch_state": "steering",
                    "queue_position": 0,
                    "steer_from_request_id": running_request_id,
                    "steer_requested_at": steer_requested_at,
                }
            )
            running_request = self._active_requests.get(running_request_id)
            running_mode = running_request.get("mode") if running_request else command.mode
            running_payload = dict(running_request.get("payload") or {}) if running_request else {}
            self._dispatch_condition.notify_all()
        self._emit_from_runtime(
            _runtime_request_dispatch_event(
                command=queued_command,
                request_id=queued_request_id,
                event_type="runtime_request_steering",
                dispatch_state="steering",
                queue_position=0,
                extra_payload={
                    "steer_from_request_id": running_request_id,
                    "steer_requested_at": steer_requested_at,
                },
            )
        )
        cancel_command = FactoryFrontendCommand(
            type="cancel_runtime_request",
            request_id=command.request_id,
            session_id=session_id,
            mode=running_mode,
            payload={
                "reason": "user_steered",
                "target_request_id": running_request_id,
                **(
                    {"package_id": running_payload["package_id"]}
                    if running_payload.get("package_id")
                    else {}
                ),
            },
        )
        self._handle_command(self._resolve_cancel_command(cancel_command))

    def _resolve_cancel_command(self, command: FactoryFrontendCommand) -> FactoryFrontendCommand:
        if command.type != "cancel_runtime_request":
            return command
        payload = dict(command.payload or {})
        requested_target = str(payload.get("target_request_id") or "").strip()
        session_id = _command_session_id(command)
        resolved_target = ""
        with self._background_lock:
            if requested_target and requested_target in self._active_requests:
                resolved_target = requested_target
            else:
                candidates = [
                    request
                    for request in self._active_requests.values()
                    if not bool(request.get("background"))
                    and session_id
                    and _active_request_session_id(request) == session_id
                ]
                if candidates:
                    active_request = max(candidates, key=lambda item: str(item.get("startedAt") or ""))
                    resolved_target = str(active_request.get("requestId") or "").strip()
            if resolved_target and resolved_target in self._active_requests:
                active_payload = self._active_requests[resolved_target].setdefault("payload", {})
                requested_at = datetime.now(UTC).isoformat()
                if active_payload.get("dispatch_state") == "queued":
                    active_payload["queue_cancel_requested_at"] = requested_at
                else:
                    active_payload["stop_requested_at"] = requested_at
                    active_payload["dispatch_state"] = "stopping"
                self._dispatch_condition.notify_all()
        if not resolved_target:
            return command
        if requested_target and requested_target != resolved_target:
            payload["requested_target_request_id"] = requested_target
        payload["target_request_id"] = resolved_target
        return command.model_copy(update={"payload": payload})

    def _handle_command(self, command: FactoryFrontendCommand) -> None:
        adapter = self.adapter
        if adapter is None:
            raise RuntimeError("Runtime service not started")
        adapter.handle(command)

    def _emit_from_runtime(self, payload: Any) -> None:
        if hasattr(payload, "model_dump"):
            event_payload = payload.model_dump(mode="json")
        else:
            event_payload = payload
        if not isinstance(event_payload, dict):
            logger.warning("Ignored non-object runtime event: %r", event_payload)
            return

        event_payload = self._filter_deleting_sessions_from_event(event_payload)
        event_session_id = _runtime_event_session_id(event_payload)
        event_type = str(event_payload.get("event_type") or "")
        with self._background_lock:
            session_is_deleting = bool(
                event_session_id and event_session_id in self._deleting_session_ids
            )
        if session_is_deleting and event_type not in {
            "session_deleted",
            "agent_package_session_deleted",
        }:
            self._observe_runtime_event(event_payload)
            return

        self._observe_runtime_event(event_payload)
        self._event_pipeline.submit(event_payload)

    def _filter_deleting_sessions_from_event(
        self,
        event_payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload = event_payload.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
            return event_payload
        with self._background_lock:
            deleting_session_ids = set(self._deleting_session_ids)
        if not deleting_session_ids:
            return event_payload
        sessions = [
            item
            for item in payload["sessions"]
            if not (
                isinstance(item, dict)
                and str(item.get("session_id") or "").strip() in deleting_session_ids
            )
        ]
        return {**event_payload, "payload": {**payload, "sessions": sessions}}

    def _prepare_runtime_event(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            event_payload = self.event_journal.prepare_for_delivery(event_payload)
        except Exception:
            logger.exception("Failed to persist or hydrate runtime process event")
        try:
            record_model_usage_frontend_event(event_payload)
        except Exception:
            logger.exception("Failed to record model usage event")
        for observer in tuple(self.event_observers):
            try:
                observer(event_payload)
            except Exception:
                logger.exception("Runtime event observer failed")
        return event_payload

    def _schedule_runtime_event_delivery(self, event_payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            self.event_history.append(event_payload)
            return
        loop.call_soon_threadsafe(self._record_and_broadcast, event_payload)

    def _record_and_broadcast(self, event_payload: dict[str, Any]) -> None:
        self.event_history.append(event_payload)
        stale_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event_payload)
            except asyncio.QueueFull:
                stale_subscribers.append(queue)
        for queue in stale_subscribers:
            self.unsubscribe(queue)

    def schedule_coroutine(self, coroutine: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            return
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        future.add_done_callback(_log_scheduled_coroutine_failure)

    def _report_event_pipeline_failure(self, stage: str, exc: BaseException) -> None:
        logger.error(
            "Runtime event pipeline %s failed: %s: %s",
            stage,
            type(exc).__name__,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    def _runtime_ready_event(
        self,
        *,
        replay_gap: bool = False,
        replay_after_event_id: str | None = None,
    ):
        adapter = self.adapter
        if adapter is None:
            return None
        return event(
            "runtime_ready",
            producer_type="factory_bridge",
            message="factory runtime service ready",
            graph_id="factory_bridge",
            payload={
                "checkpointer": adapter.checkpointer_payload(),
                "options": adapter._options_payload(),
                "active_requests": self._active_request_payloads(),
                "event_replay": {
                    "gap": replay_gap,
                    "after_event_id": replay_after_event_id,
                },
                "event_pipeline": self._event_pipeline.stats().payload(),
            },
        )

    def _active_request_payloads(self) -> list[dict[str, Any]]:
        with self._background_lock:
            return [
                dict(item)
                for item in self._active_requests.values()
                if not (
                    item.get("payload", {}).get("dispatch_state") == "queued"
                    and item.get("payload", {}).get("queue_cancel_requested_at")
                )
            ]

    def _observe_runtime_event(self, event_payload: dict[str, Any]) -> None:
        request_id = str(event_payload.get("request_id") or "").strip()
        if not request_id:
            return
        event_type = str(event_payload.get("event_type") or "")
        if event_type in {"tool_approval_resolved", "runtime_resumed"}:
            payload = event_payload.get("payload")
            detail = payload if isinstance(payload, dict) else {}
            original_request_id = str(
                detail.get("pending_request_id")
                or detail.get("original_request_id")
                or ""
            ).strip()
            if original_request_id:
                with self._background_lock:
                    self._active_requests.pop(original_request_id, None)
        if event_type in TERMINAL_REQUEST_EVENTS:
            with self._background_lock:
                self._active_requests.pop(request_id, None)
            return
        if event_type not in ACTIVE_REQUEST_METADATA_EVENTS:
            return
        with self._background_lock:
            record = self._active_requests.get(request_id)
            if record is None:
                record = _active_request_from_event(event_payload, request_id)
                self._active_requests[request_id] = record
            _merge_active_request_event(record, event_payload)


def _is_long_running_command(command: FactoryFrontendCommand) -> bool:
    if command.type in ALWAYS_LONG_RUNNING_COMMANDS:
        return True
    long_running_actions = LONG_RUNNING_ACTIONS.get(command.type)
    if not long_running_actions:
        return False
    action = str(command.payload.get("action") or "").strip()
    return action in long_running_actions


def _runtime_event_pipeline_capacity() -> int:
    raw = str(os.getenv(RUNTIME_EVENT_PIPELINE_CAPACITY_ENV) or "").strip()
    if not raw:
        return DEFAULT_RUNTIME_EVENT_PIPELINE_CAPACITY
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{RUNTIME_EVENT_PIPELINE_CAPACITY_ENV} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{RUNTIME_EVENT_PIPELINE_CAPACITY_ENV} must be greater than zero")
    return value


def _log_scheduled_coroutine_failure(future: Any) -> None:
    try:
        future.result()
    except BaseException:
        logger.exception("Runtime event observer coroutine failed")


def _active_request_from_command(command: FactoryFrontendCommand, request_id: str) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload = dict(command.payload or {})
    source = _command_request_source(command, request_id=request_id)
    if command.message:
        payload.setdefault("message", command.message)
    if command.session_id:
        payload.setdefault("session_id", command.session_id)
    payload.setdefault("command_type", command.type)
    return {
        "requestId": request_id,
        "status": "running",
        "mode": command.mode or COMMAND_MODE_HINTS.get(command.type),
        "runId": None,
        "sessionId": command.session_id,
        "commandType": command.type,
        "background": source == "scheduler",
        "source": source,
        "startedAt": now,
        "completedAt": None,
        "payload": payload,
    }


def _runtime_request_dispatch_event(
    *,
    command: FactoryFrontendCommand,
    request_id: str,
    event_type: str,
    dispatch_state: str,
    queue_position: int,
    extra_payload: dict[str, Any] | None = None,
):
    command_payload = dict(command.payload or {})
    session_id = _command_session_id(command)
    payload = {
        key: command_payload[key]
        for key in (
            "package_id",
            "factory_session_id",
        )
        if command_payload.get(key) is not None
    }
    payload.update(
        {
            "command_type": command.type,
            "request_source": _command_request_source(command, request_id=request_id),
            "dispatch_state": dispatch_state,
            "queue_position": queue_position,
            "session_id": session_id or None,
            **dict(extra_payload or {}),
        }
    )
    return event(
        event_type,
        request_id=request_id,
        session_id=session_id or None,
        mode=command.mode or COMMAND_MODE_HINTS.get(command.type),
        producer_type="factory_bridge",
        payload=payload,
    )


def _command_request_source(command: FactoryFrontendCommand, *, request_id: str) -> str:
    if request_id.startswith("scheduler-"):
        return "scheduler"
    metadata = command.payload.get("message_metadata")
    if isinstance(metadata, dict) and str(metadata.get("visibility") or "").strip() == "internal":
        return "internal"
    return "user"


def _command_session_id(command: FactoryFrontendCommand | None) -> str:
    if command is None:
        return ""
    return str(command.session_id or command.payload.get("session_id") or "").strip()


def _deleted_session_id(command: FactoryFrontendCommand) -> str:
    if command.type == "delete_agent_package_session":
        return str(command.payload.get("session_id") or command.session_id or "").strip()
    return _command_session_id(command)


def _logical_session_deletion_event(
    command: FactoryFrontendCommand,
    *,
    session_id: str,
):
    package_id = str(command.payload.get("package_id") or "").strip()
    event_type = (
        "agent_package_session_deleted"
        if command.type == "delete_agent_package_session"
        else "session_deleted"
    )
    return event(
        event_type,
        request_id=command.request_id,
        session_id=None,
        mode=command.mode or COMMAND_MODE_HINTS.get(command.type),
        producer_type="factory_bridge",
        payload={
            "session_id": session_id,
            "session_ids": [session_id],
            "package_id": package_id or None,
            "deleted": True,
            "cleanup_pending": True,
        },
    )


def _runtime_event_session_id(event_payload: dict[str, Any]) -> str:
    payload = event_payload.get("payload")
    event_detail = payload if isinstance(payload, dict) else {}
    session = event_detail.get("session")
    session_detail = session if isinstance(session, dict) else {}
    return str(
        event_payload.get("session_id")
        or event_detail.get("session_id")
        or event_detail.get("factory_session_id")
        or session_detail.get("session_id")
        or ""
    ).strip()


def _active_request_session_id(request: dict[str, Any] | None) -> str:
    if not request:
        return ""
    payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
    return str(request.get("sessionId") or payload.get("session_id") or "").strip()


def _active_request_from_event(event_payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    timestamp = str(event_payload.get("timestamp") or datetime.now(UTC).isoformat())
    payload = dict(event_payload.get("payload") or {})
    return {
        "requestId": request_id,
        "status": "running",
        "mode": event_payload.get("mode"),
        "runId": event_payload.get("run_id"),
        "sessionId": event_payload.get("session_id") or payload.get("session_id"),
        "commandType": payload.get("command_type"),
        "background": request_id.startswith("scheduler-"),
        "source": "scheduler" if request_id.startswith("scheduler-") else "user",
        "startedAt": timestamp,
        "completedAt": None,
        "payload": payload,
    }


def _merge_active_request_event(record: dict[str, Any], event_payload: dict[str, Any]) -> None:
    payload = dict(event_payload.get("payload") or {})
    record["mode"] = event_payload.get("mode") or record.get("mode")
    record["runId"] = event_payload.get("run_id") or record.get("runId")
    session_id = event_payload.get("session_id") or payload.get("session_id") or record.get("sessionId")
    record["sessionId"] = session_id
    if session_id:
        payload.setdefault("session_id", session_id)
    record["payload"] = {
        **(record.get("payload") or {}),
        **payload,
    }
