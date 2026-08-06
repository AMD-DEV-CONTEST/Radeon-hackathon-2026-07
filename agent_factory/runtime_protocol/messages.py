from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage


def has_complete_tool_call_history(messages: Sequence[Any]) -> bool:
    pending: list[str] = []
    for message in messages:
        if _is_tool_message(message):
            tool_call_id = _tool_message_call_id(message)
            if tool_call_id not in pending:
                return False
            pending = [item for item in pending if item != tool_call_id]
            continue
        if pending:
            return False
        tool_calls = _tool_calls(message)
        if tool_calls:
            pending = [_tool_call_id(call) for call in tool_calls if _tool_call_id(call)]
    return not pending


def close_incomplete_tool_call_history(
    messages: Sequence[Any],
    *,
    content: str,
) -> list[Any]:
    closed: list[Any] = []
    pending: list[str] = []
    for message in messages:
        if _is_tool_message(message):
            tool_call_id = _tool_message_call_id(message)
            if tool_call_id not in pending:
                continue
            closed.append(message)
            pending = [item for item in pending if item != tool_call_id]
            continue
        if pending:
            closed.extend(_interrupted_tool_messages(pending, content))
            pending = []
        closed.append(message)
        tool_calls = _tool_calls(message)
        if tool_calls:
            pending = [_tool_call_id(call) for call in tool_calls if _tool_call_id(call)]
    if pending:
        closed.extend(_interrupted_tool_messages(pending, content))
    return closed


def incomplete_tool_call_ids(messages: Sequence[Any]) -> list[str]:
    missing: list[str] = []
    pending: list[str] = []
    for message in messages:
        if pending and not _is_tool_message(message):
            missing.extend(pending)
            pending = []
        tool_calls = _tool_calls(message)
        if tool_calls:
            pending = [_tool_call_id(call) for call in tool_calls if _tool_call_id(call)]
            continue
        if _is_tool_message(message):
            tool_call_id = _tool_message_call_id(message)
            if tool_call_id in pending:
                pending = [item for item in pending if item != tool_call_id]
    if pending:
        missing.extend(pending)
    return missing


def _interrupted_tool_messages(tool_call_ids: Sequence[str], content: str) -> list[ToolMessage]:
    return [
        ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            status="error",
            additional_kwargs={"factory_control": {"type": "tool_execution_interrupted"}},
        )
        for tool_call_id in tool_call_ids
    ]


def _tool_calls(message: Any) -> list[Any]:
    if isinstance(message, AIMessage):
        return [
            *list(getattr(message, "tool_calls", None) or []),
            *list(getattr(message, "invalid_tool_calls", None) or []),
        ]
    if not isinstance(message, dict):
        return []
    if _message_type(message) != "ai":
        return []
    calls = message.get("tool_calls")
    if calls is None and isinstance(message.get("data"), dict):
        calls = message["data"].get("tool_calls")
    invalid_calls = message.get("invalid_tool_calls")
    if invalid_calls is None and isinstance(message.get("data"), dict):
        invalid_calls = message["data"].get("invalid_tool_calls")
    items: list[Any] = []
    if isinstance(calls, list):
        items.extend(calls)
    if isinstance(invalid_calls, list):
        items.extend(invalid_calls)
    return items


def _tool_call_id(call: Any) -> str:
    if not isinstance(call, dict):
        return ""
    return str(call.get("id") or call.get("tool_call_id") or "")


def _is_tool_message(message: Any) -> bool:
    return isinstance(message, ToolMessage) or (isinstance(message, dict) and _message_type(message) == "tool")


def _tool_message_call_id(message: Any) -> str:
    if isinstance(message, ToolMessage):
        return str(getattr(message, "tool_call_id", "") or "")
    if not isinstance(message, dict):
        return ""
    if message.get("tool_call_id"):
        return str(message.get("tool_call_id") or "")
    data = message.get("data")
    if isinstance(data, dict):
        return str(data.get("tool_call_id") or "")
    return ""


def _message_type(message: dict[str, Any]) -> str:
    value = str(message.get("type") or message.get("role") or "").lower()
    if value in {"ai", "assistant"}:
        return "ai"
    if value == "tool":
        return "tool"
    data = message.get("data")
    if isinstance(data, dict):
        nested = str(data.get("type") or data.get("role") or "").lower()
        if nested in {"ai", "assistant"}:
            return "ai"
        if nested == "tool":
            return "tool"
    return value
