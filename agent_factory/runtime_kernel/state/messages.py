from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field


class MessageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: Any
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)


def dump_message(message: BaseMessage) -> MessageRecord:
    if isinstance(message, SystemMessage):
        return MessageRecord(
            role="system",
            content=_normalize_content(message.content),
            name=message.name,
            additional_kwargs=dict(message.additional_kwargs),
            response_metadata=dict(message.response_metadata),
        )
    if isinstance(message, HumanMessage):
        return MessageRecord(
            role="user",
            content=_normalize_content(message.content),
            name=message.name,
            additional_kwargs=dict(message.additional_kwargs),
            response_metadata=dict(message.response_metadata),
        )
    if isinstance(message, ToolMessage):
        return MessageRecord(
            role="tool",
            content=_normalize_content(message.content),
            name=message.name,
            tool_call_id=message.tool_call_id,
            additional_kwargs=dict(message.additional_kwargs),
            response_metadata=dict(message.response_metadata),
        )
    if isinstance(message, AIMessage):
        return MessageRecord(
            role="assistant",
            content=_normalize_content(message.content),
            name=message.name,
            tool_calls=list(getattr(message, "tool_calls", []) or []),
            additional_kwargs=dict(message.additional_kwargs),
            response_metadata=dict(message.response_metadata),
        )
    return MessageRecord(role="user", content=_normalize_content(message.content))


def dump_messages(messages: list[BaseMessage]) -> list[MessageRecord]:
    return [dump_message(message) for message in messages]


def load_message(record: MessageRecord) -> BaseMessage:
    if record.role == "system":
        return SystemMessage(
            content=record.content,
            name=record.name,
            additional_kwargs=dict(record.additional_kwargs),
            response_metadata=dict(record.response_metadata),
        )
    if record.role == "user":
        return HumanMessage(
            content=record.content,
            name=record.name,
            additional_kwargs=dict(record.additional_kwargs),
            response_metadata=dict(record.response_metadata),
        )
    if record.role == "tool":
        return ToolMessage(
            content=record.content,
            name=record.name,
            tool_call_id=record.tool_call_id or "",
            additional_kwargs=dict(record.additional_kwargs),
            response_metadata=dict(record.response_metadata),
        )
    return AIMessage(
        content=record.content,
        name=record.name,
        tool_calls=list(record.tool_calls),
        additional_kwargs=dict(record.additional_kwargs),
        response_metadata=dict(record.response_metadata),
    )


def load_messages(records: list[MessageRecord]) -> list[BaseMessage]:
    return [load_message(record) for record in records]


def _normalize_content(content: Any) -> Any:
    if isinstance(content, (str, list, dict, int, float, bool)) or content is None:
        return content
    return json.loads(json.dumps(content, ensure_ascii=False, default=str))
