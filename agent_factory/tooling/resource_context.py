from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel


JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | dict[str, Any] | list[Any]


def build_tool_resource_context(resources: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Return the JSON-safe resource view used by risk, approval, and trace.

    Tool entrypoints receive real runtime resources. Risk evaluators receive this
    projection so service objects, clients, stores, and runtime instances never
    leak into Pydantic JSON serialization or frontend payloads.
    """

    return {str(key): _resource_summary(value) for key, value in resources.items()}


def _resource_summary(value: Any) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return _resource_summary(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _resource_summary(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_resource_summary(item) for item in value]
    custom_summary = _custom_summary(value)
    if custom_summary is not None:
        return _resource_summary(custom_summary)
    if _is_json_serializable(value):
        return value
    return {
        "kind": "runtime_object",
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
    }


def _custom_summary(value: Any) -> Any | None:
    for method_name in ("tool_resource_context", "tool_resource_summary"):
        method = getattr(value, method_name, None)
        if callable(method):
            return method()
    return None


def _is_json_serializable(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return True
