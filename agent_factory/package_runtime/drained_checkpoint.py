from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import RemoveMessage
from langgraph.graph import END
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_protocol.messages import (
    close_incomplete_tool_call_history,
    has_complete_tool_call_history,
)


INTERRUPTED_TOOL_MESSAGE_CONTENT = "工具调用在开始执行前因用户停止而取消，未产生结果。"


@dataclass(frozen=True, slots=True)
class DrainedRuntimeCheckpoint:
    state: RuntimeState
    messages: list[Any]


def finalize_drained_message_checkpoint(
    *,
    graph_app: Any,
    thread_id: str,
    stop_reason: str,
) -> list[Any]:
    """Normalize message history after LangGraph has raised GraphDrained."""
    config, values = _settled_checkpoint_values(
        graph_app,
        thread_id=thread_id,
    )
    messages = _drained_messages(values.get("messages"), stop_reason=stop_reason)
    _materialize_checkpoint_update(
        graph_app,
        config=config,
        values={
            **values,
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *messages],
        },
    )
    return messages


def finalize_drained_runtime_checkpoint(
    *,
    compiled_app: Any,
    thread_id: str,
    base_state: RuntimeState,
    fallback_user_input: str,
    stop_reason: str,
) -> DrainedRuntimeCheckpoint:
    """Normalize runtime state and messages after LangGraph has fully drained."""
    config, values = _settled_checkpoint_values(
        compiled_app.graph_app,
        thread_id=thread_id,
    )
    checkpoint_state = _checkpoint_runtime_state(values) or base_state
    drained_state = _drained_runtime_state(
        checkpoint_state,
        fallback_user_input=fallback_user_input,
    )
    messages = _drained_messages(values.get("messages"), stop_reason=stop_reason)
    _materialize_checkpoint_update(
        compiled_app.graph_app,
        config=config,
        values={
            **values,
            "runtime": drained_state.model_dump(mode="python"),
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *messages],
        },
    )
    return DrainedRuntimeCheckpoint(state=drained_state, messages=messages)


def repair_incomplete_message_checkpoint(
    *,
    graph_app: Any,
    thread_id: str,
) -> bool:
    """Repair a previously interrupted checkpoint before accepting new input."""
    config = {"configurable": {"thread_id": thread_id}}
    values = _checkpoint_values(graph_app, config=config)
    messages = list(values.get("messages") or [])
    if has_complete_tool_call_history(messages):
        return False
    settled_config, settled_values = _settled_checkpoint_values(
        graph_app,
        thread_id=thread_id,
    )
    repaired_messages = _drained_messages(
        settled_values.get("messages"),
        stop_reason="previous_run_interrupted",
    )
    _materialize_checkpoint_update(
        graph_app,
        config=settled_config,
        values={
            **settled_values,
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *repaired_messages,
            ]
        },
    )
    return True


def _settled_checkpoint_values(
    graph_app: Any,
    *,
    thread_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = {"configurable": {"thread_id": thread_id}}
    settled_config = graph_app.update_state(config, None, as_node=END)
    return settled_config, _checkpoint_values(graph_app, config=settled_config)


def _materialize_checkpoint_update(
    graph_app: Any,
    *,
    config: dict[str, Any],
    values: dict[str, Any],
) -> None:
    pending_config = graph_app.update_state(config, values)
    settled_config = graph_app.update_state(pending_config, None, as_node=END)
    settled_values = _checkpoint_values(graph_app, config=settled_config)
    if not has_complete_tool_call_history(list(settled_values.get("messages") or [])):
        raise RuntimeError("drained checkpoint contains incomplete tool-call history")


def _checkpoint_values(
    graph_app: Any,
    *,
    config: dict[str, Any],
) -> dict[str, Any]:
    try:
        snapshot = graph_app.get_state(config)
    except Exception:
        return {}
    values = getattr(snapshot, "values", {}) or {}
    return dict(values) if isinstance(values, dict) else {}


def _checkpoint_runtime_state(values: dict[str, Any]) -> RuntimeState | None:
    runtime = values.get("runtime")
    if runtime is None:
        return None
    try:
        return RuntimeState.model_validate(runtime)
    except Exception:
        return None


def _drained_runtime_state(
    state: RuntimeState,
    *,
    fallback_user_input: str,
) -> RuntimeState:
    drained = state.model_copy(deep=True)
    if fallback_user_input and not drained.conversation.current_user_input:
        drained.conversation.current_user_input = fallback_user_input
    drained.policy.interrupted = False
    drained.policy.interrupt_required = False
    drained.policy.approval_required = False
    drained.execution.finished = True
    drained.execution.finish_status = "stopped"
    drained.execution.interrupted = False
    drained.execution.last_error = None
    drained.execution.last_error_location = None
    return drained


def _drained_messages(raw_messages: Any, *, stop_reason: str) -> list[Any]:
    return close_incomplete_tool_call_history(
        list(raw_messages or []),
        content=(
            "工具调用因用户发送新的引导而取消，未产生结果。"
            if stop_reason == "user_steered"
            else (
                "工具调用因上一次运行中断而取消，未产生结果。"
                if stop_reason == "previous_run_interrupted"
                else INTERRUPTED_TOOL_MESSAGE_CONTENT
            )
        ),
    )
