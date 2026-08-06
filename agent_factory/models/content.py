from __future__ import annotations

import re
from typing import Any

from agent_factory.models.reasoning import is_reasoning_content_block


_INTERNAL_SESSION_SNAPSHOT_BLOCK_RE = re.compile(
    r"<session_snapshot\b[^>]*>.*?</session_snapshot>",
    re.IGNORECASE | re.DOTALL,
)
_INTERNAL_SESSION_SNAPSHOT_OPEN_RE = re.compile(
    r"<session_snapshot\b[^>]*>.*$",
    re.IGNORECASE,
)


def content_to_text(content: Any) -> str:
    """Convert provider/LangChain content blocks into visible assistant text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _content_part_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(content) if content else ""


def strip_internal_snapshot_blocks(value: str) -> str:
    """Remove private context snapshots only when text is leaving the model as user-visible output."""
    if not value:
        return ""
    text = _INTERNAL_SESSION_SNAPSHOT_BLOCK_RE.sub("", value)
    return _INTERNAL_SESSION_SNAPSHOT_OPEN_RE.sub("", text)


def _content_part_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ""
    if is_reasoning_content_block(item):
        return ""
    value = item.get("text") or item.get("content")
    return str(value) if value else ""
