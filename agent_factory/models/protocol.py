from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


StructuredOutputMethod = Literal["function_calling", "json_mode", "json_schema"]
ModelTransport = Literal["local_llama_cpp"]
ContentPartType = Literal["text", "image", "file", "audio", "video"]
ModelStreamEventType = Literal[
    "message_start",
    "text_delta",
    "reasoning_delta",
    "reasoning_summary_delta",
    "tool_call_start",
    "tool_call_delta",
    "tool_call_done",
    "usage_update",
    "message_done",
    "error",
]


@dataclass(frozen=True, slots=True)
class ModelReasoningSettings:
    enabled: bool | None = None
    effort: str | None = None
    summary: str | None = None
    budget_tokens: int | None = None
    send_history: bool | None = None

    @property
    def mode(self) -> str | None:
        if self.enabled is True:
            return "enabled"
        if self.enabled is False:
            return "disabled"
        return None


@dataclass(frozen=True, slots=True)
class ModelContentPart:
    type: ContentPartType
    text: str | None = None
    mime_type: str | None = None
    url: str | None = None
    file_id: str | None = None
    data: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: tuple[ModelContentPart, ...] = ()
    tool_calls: tuple[ModelToolCall, ...] = ()
    tool_call_id: str | None = None
    reasoning_content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    model: str
    messages: tuple[ModelMessage, ...]
    tools: tuple[dict[str, Any], ...] = ()
    tool_choice: str | dict[str, Any] | None = None
    structured_output_method: StructuredOutputMethod | None = None
    reasoning: ModelReasoningSettings = field(default_factory=ModelReasoningSettings)
    stream: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    type: ModelStreamEventType
    stream_id: str
    delta: str | None = None
    tool_call: ModelToolCall | None = None
    usage: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
