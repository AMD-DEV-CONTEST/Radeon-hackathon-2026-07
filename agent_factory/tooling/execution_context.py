from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
import threading
from typing import Any, Callable, Iterator, Mapping


@dataclass(frozen=True, slots=True)
class CurrentToolCall:
    tool_id: str
    tool_call_id: str
    origin_node_id: str = ""
    origin_impl: str = ""
    event_sink: Callable[[dict[str, Any]], None] | None = None
    runtime_resource_overrides: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ToolApprovalOverride:
    reason: str


_CURRENT_TOOL_CALL: ContextVar[CurrentToolCall | None] = ContextVar(
    "agentfactory_current_tool_call",
    default=None,
)
_TOOL_APPROVAL_OVERRIDE: ContextVar[ToolApprovalOverride | None] = ContextVar(
    "agentfactory_tool_approval_override",
    default=None,
)
_TOOL_OUTPUT_SESSION_ID: ContextVar[str | None] = ContextVar(
    "agentfactory_tool_output_session_id",
    default=None,
)
_RUNTIME_RUN_CONTROL: ContextVar[Any | None] = ContextVar(
    "agentfactory_runtime_run_control",
    default=None,
)


class RuntimeToolExecutionCancelled(RuntimeError):
    pass


@contextmanager
def tool_call_context(
    *,
    tool_id: str,
    tool_call_id: str,
    origin_node_id: str = "",
    origin_impl: str = "",
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    runtime_resource_overrides: Mapping[str, Any] | None = None,
) -> Iterator[None]:
    token = _CURRENT_TOOL_CALL.set(
        CurrentToolCall(
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            origin_node_id=origin_node_id,
            origin_impl=origin_impl,
            event_sink=event_sink,
            runtime_resource_overrides=dict(runtime_resource_overrides or {}),
        )
    )
    try:
        yield
    finally:
        _CURRENT_TOOL_CALL.reset(token)


@contextmanager
def tool_approval_override(*, reason: str) -> Iterator[None]:
    token = _TOOL_APPROVAL_OVERRIDE.set(ToolApprovalOverride(reason=reason))
    try:
        yield
    finally:
        _TOOL_APPROVAL_OVERRIDE.reset(token)


@contextmanager
def tool_output_session_context(session_id: str) -> Iterator[None]:
    normalized = str(session_id or "").strip()
    if not normalized:
        raise ValueError("tool output session id is required")
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError("tool output session id must be a path-safe identifier")
    token = _TOOL_OUTPUT_SESSION_ID.set(normalized)
    try:
        yield
    finally:
        _TOOL_OUTPUT_SESSION_ID.reset(token)


@contextmanager
def runtime_run_control_context(control: Any | None) -> Iterator[None]:
    token = _RUNTIME_RUN_CONTROL.set(control)
    try:
        yield
    finally:
        _RUNTIME_RUN_CONTROL.reset(token)


def current_tool_call() -> CurrentToolCall | None:
    return _CURRENT_TOOL_CALL.get()


def current_tool_event_sink() -> Callable[[dict[str, Any]], None] | None:
    current = current_tool_call()
    return current.event_sink if current is not None else None


def current_tool_runtime_resource_overrides() -> Mapping[str, Any]:
    current = current_tool_call()
    return current.runtime_resource_overrides if current is not None and current.runtime_resource_overrides else {}


def current_tool_approval_override() -> ToolApprovalOverride | None:
    return _TOOL_APPROVAL_OVERRIDE.get()


def current_tool_output_session_id() -> str | None:
    return _TOOL_OUTPUT_SESSION_ID.get()


def current_runtime_run_control() -> Any | None:
    return _RUNTIME_RUN_CONTROL.get()


def register_runtime_tool_cancellation(callback: Callable[[], None]) -> Callable[[], None]:
    control = current_runtime_run_control()
    register = getattr(control, "register_tool_cancellation", None)
    if callable(register):
        return register(callback)
    if control is not None and bool(getattr(control, "drain_requested", False)):
        callback()
    return lambda: None


def execute_with_runtime_cancellation(operation: Callable[[], Any]) -> Any:
    """Run a synchronous tool operation behind the shared run cancellation boundary.

    Python cannot safely terminate an arbitrary worker thread. On cancellation the
    graph is released immediately and the worker is detached; cancellable tools such
    as MCP and shell also register their own hook to terminate external I/O.
    """

    control = current_runtime_run_control()
    if control is None:
        return operation()
    if bool(getattr(control, "drain_requested", False)):
        raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))

    completed = threading.Event()
    cancelled = threading.Event()
    outcome: dict[str, Any] = {}
    context = copy_context()

    def run() -> None:
        try:
            outcome["value"] = context.run(operation)
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            completed.set()

    unregister = register_runtime_tool_cancellation(cancelled.set)
    worker = threading.Thread(target=run, name="agentfactory-tool-call", daemon=True)
    worker.start()
    try:
        while not completed.is_set():
            if cancelled.wait(timeout=0.05) or bool(getattr(control, "drain_requested", False)):
                raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))
        if cancelled.is_set() or bool(getattr(control, "drain_requested", False)):
            raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))
        error = outcome.get("error")
        if error is not None:
            raise error
        return outcome.get("value")
    finally:
        unregister()


def _runtime_cancel_reason(control: Any) -> str:
    reason = str(getattr(control, "drain_reason", None) or "user_cancelled")
    return f"Tool execution cancelled: {reason}"
