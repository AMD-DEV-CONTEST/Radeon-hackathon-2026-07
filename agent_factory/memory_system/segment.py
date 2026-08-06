from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agent_factory.memory_system.schema import MemoryConversationMessage, MemoryConversationSegment, MemoryScope


def build_conversation_segment(
    *,
    scope: MemoryScope,
    namespace: tuple[str, ...],
    source: dict[str, Any],
    messages: Any,
    end_turn: int,
    max_user_turns: int,
) -> MemoryConversationSegment | None:
    normalized = normalize_conversation_messages(messages)
    if not normalized:
        return None
    user_positions = [index for index, message in enumerate(normalized) if message.role == "user"]
    if not user_positions:
        return None
    turn_window = max(1, min(int(max_user_turns), len(user_positions)))
    start_index = user_positions[-turn_window]
    selected = normalized[start_index:]
    if not selected:
        return None
    safe_end_turn = max(1, int(end_turn or len(user_positions)))
    return MemoryConversationSegment(
        scope=scope,
        namespace=namespace,
        start_turn=max(1, safe_end_turn - turn_window + 1),
        end_turn=safe_end_turn,
        messages=selected,
        source=source,
    )


def normalize_conversation_messages(messages: Any) -> list[MemoryConversationMessage]:
    if not isinstance(messages, list):
        return []
    normalized: list[MemoryConversationMessage] = []
    turn_index = 0
    for index, message in enumerate(messages):
        role, content = _message_role_content(message)
        if role is None or not content.strip():
            continue
        if role == "user":
            turn_index += 1
        normalized.append(
            MemoryConversationMessage(
                role=role,
                content=content.strip(),
                turn_index=turn_index or None,
                message_index=index,
            )
        )
    return normalized


def segment_query_text(segment: MemoryConversationSegment) -> str:
    return "\n".join(f"{message.role}: {message.content}" for message in segment.messages)


def _message_role_content(message: Any) -> tuple[str | None, str]:
    if isinstance(message, HumanMessage):
        return "user", _string_content(message.content)
    if isinstance(message, AIMessage):
        if getattr(message, "tool_calls", None):
            return None, ""
        return "assistant", _string_content(message.content)
    if isinstance(message, BaseMessage):
        return None, ""
    if isinstance(message, dict):
        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            return None, ""
        return role, _string_content(message.get("content"))
    return None, ""


def _string_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content or "")
