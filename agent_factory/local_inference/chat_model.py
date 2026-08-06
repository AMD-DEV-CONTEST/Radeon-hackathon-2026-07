from __future__ import annotations

import json
import logging
import re
import sys
import threading
from operator import itemgetter
from typing import Any, Iterator, Sequence
from uuid import uuid4

import httpx
from langchain_core.language_models.chat_models import BaseChatModel, generate_from_stream
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    get_buffer_string,
)
from langchain_core.output_parsers import JsonOutputParser, PydanticOutputParser
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableMap, RunnablePassthrough
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, Field
from langgraph.errors import GraphDrained

from agent_factory.local_inference.config import LocalInferenceEndpoint
from agent_factory.local_inference.http_client import create_private_http_client
from agent_factory.local_inference.request_context import current_inference_request
from agent_factory.tooling.execution_context import current_runtime_run_control


logger = logging.getLogger(__name__)


def _priority_for_role(role: str) -> str:
    normalized = str(role or "main").strip().lower()
    if normalized == "compression":
        return "background"
    if normalized == "task":
        return "normal"
    return "foreground"


class LocalLlamaCppChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    endpoint: LocalInferenceEndpoint
    temperature: float | None = None
    max_output_tokens: int | None = None
    reasoning_enabled: bool | None = None
    model_role: str = "main"
    bound_tools: list[dict[str, Any]] = Field(default_factory=list)
    bound_tool_choice: str | dict[str, Any] | None = None

    @property
    def _llm_type(self) -> str:
        return "local_llama_cpp_rocm"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "transport": "local_llama_cpp"}

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool],
        *,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        converted = [convert_to_openai_tool(tool) for tool in tools]
        return self.model_copy(
            update={
                "bound_tools": converted,
                "bound_tool_choice": _llama_cpp_tool_choice(tool_choice),
            },
            deep=True,
        )

    def with_structured_output(
        self,
        schema: dict[str, Any] | type,
        *,
        include_raw: bool = False,
        method: str | None = None,
        strict: bool | None = None,
        **kwargs: Any,
    ):
        if kwargs:
            names = ", ".join(sorted(kwargs))
            raise ValueError(f"unsupported structured output arguments: {names}")
        structured_method = str(method or "function_calling").strip()
        if structured_method == "function_calling":
            return super().with_structured_output(schema, include_raw=include_raw)
        if structured_method != "json_mode":
            raise ValueError(f"unsupported structured output method: {structured_method}")

        response_format = {
            "type": "json_schema",
            "schema": _structured_json_schema(schema),
        }
        raw_model = self.bind(response_format=response_format)
        parser = (
            PydanticOutputParser(pydantic_object=schema)
            if isinstance(schema, type) and issubclass(schema, BaseModel)
            else JsonOutputParser()
        )
        if not include_raw:
            return raw_model | parser
        parser_assign = RunnablePassthrough.assign(
            parsed=itemgetter("raw") | parser,
            parsing_error=lambda _: None,
        )
        parser_none = RunnablePassthrough.assign(parsed=lambda _: None)
        return RunnableMap(raw=raw_model) | parser_assign.with_fallbacks(
            [parser_none],
            exception_key="parsing_error",
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        return generate_from_stream(
            self._stream(
                messages,
                stop=stop,
                run_manager=run_manager,
                **kwargs,
            )
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        _raise_if_runtime_stopped()
        payload = self._request_payload(messages, stop=stop, stream=True, kwargs=kwargs)
        self._log_request_started(payload)
        client = create_private_http_client(self.endpoint)
        stream_context = client.stream(
            "POST",
            self.endpoint.endpoint("/chat/completions"),
            json=payload,
            headers=self._admission_headers(),
        )
        detached = False
        lines: Iterator[str] | None = None
        try:
            response = stream_context.__enter__()
            if response.is_error:
                response.read()
                _raise_for_local_inference_error(response)
            lines = response.iter_lines()
            stop_reason = _runtime_stop_reason()
            if stop_reason is not None:
                _drain_stream_in_background(
                    lines=lines,
                    stream_context=stream_context,
                    client=client,
                )
                detached = True
                raise GraphDrained(stop_reason)
            for line in lines:
                stop_reason = _runtime_stop_reason()
                if stop_reason is not None:
                    _drain_stream_in_background(
                        lines=lines,
                        stream_context=stream_context,
                        client=client,
                    )
                    detached = True
                    raise GraphDrained(stop_reason)
                data = _sse_data(line)
                if data is None:
                    continue
                if data == "[DONE]":
                    return
                try:
                    event = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("llama.cpp returned an invalid SSE JSON event") from exc
                if not isinstance(event, dict):
                    raise RuntimeError("llama.cpp returned a non-object SSE event")
                error = event.get("error")
                if error is not None:
                    detail = _stream_error_detail(error)
                    raise RuntimeError(f"llama.cpp streaming request failed: {detail}")
                chunk = _chat_generation_chunk(event)
                if chunk is not None:
                    yield chunk
        finally:
            if not detached and lines is not None and _runtime_stop_reason() is not None:
                _drain_stream_in_background(
                    lines=lines,
                    stream_context=stream_context,
                    client=client,
                )
                detached = True
            if not detached:
                try:
                    stream_context.__exit__(*sys.exc_info())
                finally:
                    client.close()

    def _request_payload(
        self,
        messages: list[BaseMessage],
        *,
        stop: list[str] | None,
        stream: bool,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [_message_payload(message) for message in messages],
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        tools = kwargs.get("tools") or self.bound_tools
        tool_choice = kwargs.get("tool_choice") or self.bound_tool_choice
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = _llama_cpp_tool_choice(tool_choice) or "auto"
            payload["parse_tool_calls"] = True
        response_format = kwargs.get("response_format")
        if response_format is not None:
            payload["response_format"] = response_format
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_output_tokens is not None:
            payload["max_tokens"] = self.max_output_tokens
        if stop:
            payload["stop"] = stop
        if self.reasoning_enabled is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": self.reasoning_enabled}
        return payload

    def _log_request_started(self, payload: dict[str, Any]) -> None:
        logger.info(
            "llama.cpp chat request started: endpoint=%s model=%s stream=%s messages=%d tools=%d reasoning=%s",
            self.endpoint.endpoint("/chat/completions"),
            self.model_name,
            bool(payload.get("stream")),
            len(payload.get("messages") or []),
            len(payload.get("tools") or []),
            self.reasoning_enabled,
        )

    def _admission_headers(self) -> dict[str, str]:
        context = current_inference_request()
        priority = context.priority if context is not None and context.priority else _priority_for_role(self.model_role)
        headers = {"x-agentfactory-priority": priority}
        if context is not None:
            headers["x-agentfactory-session-id"] = context.session_id
            if context.request_id:
                headers["x-agentfactory-request-id"] = context.request_id
        return headers

    def get_token_ids(self, text: str) -> list[int]:
        with create_private_http_client(self.endpoint) as client:
            response = client.post(
                self.endpoint.server_endpoint("/tokenize"),
                json={"content": text, "add_special": False},
            )
            _raise_for_local_inference_error(response)
            payload = response.json()
        tokens = payload.get("tokens") if isinstance(payload, dict) else None
        if not isinstance(tokens, list) or not all(isinstance(token, int) for token in tokens):
            raise ValueError("llama-server tokenize response does not contain integer tokens")
        return tokens

    def get_num_tokens_from_messages(
        self,
        messages: list[BaseMessage],
        tools: Sequence[Any] | None = None,
    ) -> int:
        if not messages and not tools:
            return 0
        rendered = get_buffer_string(messages)
        if tools:
            rendered = "\n\n".join(
                (
                    rendered,
                    "Tools:\n"
                    + json.dumps(
                        [convert_to_openai_tool(tool) for tool in tools],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
        return len(self.get_token_ids(rendered))


def _raise_if_runtime_stopped() -> None:
    reason = _runtime_stop_reason()
    if reason is None:
        return
    raise GraphDrained(reason)


def _runtime_stop_reason() -> str | None:
    control = current_runtime_run_control()
    if control is None or not bool(getattr(control, "drain_requested", False)):
        return None
    return str(getattr(control, "drain_reason", None) or "user_cancelled")


def _drain_stream_in_background(
    *,
    lines: Iterator[str],
    stream_context: Any,
    client: httpx.Client,
) -> None:
    request = current_inference_request()
    request_id = str(request.request_id or "runtime") if request is not None else "runtime"

    def drain() -> None:
        try:
            for _line in lines:
                pass
        except Exception as exc:
            logger.warning(
                "detached llama.cpp stream drain ended with %s: %s",
                type(exc).__name__,
                exc,
            )
        finally:
            try:
                stream_context.__exit__(None, None, None)
            finally:
                client.close()

    threading.Thread(
        target=drain,
        name=f"llama-stream-drain-{request_id}",
        daemon=True,
    ).start()


def _message_payload(message: BaseMessage) -> dict[str, Any]:
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }
    elif isinstance(message, AIMessage):
        payload: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": str(call.get("id") or uuid4().hex),
                    "type": "function",
                    "function": {
                        "name": str(call.get("name") or ""),
                        "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        reasoning = message.additional_kwargs.get("reasoning_content")
        if reasoning is not None:
            payload["reasoning_content"] = reasoning
        return payload
    else:
        role = str(getattr(message, "type", "user") or "user")
    return {"role": role, "content": message.content}


def _response_message(body: dict[str, Any]) -> AIMessage:
    choice = _choice(body)
    raw_message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    tool_calls = []
    for item in raw_message.get("tool_calls") or []:
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function.get("name") or "")
        if not name:
            continue
        tool_calls.append(
            {
                "id": str(item.get("id") or uuid4().hex),
                "name": name,
                "args": _tool_arguments(function.get("arguments")),
                "type": "tool_call",
            }
        )
    content = raw_message.get("content") or ""
    if not tool_calls:
        tool_calls = _xml_tool_calls(content)
        if tool_calls:
            content = _without_xml_tool_calls(content)
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    additional_kwargs: dict[str, Any] = {}
    if raw_message.get("reasoning_content") is not None:
        additional_kwargs["reasoning_content"] = raw_message.get("reasoning_content")
    return AIMessage(
        content=content,
        tool_calls=tool_calls,
        additional_kwargs=additional_kwargs,
        usage_metadata=_usage_metadata(usage),
        response_metadata={
            "finish_reason": choice.get("finish_reason"),
            "model": body.get("model"),
        },
    )


def _chat_generation_chunk(body: dict[str, Any]) -> ChatGenerationChunk | None:
    choices = body.get("choices")
    choice = (
        choices[0]
        if isinstance(choices, list) and choices and isinstance(choices[0], dict)
        else None
    )
    delta = (
        choice.get("delta")
        if isinstance(choice, dict) and isinstance(choice.get("delta"), dict)
        else {}
    )
    content = delta.get("content")
    if not isinstance(content, (str, list)):
        content = ""
    reasoning = _stream_reasoning_content(delta)
    tool_call_chunks = _tool_call_chunks(delta.get("tool_calls"))
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
    usage_metadata = _usage_metadata(usage) if usage is not None else None
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    timings = body.get("timings") if isinstance(body.get("timings"), dict) else None
    if (
        not content
        and not reasoning
        and not tool_call_chunks
        and usage_metadata is None
        and finish_reason is None
    ):
        return None

    additional_kwargs = {"reasoning_content": reasoning} if reasoning else {}
    response_metadata: dict[str, Any] = {}
    generation_info: dict[str, Any] = {}
    if finish_reason is not None:
        generation_info["finish_reason"] = finish_reason
        response_metadata["finish_reason"] = finish_reason
    if body.get("model") is not None and (finish_reason is not None or usage_metadata is not None):
        response_metadata["model"] = body.get("model")
    if timings is not None:
        response_metadata["timings"] = timings
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content=content,
            additional_kwargs=additional_kwargs,
            response_metadata=response_metadata,
            tool_call_chunks=tool_call_chunks,
            usage_metadata=usage_metadata,
        ),
        generation_info=generation_info or None,
    )


def _tool_call_chunks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    chunks: list[dict[str, Any]] = []
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        arguments = function.get("arguments")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        elif arguments is not None and not isinstance(arguments, str):
            arguments = str(arguments)
        index = item.get("index")
        chunks.append(
            {
                "name": str(function["name"]) if function.get("name") is not None else None,
                "args": arguments,
                "id": str(item["id"]) if item.get("id") is not None else None,
                "index": index if isinstance(index, int) and not isinstance(index, bool) else position,
                "type": "tool_call_chunk",
            }
        )
    return chunks


def _stream_reasoning_content(delta: dict[str, Any]) -> str | None:
    for key in ("reasoning_content", "reasoning", "reasoning_details"):
        text = _reasoning_text(delta.get(key))
        if text is not None:
            return text
    return None


def _reasoning_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for key in ("reasoning_content", "text", "content", "summary"):
            if key in value:
                return _reasoning_text(value[key])
        return None
    if isinstance(value, list):
        parts = [_reasoning_text(item) for item in value]
        text = "".join(part for part in parts if part)
        return text or None
    return str(value)


def _usage_metadata(usage: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "input_tokens": _non_negative_int(usage.get("prompt_tokens")),
        "output_tokens": _non_negative_int(usage.get("completion_tokens")),
        "total_tokens": _non_negative_int(usage.get("total_tokens")),
    }
    prompt_token_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_token_details, dict):
        cached_tokens = _optional_non_negative_int(prompt_token_details.get("cached_tokens"))
        if cached_tokens is not None:
            metadata["input_token_details"] = {"cache_read": cached_tokens}
    return metadata


def _non_negative_int(value: Any) -> int:
    parsed = _optional_non_negative_int(value)
    return parsed if parsed is not None else 0


def _optional_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


def _sse_data(line: str) -> str | None:
    text = line.strip()
    if not text or text.startswith(":") or not text.startswith("data:"):
        return None
    return text[5:].strip()


def _stream_error_detail(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or error)
    return str(error)


def _choice(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("local llama.cpp response does not contain a valid choice")
    return choices[0]


def _tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"value": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _llama_cpp_tool_choice(value: str | dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        raise ValueError("llama.cpp does not support object-valued OpenAI tool_choice")
    normalized = str(value).strip().lower()
    if normalized == "any":
        return "required"
    if normalized in {"auto", "none", "required"}:
        return normalized
    raise ValueError(f"unsupported llama.cpp tool_choice: {value!r}")


def _structured_json_schema(schema: dict[str, Any] | type) -> dict[str, Any]:
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    if not isinstance(schema, dict):
        raise TypeError("structured output schema must be a Pydantic model or JSON schema")
    function = schema.get("function")
    if isinstance(function, dict) and isinstance(function.get("parameters"), dict):
        return dict(function["parameters"])
    return dict(schema)


def _raise_for_local_inference_error(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _local_inference_error_detail(response)
        if detail:
            raise RuntimeError(
                f"local llama.cpp request failed with HTTP {response.status_code}: {detail}"
            ) from exc
        raise


def _local_inference_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return response.text.strip()
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or "").strip()
    return str(payload.get("detail") or payload.get("message") or "").strip()


_XML_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_XML_FUNCTION_PATTERN = re.compile(r"<function=([^>]+)>(.*?)</function>", re.DOTALL)
_XML_PARAMETER_PATTERN = re.compile(r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>", re.DOTALL)


def _xml_tool_calls(content: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, match in enumerate(_XML_TOOL_CALL_PATTERN.finditer(content)):
        body = match.group(1).strip()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = _function_xml_payload(body)
        if not isinstance(payload, dict):
            continue
        name = str(payload.get("name") or "").strip()
        arguments = payload.get("arguments")
        if not name or not isinstance(arguments, dict):
            continue
        calls.append({"id": f"call_xml_{index}_{uuid4().hex}", "name": name, "args": arguments, "type": "tool_call"})
    return calls


def _function_xml_payload(body: str) -> dict[str, Any] | None:
    match = _XML_FUNCTION_PATTERN.search(body)
    if match is None:
        return None
    arguments: dict[str, Any] = {}
    for parameter in _XML_PARAMETER_PATTERN.finditer(match.group(2)):
        key = parameter.group(1).strip()
        raw_value = parameter.group(2).strip()
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        if key:
            arguments[key] = value
    return {"name": match.group(1).strip(), "arguments": arguments}


def _without_xml_tool_calls(content: str) -> str:
    return _XML_TOOL_CALL_PATTERN.sub("", content).strip()
