from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


REDACTED_VALUE = "[REDACTED]"


def redact_json_pointer_paths(value: Any, paths: Iterable[str]) -> Any:
    """Return a copy with values selected by RFC 6901 JSON Pointers redacted."""
    redacted = deepcopy(value)
    for pointer in paths:
        _redact_pointer(redacted, str(pointer))
    return redacted


def _redact_pointer(root: Any, pointer: str) -> None:
    tokens = [_decode_pointer_token(token) for token in pointer.removeprefix("/").split("/")]
    if not tokens:
        return
    parent = root
    for token in tokens[:-1]:
        parent = _child(parent, token)
        if parent is None:
            return
    leaf = tokens[-1]
    if isinstance(parent, dict) and leaf in parent:
        parent[leaf] = REDACTED_VALUE
    elif isinstance(parent, list):
        index = _list_index(leaf, len(parent))
        if index is not None:
            parent[index] = REDACTED_VALUE


def _child(parent: Any, token: str) -> Any | None:
    if isinstance(parent, dict):
        return parent.get(token)
    if isinstance(parent, list):
        index = _list_index(token, len(parent))
        return parent[index] if index is not None else None
    return None


def _list_index(token: str, length: int) -> int | None:
    try:
        index = int(token)
    except ValueError:
        return None
    return index if 0 <= index < length else None


def _decode_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")
