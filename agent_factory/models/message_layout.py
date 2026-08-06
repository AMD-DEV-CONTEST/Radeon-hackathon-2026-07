from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from langchain_core.messages import SystemMessage


def system_messages_first(messages: Iterable[Any]) -> list[Any]:
    """Return messages with every SystemMessage moved before non-system messages."""
    items = list(messages)
    system_messages = [message for message in items if isinstance(message, SystemMessage)]
    if not system_messages:
        return items
    non_system_messages = [message for message in items if not isinstance(message, SystemMessage)]
    return [*system_messages, *non_system_messages]
