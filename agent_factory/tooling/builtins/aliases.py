from __future__ import annotations

from collections.abc import Iterable


LEGACY_BUILTIN_TOOL_ALIASES: dict[str, str] = {
    "bash": "shell",
    "bash_status": "shell_status",
    "bash_stop": "shell_stop",
}


def canonical_builtin_tool_id(tool_id: str) -> str:
    normalized = str(tool_id).strip()
    return LEGACY_BUILTIN_TOOL_ALIASES.get(normalized, normalized)


def canonical_builtin_tool_ids(tool_ids: Iterable[str]) -> list[str]:
    canonical: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        normalized = canonical_builtin_tool_id(tool_id)
        if normalized and normalized not in seen:
            canonical.append(normalized)
            seen.add(normalized)
    return canonical
