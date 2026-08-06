from __future__ import annotations

import threading
from collections.abc import Callable
from uuid import uuid4

from langgraph.runtime import RunControl


class RuntimeRunControl(RunControl):
    """Run control that also owns cancellation hooks for active tool I/O."""

    __slots__ = ("_tool_cancel_callbacks", "_tool_cancel_lock")

    def __init__(self) -> None:
        super().__init__()
        self._tool_cancel_lock = threading.RLock()
        self._tool_cancel_callbacks: dict[str, Callable[[], None]] = {}

    def request_drain(self, reason: str = "shutdown") -> None:
        super().request_drain(reason)
        with self._tool_cancel_lock:
            callbacks = list(self._tool_cancel_callbacks.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue

    def register_tool_cancellation(self, callback: Callable[[], None]) -> Callable[[], None]:
        registration_id = uuid4().hex
        with self._tool_cancel_lock:
            if self.drain_requested:
                cancel_now = True
            else:
                self._tool_cancel_callbacks[registration_id] = callback
                cancel_now = False
        if cancel_now:
            callback()

        def unregister() -> None:
            with self._tool_cancel_lock:
                self._tool_cancel_callbacks.pop(registration_id, None)

        return unregister


class RuntimeRunControlRegistry:
    """Own one LangGraph cooperative run control per active runtime request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controls: dict[str, RuntimeRunControl] = {}

    def register(self, request_id: str) -> RuntimeRunControl:
        control = RuntimeRunControl()
        with self._lock:
            self._controls[request_id] = control
        return control

    def request_drain(
        self,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> int:
        target = (request_id or "").strip()
        with self._lock:
            controls = (
                [self._controls[target]]
                if target and target in self._controls
                else list(self._controls.values())
                if not target
                else []
            )
            for control in controls:
                control.request_drain(reason)
            return len(controls)

    def release(self, request_id: str, control: RunControl) -> None:
        with self._lock:
            if self._controls.get(request_id) is control:
                self._controls.pop(request_id, None)
