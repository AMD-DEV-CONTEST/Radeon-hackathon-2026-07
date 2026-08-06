from __future__ import annotations

from typing import Any


def memory_context_text(pack: dict[str, Any]) -> str:
    items = list(pack.get("items") or [])
    if not items:
        return ""
    lines: list[str] = []
    for item in items:
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"- {content}")
    return "\n".join(lines)
