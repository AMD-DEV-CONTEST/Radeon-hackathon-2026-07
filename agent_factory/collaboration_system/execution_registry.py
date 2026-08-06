"""Process-local execution handles fenced by persisted task leases."""

from __future__ import annotations

from dataclasses import dataclass, field
import subprocess
import threading
from typing import Callable, Protocol


class ManagedProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


CancelCallback = Callable[[str], None]
CleanupCallback = Callable[[], None]


@dataclass(slots=True)
class ExecutionHandle:
    task_id: str
    lease_owner: str
    lease_token: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    shutdown_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    waiting_for: str | None = None
    cancel_callbacks: list[CancelCallback] = field(default_factory=list)
    cleanup_callbacks: list[CleanupCallback] = field(default_factory=list)
    processes: list[ManagedProcess] = field(default_factory=list)
    callback_errors: list[str] = field(default_factory=list)
    cleanup_errors: list[str] = field(default_factory=list)
    cancel_reason: str | None = None
    closed: bool = False

    def request_cancel(self, reason: str) -> None:
        self.cancel_reason = reason
        self.cancel_event.set()
        self._notify_callbacks(reason)

    def request_shutdown(self) -> None:
        self.shutdown_event.set()
        self._notify_callbacks("background_task_service_stopping")

    def _notify_callbacks(self, reason: str) -> None:
        for callback in tuple(self.cancel_callbacks):
            try:
                callback(reason)
            except Exception as exc:  # callbacks are external runtime boundaries
                self.callback_errors.append(f"{type(exc).__name__}: {exc}")


class ExecutionRegistry:
    """Own threads, child processes and cleanup callbacks for active tasks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handles: dict[str, ExecutionHandle] = {}

    def register(self, task_id: str, *, lease_owner: str, lease_token: str) -> ExecutionHandle:
        identifier = str(task_id or "").strip()
        if not identifier:
            raise ValueError("task_id is required")
        with self._lock:
            if identifier in self._handles:
                raise RuntimeError(f"task execution is already registered: {identifier}")
            handle = ExecutionHandle(
                task_id=identifier,
                lease_owner=str(lease_owner or "").strip(),
                lease_token=str(lease_token or "").strip(),
            )
            if not handle.lease_owner or not handle.lease_token:
                raise ValueError("execution handle requires a complete lease fence")
            self._handles[identifier] = handle
            return handle

    def get(self, task_id: str) -> ExecutionHandle | None:
        with self._lock:
            return self._handles.get(str(task_id or "").strip())

    def attach_thread(self, task_id: str, thread: threading.Thread) -> None:
        handle = self._require(task_id)
        with self._lock:
            if handle.thread is not None:
                raise RuntimeError(f"task thread is already attached: {task_id}")
            handle.thread = thread

    def register_cancel_callback(self, task_id: str, callback: CancelCallback) -> None:
        handle = self._require(task_id)
        with self._lock:
            if handle.closed:
                raise RuntimeError(f"task execution is already closing: {task_id}")
            handle.cancel_callbacks.append(callback)
            cancel_reason = handle.cancel_reason if handle.cancel_event.is_set() else None
            shutting_down = handle.shutdown_event.is_set()
        pending_reason = cancel_reason or ("background_task_service_stopping" if shutting_down else None)
        if pending_reason is not None:
            try:
                callback(pending_reason)
            except Exception as exc:
                handle.callback_errors.append(f"{type(exc).__name__}: {exc}")

    def register_cleanup(self, task_id: str, callback: CleanupCallback) -> None:
        handle = self._require(task_id)
        with self._lock:
            if handle.closed:
                raise RuntimeError(f"task execution is already closing: {task_id}")
            handle.cleanup_callbacks.append(callback)

    def register_process(self, task_id: str, process: ManagedProcess) -> None:
        handle = self._require(task_id)
        with self._lock:
            if handle.closed:
                raise RuntimeError(f"task execution is already closing: {task_id}")
            handle.processes.append(process)

    def set_waiting(self, task_id: str, waiting_for: str | None) -> None:
        handle = self._require(task_id)
        with self._lock:
            handle.waiting_for = str(waiting_for).strip() if waiting_for else None

    def request_cancel(self, task_id: str, *, reason: str) -> bool:
        handle = self.get(task_id)
        if handle is None:
            return False
        handle.request_cancel(reason)
        return True

    def request_shutdown_all(self) -> None:
        with self._lock:
            handles = tuple(self._handles.values())
        for handle in handles:
            handle.request_shutdown()

    def reclaim(self, task_id: str, *, join_timeout: float | None = None) -> bool:
        handle = self.get(task_id)
        if handle is None:
            return True
        thread = handle.thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=join_timeout)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            return False
        current = self.get(task_id)
        if current is None:
            return True
        if current is not handle:
            return False
        with self._lock:
            handle.closed = True
            handle.cleanup_errors.clear()
        self._cleanup_processes(handle)
        for callback in tuple(reversed(handle.cleanup_callbacks)):
            try:
                callback()
            except Exception as exc:  # cleanup failures must keep deletion fenced
                handle.cleanup_errors.append(f"{type(exc).__name__}: {exc}")
            else:
                with self._lock:
                    handle.cleanup_callbacks.remove(callback)
        if handle.cleanup_errors:
            return False
        with self._lock:
            self._handles.pop(handle.task_id, None)
        return True

    def active_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._handles)

    def active_count(self) -> int:
        with self._lock:
            return len(self._handles)

    def _require(self, task_id: str) -> ExecutionHandle:
        handle = self.get(task_id)
        if handle is None:
            raise RuntimeError(f"task execution is not registered: {task_id}")
        return handle

    def _cleanup_processes(self, handle: ExecutionHandle) -> None:
        for process in tuple(handle.processes):
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except (TimeoutError, subprocess.TimeoutExpired):
                        process.kill()
                        process.wait(timeout=2.0)
            except Exception as exc:  # child-process cleanup is an OS boundary
                handle.cleanup_errors.append(f"{type(exc).__name__}: {exc}")
            else:
                with self._lock:
                    handle.processes.remove(process)
