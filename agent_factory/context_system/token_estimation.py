from __future__ import annotations

from typing import Any


def estimate_messages_tokens(messages: list[Any]) -> int:
    return sum(estimate_text_tokens(message_text(message)) for message in messages)


def estimate_text_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)
