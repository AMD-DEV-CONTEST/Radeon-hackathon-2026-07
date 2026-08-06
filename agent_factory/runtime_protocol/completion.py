from __future__ import annotations

from typing import Any


SUCCESSFUL_RUNTIME_FINISH_STATUSES = frozenset({"completed", "waiting_for_workers"})


def runtime_completed(state: Any) -> bool:
    execution = getattr(state, "execution", None)
    return bool(
        execution is not None
        and getattr(execution, "finish_status", None) in SUCCESSFUL_RUNTIME_FINISH_STATUSES
        and not getattr(execution, "last_error", None)
    )


def runtime_error_message(state: Any, *, command: str) -> str:
    execution = getattr(state, "execution", None)
    if execution is None:
        return f"{command} failed without runtime execution state"
    return str(
        getattr(execution, "last_error", None)
        or f"{command} finished with status {getattr(execution, 'finish_status', None) or 'unknown'}"
    )
