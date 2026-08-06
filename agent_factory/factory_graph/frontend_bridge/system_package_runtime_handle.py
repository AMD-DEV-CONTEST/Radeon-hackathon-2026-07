from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import Path
import threading
import time
from typing import Any, Deque, Iterator
from uuid import uuid4

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.runtime_events import (
    heartbeat_due,
    is_request_progress,
    is_terminal_request_event,
    request_heartbeat_event,
    request_timed_out,
    request_timeout_payload,
    run_failed_event,
)
from agent_factory.package_runtime import PackageRuntimeCore
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy
from agent_factory.runtime_contracts import LoadedAgentPackage


Emit = Callable[[FactoryFrontendEvent], None]
ContainerStreamItem = tuple[str, Any]


def _target_request_ids(
    events: dict[str, Deque[ContainerStreamItem]],
    request_sessions: dict[str, str],
    *,
    request_id: str | None,
    session_id: str | None,
) -> list[str]:
    target = (request_id or "").strip()
    if target:
        return [target] if target in events else []
    session_target = (session_id or "").strip()
    if session_target:
        return [
            active_request_id
            for active_request_id in events
            if request_sessions.get(active_request_id) == session_target
        ]
    return list(events)


def _command_session_id(command: dict[str, Any]) -> str:
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    return str(payload.get("session_id") or command.get("session_id") or "").strip()


class SystemPackageRuntimeHandle:
    def __init__(
        self,
        *,
        package_id: str,
        package: LoadedAgentPackage,
        package_fingerprint: str,
        runtime_root: Path,
        workdir_root: Path,
        runtime_instance_id: str,
        instance_extension_root: Path,
        idle_timeout_seconds: int,
        request_policy: RuntimeRequestPolicy,
        producer_type: str,
        emit: Emit | None = None,
    ) -> None:
        self.package_id = package_id
        self.package_fingerprint = package_fingerprint
        self.runtime_root = runtime_root
        self.idle_timeout_seconds = idle_timeout_seconds
        self.request_policy = request_policy
        self._emit = emit
        self._idle_timer: threading.Timer | None = None
        self._closing = False
        self._condition = threading.Condition()
        self._request_events: dict[str, Deque[ContainerStreamItem]] = {}
        self._request_commands: dict[str, str] = {}
        self._request_session_ids: dict[str, str] = {}
        self._request_done: dict[str, bool] = {}
        self._request_errors: dict[str, BaseException] = {}
        self.last_used = time.monotonic()
        self.startup_payload: dict[str, Any] | None = None
        self.core = PackageRuntimeCore(
            package=package,
            runtime_root=runtime_root,
            workdir_root=workdir_root,
            runtime_instance_id=runtime_instance_id,
            instance_extension_root=instance_extension_root,
            emit_background=self._emit_background_event,
            graph_id=f"{package_id}_runtime",
            producer_type=producer_type,
        )
        self._schedule_idle_shutdown()

    def set_emit(self, emit: Emit | None) -> None:
        self._emit = emit

    def set_runtime_resources_override(self, resources: dict[str, Any]) -> None:
        self.core.set_runtime_resources_override(resources)

    @property
    def is_running(self) -> bool:
        return not self._closing

    @property
    def active_request_count(self) -> int:
        with self._condition:
            return len(self._request_events)

    @property
    def active_command_types(self) -> tuple[str, ...]:
        with self._condition:
            return tuple(self._request_commands.values())

    def is_idle(self, timeout_seconds: int) -> bool:
        return timeout_seconds > 0 and (time.monotonic() - self.last_used) > timeout_seconds

    def send(self, command: dict[str, Any]) -> Iterator[tuple[str, Any]]:
        if self._closing:
            raise RuntimeError(f"system package runtime for {self.package_id} is closed")
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        with self._condition:
            if request_id in self._request_events:
                raise RuntimeError(f"system package runtime request is already active: {request_id}")
            self._request_events[request_id] = deque()
            self._request_commands[request_id] = str(command.get("type") or "")
            session_id = _command_session_id(command)
            if session_id:
                self._request_session_ids[request_id] = session_id
            self._request_done[request_id] = False

        def collect(item: FactoryFrontendEvent) -> None:
            with self._condition:
                queue = self._request_events.get(request_id)
                if queue is not None:
                    queue.append(("frontend_event", item))
                    self._condition.notify_all()

        def run_request() -> None:
            try:
                self.core.handle(command, emit=collect)
            except BaseException as exc:
                with self._condition:
                    self._request_errors[request_id] = exc
                    self._condition.notify_all()
            finally:
                with self._condition:
                    self._request_done[request_id] = True
                    self._condition.notify_all()

        self.last_used = time.monotonic()
        self._cancel_idle_shutdown()
        request_policy = RuntimeRequestPolicy.from_payload(
            (command.get("payload") or {}).get("runtime_request")
            if isinstance(command.get("payload"), dict)
            else None,
            default=self.request_policy,
        )
        worker = threading.Thread(
            target=run_request,
            name=f"system-package-runtime-{self.package_id}-{request_id}",
            daemon=True,
        )
        worker.start()
        terminal_seen = False
        started_at = time.monotonic()
        last_progress_at = started_at
        last_heartbeat_at = started_at
        try:
            while not terminal_seen:
                for stream_mode, item in self._next_request_batch(request_id):
                    if is_request_progress(item, request_id):
                        last_progress_at = time.monotonic()
                    yield stream_mode, item
                    if is_terminal_request_event(item, request_id):
                        terminal_seen = True
                if terminal_seen:
                    break
                now = time.monotonic()
                if request_timed_out(last_progress_at, now, request_policy):
                    self.close()
                    yield "frontend_event", run_failed_event(
                        request_id,
                        request_timeout_payload(
                            package_id=self.package_id,
                            request_id=request_id,
                            elapsed_seconds=now - started_at,
                            inactive_seconds=now - last_progress_at,
                            timeout_seconds=request_policy.timeout_seconds,
                        ),
                    )
                    break
                if heartbeat_due(last_heartbeat_at, now, request_policy):
                    last_heartbeat_at = now
                    yield "frontend_event", request_heartbeat_event(
                        request_id,
                        package_id=self.package_id,
                        elapsed_seconds=now - started_at,
                        inactive_seconds=now - last_progress_at,
                        timeout_seconds=request_policy.timeout_seconds,
                    )
                with self._condition:
                    if self._request_done.get(request_id) and not self._request_events.get(request_id):
                        error = self._request_errors.get(request_id)
                        if error is not None:
                            raise RuntimeError(f"system package runtime request failed: {error}") from error
                        raise RuntimeError(
                            f"system package runtime request ended without terminal event: {request_id}"
                        )
        finally:
            worker.join(timeout=0.1)
            with self._condition:
                self._request_events.pop(request_id, None)
                self._request_commands.pop(request_id, None)
                self._request_session_ids.pop(request_id, None)
                self._request_done.pop(request_id, None)
                self._request_errors.pop(request_id, None)
            self.last_used = time.monotonic()
            self._schedule_idle_shutdown()

    def cancel_active_requests(
        self,
        *,
        reason: str,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        with self._condition:
            request_ids = _target_request_ids(
                self._request_events,
                self._request_session_ids,
                request_id=request_id,
                session_id=session_id,
            )
        cancelled = 0
        for active_request_id in request_ids:
            cancelled += self.core.cancel_active_requests(
                reason=reason,
                request_id=active_request_id,
            )
        return cancelled

    def close(self) -> None:
        self._cancel_idle_shutdown()
        if self._closing:
            return
        self._closing = True
        self.core.shutdown()
        with self._condition:
            self._condition.notify_all()

    def _next_request_batch(self, request_id: str) -> list[ContainerStreamItem]:
        while True:
            with self._condition:
                queue = self._request_events.get(request_id)
                if queue is None:
                    return []
                if queue:
                    batch = list(queue)
                    queue.clear()
                    return batch
                error = self._request_errors.get(request_id)
                if error is not None:
                    raise RuntimeError(f"system package runtime request failed: {error}") from error
                if self._request_done.get(request_id):
                    return []
                if self._closing:
                    raise RuntimeError(f"system package runtime for {self.package_id} is closed")
                self._condition.wait(timeout=0.2)
                return []

    def _emit_background_event(self, item: FactoryFrontendEvent) -> None:
        if self._emit is not None:
            self._emit(item)
        self._schedule_idle_shutdown()

    def _schedule_idle_shutdown(self) -> None:
        self._cancel_idle_shutdown()
        if self.idle_timeout_seconds <= 0 or self._closing:
            return
        self._idle_timer = threading.Timer(self.idle_timeout_seconds, self.close)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _cancel_idle_shutdown(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
