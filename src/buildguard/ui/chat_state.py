"""Small, testable state transitions for the Streamlit chat shell."""

from __future__ import annotations

from typing import Any, Protocol, overload


class StateStore(Protocol):
    def __contains__(self, key: object) -> bool: ...

    def __getitem__(self, key: str) -> Any: ...

    def __setitem__(self, key: str, value: Any) -> None: ...

    @overload
    def get(self, key: str | int, /) -> Any | None: ...

    @overload
    def get(self, key: str | int, default: Any, /) -> Any: ...


DEFAULT_CHAT_STATE: dict[str, Any] = {
    "active_session_id": None,
    "chat_messages": [],
    "chat_results": [],
    "loaded_session_id": None,
    "pending_confirmation": None,
    "last_chat_request": None,
    "attachment_generation": 0,
    "chat_busy": False,
    "active_stream_task": None,
}


def initialize_chat_state(state: StateStore) -> None:
    for key, value in DEFAULT_CHAT_STATE.items():
        if key not in state:
            state[key] = list(value) if isinstance(value, list) else value


def reset_chat(state: StateStore) -> None:
    initialize_chat_state(state)
    state["active_session_id"] = None
    state["loaded_session_id"] = None
    state["chat_messages"] = []
    state["chat_results"] = []
    state["pending_confirmation"] = None
    state["last_chat_request"] = None
    state["attachment_generation"] = int(state["attachment_generation"]) + 1
    state["chat_busy"] = False
    state["active_stream_task"] = None


def select_session(state: StateStore, session_id: str) -> None:
    initialize_chat_state(state)
    if state["active_session_id"] == session_id:
        return
    state["active_session_id"] = session_id
    state["loaded_session_id"] = None
    state["chat_messages"] = []
    state["chat_results"] = []
    state["pending_confirmation"] = None


def append_message(
    state: StateStore,
    role: str,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    initialize_chat_state(state)
    messages = list(state["chat_messages"])
    messages.append(
        {
            "id": "",
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": "",
        }
    )
    state["chat_messages"] = messages


def record_result(state: StateStore, result: dict[str, Any]) -> None:
    initialize_chat_state(state)
    results = list(state["chat_results"])
    results.append(dict(result))
    state["chat_results"] = results
    append_message(
        state,
        "assistant",
        str(result.get("final_response") or "任务已完成，但没有文本回复。"),
        metadata={"task_id": result.get("task_id"), "result": dict(result)},
    )
    if result.get("session_id"):
        state["active_session_id"] = str(result["session_id"])
        state["loaded_session_id"] = str(result["session_id"])
    if result.get("status") == "WAIT_FOR_CONFIRMATION":
        state["pending_confirmation"] = dict(result)
    elif result.get("task_id"):
        pending = state.get("pending_confirmation")
        if isinstance(pending, dict) and pending.get("task_id") == result.get("task_id"):
            state["pending_confirmation"] = None
