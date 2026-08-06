from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class RuntimeGraphState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    runtime: Annotated[dict[str, Any], merge_runtime_patch]


def merge_runtime_patch(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    if left is None:
        return dict(right or {})
    if right is None:
        return dict(left)
    return _deep_merge(dict(left), dict(right))


def _deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged
