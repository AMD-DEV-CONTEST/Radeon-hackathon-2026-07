from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_openai import ChatOpenAI

from agent_factory.models.reasoning import (
    coerce_reasoning_content,
    reasoning_content_from_blocks,
    reasoning_content_from_message,
    reasoning_content_from_raw_message,
    reasoning_content_from_stream_chunk,
)


class ThinkingCompatibleChatOpenAI(ChatOpenAI):
    """ChatOpenAI adapter for OpenAI-compatible thinking-mode providers."""

    preserve_reasoning_content: bool = False

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        _normalize_tool_call_arguments_payload(payload.get("messages"))
        if not self.preserve_reasoning_content:
            return payload
        source_messages = self._convert_input(input_).to_messages()
        payload_messages = payload.get("messages")
        if isinstance(payload_messages, list):
            _patch_reasoning_content_payload(payload_messages, source_messages)
        return payload

    def _create_chat_result(self, response: Any, generation_info: dict | None = None):
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices") or []
        for generation, choice in zip(result.generations, choices, strict=False):
            message = generation.message
            if not isinstance(message, AIMessage):
                continue
            reasoning_content = _reasoning_content_from_raw_message(choice.get("message") or {})
            if reasoning_content is not None:
                message.additional_kwargs["reasoning_content"] = reasoning_content
        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ):
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None
        reasoning_content = reasoning_content_from_stream_chunk(chunk)
        if reasoning_content is None:
            return generation_chunk
        message = getattr(generation_chunk, "message", None)
        if isinstance(message, AIMessageChunk):
            message.additional_kwargs["reasoning_content"] = reasoning_content
            message.response_metadata["reasoning_content"] = reasoning_content
        return generation_chunk


def _normalize_tool_call_arguments_payload(messages: Any) -> None:
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict):
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict) or "arguments" not in function:
                continue
            function["arguments"] = _json_argument_string(function.get("arguments"))


def _json_argument_string(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "{}"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return json.dumps(text, ensure_ascii=False, default=str)
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"), default=str)
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"), default=str)


def _patch_reasoning_content_payload(
    payload_messages: list[dict[str, Any]],
    source_messages: list[BaseMessage],
) -> None:
    source_index = 0
    for payload_message in payload_messages:
        if payload_message.get("role") != "assistant":
            continue
        source_entry = _next_ai_message(source_messages, source_index)
        if source_entry is None:
            continue
        source_index, source_message = source_entry
        source_index += 1
        reasoning_content = _reasoning_content_from_ai_message(source_message)
        if reasoning_content is not None:
            payload_message["reasoning_content"] = reasoning_content
        elif payload_message.get("tool_calls"):
            payload_message["reasoning_content"] = ""


def _next_ai_message(messages: list[BaseMessage], start: int) -> tuple[int, AIMessage] | None:
    for index, message in enumerate(messages[start:], start=start):
        if isinstance(message, AIMessage):
            return index, message
    return None


def _reasoning_content_from_raw_message(message: dict[str, Any]) -> str | None:
    return reasoning_content_from_raw_message(message)


def _reasoning_content_from_ai_message(message: AIMessage) -> str | None:
    return reasoning_content_from_message(message)


def _reasoning_content_from_blocks(content: Any) -> str | None:
    return reasoning_content_from_blocks(content)


def _coerce_reasoning_content(value: Any) -> str | None:
    return coerce_reasoning_content(value)
