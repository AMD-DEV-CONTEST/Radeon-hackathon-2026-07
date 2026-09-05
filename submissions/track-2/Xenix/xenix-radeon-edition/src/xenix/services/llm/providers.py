from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib import error, request

from pydantic import field_validator
from sqlmodel import Field, SQLModel

from ...exceptions import ValidationError
from .messages import (
    AssistantOutputItem,
    CanonicalMessageBlock,
    ProviderOutputItem,
    ToolCallOutputItem,
    assistant_text_from_blocks,
    blocks_to_markdown,
    normalize_message_blocks,
    output_items_are_ordered,
)
from .tooling import (
    MAX_TOOL_CALLS,
    AgentToolSpec as _ToolDefinition,
    ensure_bounded_json,
)


def _dict_get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return default


class ProviderMessage(SQLModel):
    role: str
    # ``content`` remains a compatibility projection for scripted/custom
    # providers.  Wire adapters prefer the typed canonical blocks below and
    # derive their own provider text from them.
    content: str = ""
    content_blocks: list[CanonicalMessageBlock] = Field(default_factory=list)
    # Direct canonical value for a Tool Result.  Unlike ``content``, this is
    # not a provider wire encoding; each adapter chooses its own carrier.
    tool_result_value: Any = None
    provider_payload: dict[str, Any] = Field(default_factory=dict)
    source_message_id: str | None = None

    @field_validator("content_blocks", mode="before")
    @classmethod
    def _parse_content_blocks(cls, value: Any) -> list[CanonicalMessageBlock]:
        return list(normalize_message_blocks(value))

    @property
    def blocks(self) -> list[CanonicalMessageBlock]:
        """Alias exposing the canonical transcript shape without mutation."""

        return list(self.content_blocks)

    @property
    def canonical_blocks(self) -> tuple[CanonicalMessageBlock, ...]:
        return tuple(self.content_blocks)


class ProviderToolCall(SQLModel):
    provider_call_id: str
    tool_name: str
    provider_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    stream_index: int | None = None


class ProviderResponse(SQLModel):
    assistant_content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[ProviderToolCall] = Field(default_factory=list)
    usage_payload: dict[str, Any] | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    output_items: list[ProviderOutputItem] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        # Scripted providers and older callers may still construct the legacy
        # parallel fields.  Normalize that shape at the DTO boundary; wire
        # adapters always populate output_items directly.
        if self.output_items:
            if not output_items_are_ordered(self.output_items):
                raise ValidationError("Provider output items are not ordered.")
            return
        items: list[ProviderOutputItem] = []
        if self.assistant_content_blocks:
            blocks = normalize_message_blocks(self.assistant_content_blocks)
            text = assistant_text_from_blocks(blocks)
            if blocks or text:
                items.append(AssistantOutputItem(text=text, content_blocks=blocks))
        items.extend(
            ToolCallOutputItem(
                provider_call_id=call.provider_call_id,
                tool_name=call.tool_name,
                provider_name=call.provider_name or "",
                arguments=dict(call.arguments),
                stream_index=call.stream_index,
            )
            for call in self.tool_calls
        )
        if items:
            self.output_items = items


@dataclass(frozen=True)
class ProviderStreamEvent:
    delta_text: str = ""
    tool_call_delta: bool = False
    response: ProviderResponse | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_delta(self) -> bool:
        return bool(self.delta_text)

    @property
    def is_tool_call_delta(self) -> bool:
        return self.tool_call_delta

    @property
    def is_complete(self) -> bool:
        return self.response is not None


@dataclass(frozen=True)
class LLMRetryEvent:
    attempt_number: int
    max_attempts: int
    reason: str
    error_summary: str
    error_code: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
            "reason": self.reason,
            "error_summary": self.error_summary,
        }
        if self.error_code:
            payload["error_code"] = self.error_code
        return payload


@dataclass(frozen=True)
class LLMRequestMetadata:
    provider_name: str
    model: str


_PROVIDER_URL_PATTERN = re.compile(r"(?i)\b(?:https?|wss?)://[^\s'\"<>]+")
_PROVIDER_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|bearer(?:[_-]?token)?|password|secret|token)\b\s*(?:[:=]|\s)\s*)([^\s,;]+)"
)


def redact_provider_error_text(value: object, *, fallback: str = "LLM provider request failed.") -> str:
    """Return bounded diagnostics without a dynamic endpoint or credential.

    Provider failures can cross retry events into the Harness/UI.  Treat them as
    an external boundary even when the immediate adapter is a local loopback.
    """

    text = str(value).strip()
    if not text:
        return fallback
    text = _PROVIDER_URL_PATTERN.sub("<endpoint>", text)
    text = _PROVIDER_SECRET_PATTERN.sub(r"\1<redacted>", text)
    return text[:512]


class ProviderOperationError(ValidationError):
    """A provider failure carrying the operation's dispatch witness.

    Managed adapters set ``dispatch_may_have_happened`` when a binding loss can
    no longer prove that the server did not receive the request.  The outer LLM
    retry loop then fails the semantic operation instead of replaying it.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        retryable: bool | None = None,
        dispatch_may_have_happened: bool = False,
    ) -> None:
        self.dispatch_may_have_happened = bool(dispatch_may_have_happened)
        super().__init__(
            redact_provider_error_text(message),
            error_code=error_code,
            retryable=retryable,
        )


class ProviderBindingError(ProviderOperationError):
    """A manager-provided dynamic binding failed without leaking its details."""

    def __init__(
        self,
        message: str = "LLM provider binding failed.",
        *,
        error_code: str = "llm_provider_binding_error",
        retryable: bool = True,
        dispatch_may_have_happened: bool = False,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code,
            retryable=retryable,
            dispatch_may_have_happened=dispatch_may_have_happened,
        )


class AgentProvider(Protocol):
    def complete(
        self,
        messages: list[ProviderMessage],
        tools: list[_ToolDefinition],
    ) -> ProviderResponse:
        ...


class ScriptedAgentProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)

    def complete(
        self,
        messages: list[ProviderMessage],
        tools: list[_ToolDefinition],
    ) -> ProviderResponse:
        if not self._responses:
            raise ValidationError("Scripted provider has no responses left.")
        return self._responses.pop(0)


class OpenAICompatibleChatProvider:
    def __init__(
        self,
        *,
        provider_key: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 120,
        streaming_enabled: bool = True,
    ) -> None:
        self._provider_key = (provider_key or "openai").strip() or "openai"
        self._base_url = (base_url or "https://api.openai.com").rstrip("/")
        self._api_key = api_key or ""
        self._model = model or "gpt-4o-mini"
        self._timeout_seconds = timeout_seconds
        self._streaming_enabled = streaming_enabled

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(provider_key={self._provider_key!r}, "
            f"model={self._model!r}, timeout_seconds={self._timeout_seconds!r}, "
            f"streaming_enabled={self._streaming_enabled!r})"
        )

    @property
    def provider_key(self) -> str:
        return self._provider_key

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        messages: list[ProviderMessage],
        tools: list[_ToolDefinition],
    ) -> ProviderResponse:
        if not self._api_key:
            raise ValidationError("LLM API key is required for the OpenAI-compatible provider.")

        payload = self._build_payload(
            messages,
            tools,
            stream=False,
        )
        raw = self._post_json(payload)
        return self._parse_chat_completion(raw, tools)

    def stream(
        self,
        messages: list[ProviderMessage],
        tools: list[_ToolDefinition],
    ):
        if not self._streaming_enabled:
            yield ProviderStreamEvent(
                response=self.complete(messages, tools)
            )
            return
        if not self._api_key:
            raise ValidationError("LLM API key is required for the OpenAI-compatible provider.")

        payload = self._build_payload(
            messages,
            tools,
            stream=True,
        )
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        refusal_parts: list[str] = []
        raw_chunks: list[dict[str, Any]] = []
        tool_call_accumulator: dict[int, dict[str, Any]] = {}
        seen_choice = False
        usage_payload: dict[str, Any] | None = None
        for chunk in self._post_stream(payload):
            if not isinstance(chunk, dict):
                raise ValidationError("LLM provider stream chunk must be an object.")
            raw_chunks.append(chunk)
            chunk_usage = self._normalize_usage_payload(chunk.get("usage"))
            if chunk_usage is not None:
                usage_payload = chunk_usage
            choices = chunk.get("choices")
            if choices is None:
                choices = []
            if not isinstance(choices, list):
                raise ValidationError("LLM provider stream choices must be an array.")
            if not choices:
                # OpenAI's include_usage terminal chunk has no choices.  It is
                # valid only after at least one selected choice was observed.
                if not seen_choice:
                    continue
                continue
            if len(choices) != 1:
                raise ValidationError("LLM provider stream must contain exactly one choice.")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise ValidationError("LLM provider stream choice must be an object.")
            seen_choice = True
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                raise ValidationError("LLM provider stream delta must be an object.")
            content = self._optional_text(delta, "content")
            reasoning = self._optional_text(delta, "reasoning_content")
            refusal = self._optional_text(delta, "refusal")
            if content:
                text_parts.append(content)
                # The LLMService buffers this event while a request may retry.
                yield ProviderStreamEvent(delta_text=content, raw_payload=chunk)
            if reasoning:
                reasoning_parts.append(reasoning)
            if refusal:
                refusal_parts.append(refusal)
            tool_call_deltas = delta.get("tool_calls")
            if tool_call_deltas is None:
                tool_call_deltas = []
            if not isinstance(tool_call_deltas, list):
                raise ValidationError("LLM provider stream tool_calls must be an array.")
            if tool_call_deltas:
                self._accumulate_tool_call_deltas(tool_call_accumulator, tool_call_deltas)
                yield ProviderStreamEvent(tool_call_delta=True, raw_payload=chunk)

        text = "".join(text_parts)
        reasoning = "".join(reasoning_parts)
        refusal = "".join(refusal_parts)
        tool_calls = self._build_tool_calls(tool_call_accumulator, tools)
        raw_message: dict[str, Any] = {
            "content": text or None,
            "reasoning_content": reasoning or None,
            "refusal": refusal or None,
            "tool_calls": [
                {
                    "index": call.stream_index,
                    "id": call.provider_call_id,
                    "type": "function",
                    "function": {
                        "name": call.provider_name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in tool_calls
            ],
        }
        normalized = self._parse_chat_completion(
            {"choices": [{"message": raw_message}]},
            tools,
        )
        yield ProviderStreamEvent(
            response=normalized.model_copy(
                update={
                    "usage_payload": usage_payload,
                    "raw_payload": {"chunks": raw_chunks},
                }
            )
        )

    def _build_payload(
        self,
        messages: list[ProviderMessage],
        tools: list[_ToolDefinition],
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "messages": self._build_messages(messages),
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.provider_name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = f"{self._base_url}/v1/chat/completions"
        http_request = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                try:
                    return json.loads(response.read().decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise ProviderOperationError(
                        "LLM provider returned invalid JSON.",
                        error_code="llm_response_invalid_json",
                        retryable=True,
                        # A response body proves the server accepted and
                        # processed this semantic request.  Retrying could
                        # duplicate a Tool Call or user-visible completion.
                        dispatch_may_have_happened=True,
                    ) from exc
        except error.HTTPError as exc:
            raise self._http_error(endpoint, exc) from None
        except (error.URLError, TimeoutError, OSError):
            # ``urllib`` cannot prove that a transport failure occurred before
            # bytes crossed the socket boundary.  Preserve the conservative
            # possible-dispatch witness; manager adapters may still raise an
            # explicit pre-dispatch binding error when they can prove otherwise.
            raise ProviderOperationError(
                "LLM provider request could not be completed.",
                error_code="llm_provider_network_error",
                retryable=True,
                dispatch_may_have_happened=True,
            ) from None

    def _post_stream(self, payload: dict[str, Any]):
        endpoint = f"{self._base_url}/v1/chat/completions"
        http_request = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderOperationError(
                            "LLM provider stream returned invalid JSON.",
                            error_code="llm_stream_invalid_json",
                            retryable=True,
                            dispatch_may_have_happened=True,
                        ) from exc
        except error.HTTPError as exc:
            raise self._http_error(endpoint, exc) from None
        except (error.URLError, TimeoutError, OSError):
            raise ProviderOperationError(
                "LLM provider stream could not be completed.",
                error_code="llm_provider_network_error",
                retryable=True,
                dispatch_may_have_happened=True,
            ) from None

    def _http_error(self, endpoint: str, exc: error.HTTPError) -> ProviderOperationError:
        retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
        return ProviderOperationError(
            self._format_http_error(endpoint, exc),
            error_code=f"llm_provider_http_{exc.code}",
            retryable=retryable,
            dispatch_may_have_happened=True,
        )

    def _format_http_error(self, endpoint: str, exc: error.HTTPError) -> str:
        # Do not echo a server body here: it can contain an endpoint, a bearer
        # token, or provider-private request details that later surface through
        # a retry event.  The typed status code is sufficient for this boundary.
        del endpoint
        return f"LLM provider request failed with HTTP {exc.code}."

    def _extract_provider_error_message(self, body: str) -> str:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return redact_provider_error_text(body, fallback="")
        provider_error = payload.get("error")
        if isinstance(provider_error, dict):
            message = provider_error.get("message")
            code = provider_error.get("code")
            if message and code:
                return redact_provider_error_text(f"{message} ({code})", fallback="")
            if message:
                return redact_provider_error_text(message, fallback="")
        return redact_provider_error_text(body, fallback="")

    def _parse_chat_completion(self, raw: dict[str, Any], tools: list[_ToolDefinition]) -> ProviderResponse:
        if not isinstance(raw, dict):
            raise ValidationError("LLM provider response must be an object.")
        choices = raw.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValidationError("LLM provider response must contain exactly one choice.")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValidationError("LLM provider response choice/message shape is invalid.")
        message = choice["message"]
        content = self._optional_text(message, "content")
        reasoning = self._optional_text(message, "reasoning_content")
        refusal = self._optional_text(message, "refusal")
        tool_by_provider_name = {tool.provider_name: tool for tool in tools}
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls is None:
            raw_tool_calls = []
        if not isinstance(raw_tool_calls, list):
            raise ValidationError("LLM provider tool_calls must be an array.")
        if len(raw_tool_calls) > MAX_TOOL_CALLS:
            raise ValidationError(
                f"LLM provider returned more than {MAX_TOOL_CALLS} tool calls.",
                error_code="llm_tool_call_limit_exceeded",
            )
        seen_ids: set[str] = set()
        tool_calls: list[ProviderToolCall] = []
        output_items: list[ProviderOutputItem] = []
        if content or reasoning or refusal:
            output_items.append(
                AssistantOutputItem(text=content, reasoning=reasoning, refusal=refusal)
            )
        for call in raw_tool_calls:
            if not isinstance(call, dict):
                raise ValidationError("LLM provider tool call must be an object.")
            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id.strip():
                raise ValidationError("LLM provider tool call ID cannot be blank.")
            call_id = call_id.strip()
            if call_id in seen_ids:
                raise ValidationError(f"LLM provider tool call ID '{call_id}' is duplicated.")
            seen_ids.add(call_id)
            function = call.get("function")
            if not isinstance(function, dict):
                raise ValidationError("LLM provider tool call function must be an object.")
            provider_name = function.get("name")
            if not isinstance(provider_name, str) or not provider_name.strip():
                raise ValidationError("LLM provider tool name cannot be blank.")
            provider_name = provider_name.strip()
            spec = tool_by_provider_name.get(provider_name)
            if spec is None:
                raise ValidationError(
                    f"LLM provider requested an unexposed tool '{provider_name}'.",
                    error_code="llm_tool_not_exposed",
                )
            raw_arguments = function.get("arguments", "{}")
            arguments = self._parse_arguments(raw_arguments, spec.name)
            stream_index = call.get("index")
            if stream_index is not None and (
                isinstance(stream_index, bool)
                or not isinstance(stream_index, int)
                or stream_index < 0
            ):
                raise ValidationError("LLM provider tool call index is invalid.")
            tool_call = ProviderToolCall(
                provider_call_id=call_id,
                tool_name=spec.name,
                provider_name=provider_name,
                arguments=arguments,
                stream_index=stream_index,
            )
            tool_calls.append(tool_call)
            output_items.append(
                ToolCallOutputItem(
                    provider_call_id=call_id,
                    tool_name=spec.name,
                    provider_name=provider_name,
                    arguments=arguments,
                    stream_index=stream_index,
                )
            )
        if not output_items:
            raise ValidationError(
                "LLM provider returned an empty assistant output without tool calls.",
                error_code="llm_empty_output",
            )
        content_blocks = [{"type": "markdown", "text": content}] if content else []
        return ProviderResponse(
            assistant_content_blocks=content_blocks,
            tool_calls=tool_calls,
            usage_payload=self._normalize_usage_payload(raw.get("usage")),
            raw_payload=raw,
            output_items=output_items,
        )

    def _optional_text(self, value: dict[str, Any], key: str) -> str | None:
        raw = value.get(key)
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise ValidationError(f"LLM provider field '{key}' must be a string or null.")
        return raw

    def _parse_arguments(self, raw_arguments: Any, tool_name: str) -> dict[str, Any]:
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"Tool call '{tool_name}' arguments are not valid JSON.",
                    error_code="llm_tool_arguments_invalid_json",
                ) from exc
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            raise ValidationError(f"Tool call '{tool_name}' arguments must be a JSON object.")
        ensure_bounded_json(arguments, label=f"Tool call '{tool_name}' arguments")
        return dict(arguments)

    def _normalize_usage_payload(self, raw_usage: Any) -> dict[str, Any] | None:
        if not isinstance(raw_usage, dict):
            return None

        input_tokens = self._int_or_none(
            raw_usage.get("prompt_tokens", raw_usage.get("input_tokens"))
        )
        output_tokens = self._int_or_none(
            raw_usage.get("completion_tokens", raw_usage.get("output_tokens"))
        )
        total_tokens = self._int_or_none(raw_usage.get("total_tokens"))
        prompt_details = raw_usage.get("prompt_tokens_details")
        input_details = raw_usage.get("input_tokens_details")
        cached_input_tokens = self._int_or_none(
            _dict_get(prompt_details, "cached_tokens", _dict_get(input_details, "cached_tokens"))
        )

        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

        if all(value is None for value in (input_tokens, output_tokens, total_tokens, cached_input_tokens)):
            return {"provider_usage": dict(raw_usage)}

        return {
            "input_tokens": input_tokens or 0,
            "cached_input_tokens": cached_input_tokens or 0,
            "output_tokens": output_tokens or 0,
            "total_tokens": total_tokens or 0,
            "provider_usage": dict(raw_usage),
        }

    def _int_or_none(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return None

    def _accumulate_tool_call_deltas(
        self,
        accumulator: dict[int, dict[str, Any]],
        tool_call_deltas: list[dict[str, Any]],
    ) -> None:
        for delta in tool_call_deltas:
            if not isinstance(delta, dict):
                raise ValidationError("LLM provider stream tool call delta must be an object.")
            index = delta.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ValidationError("LLM provider stream tool call index is invalid.")
            current = accumulator.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if "id" in delta and delta["id"] is not None:
                call_id = delta["id"]
                if not isinstance(call_id, str):
                    raise ValidationError("LLM provider stream tool call ID must be a string.")
                call_id = call_id.strip()
                if call_id and current["id"] and current["id"] != call_id:
                    raise ValidationError("LLM provider stream tool call ID changed.")
                if call_id:
                    current["id"] = call_id
            function = delta.get("function")
            if function is None:
                function = {}
            if not isinstance(function, dict):
                raise ValidationError("LLM provider stream tool function must be an object.")
            if "name" in function and function["name"] is not None:
                name = function["name"]
                if not isinstance(name, str):
                    raise ValidationError("LLM provider stream tool name must be a string.")
                if name and current["name"] and current["name"] != name:
                    raise ValidationError("LLM provider stream tool name changed.")
                if name:
                    current["name"] = name
            if "arguments" in function and function["arguments"] is not None:
                arguments = function["arguments"]
                if not isinstance(arguments, str):
                    raise ValidationError("LLM provider stream tool arguments must be text.")
                current["arguments"] += arguments

    def _build_tool_calls(
        self,
        accumulator: dict[int, dict[str, Any]],
        tools: list[_ToolDefinition],
    ) -> list[ProviderToolCall]:
        indexes = sorted(accumulator)
        if len(indexes) > MAX_TOOL_CALLS:
            raise ValidationError(
                f"LLM provider returned more than {MAX_TOOL_CALLS} tool calls.",
                error_code="llm_tool_call_limit_exceeded",
            )
        if indexes and indexes != list(range(len(indexes))):
            raise ValidationError(
                "LLM provider stream tool call indexes must be contiguous from zero."
            )
        tool_by_provider_name = {tool.provider_name: tool for tool in tools}
        tool_calls: list[ProviderToolCall] = []
        seen_ids: set[str] = set()
        for index in indexes:
            current = accumulator[index]
            call_id = current["id"].strip()
            if not call_id:
                raise ValidationError("LLM provider stream tool call ID cannot be blank.")
            if call_id in seen_ids:
                raise ValidationError(f"LLM provider tool call ID '{call_id}' is duplicated.")
            seen_ids.add(call_id)
            spec = tool_by_provider_name.get(current["name"])
            if spec is None:
                raise ValidationError(
                    f"LLM provider requested an unexposed tool '{current['name']}'.",
                    error_code="llm_tool_not_exposed",
                )
            arguments = self._parse_arguments(current["arguments"] or "{}", spec.name)
            tool_calls.append(
                ProviderToolCall(
                    provider_call_id=call_id,
                    tool_name=spec.name,
                    provider_name=current["name"],
                    arguments=arguments,
                    stream_index=index,
                )
            )
        return tool_calls

    def _build_messages(self, rows: list[ProviderMessage]) -> list[dict[str, Any]]:
        provider_messages: list[dict[str, Any]] = []
        for row in rows:
            # Chat Completions accepts text content here.  Canonical blocks
            # are deliberately serialized at this adapter boundary so every
            # block (including UI-hidden Dataset blocks) reaches the provider.
            # Structured Tool Call/Result fields remain provider_payload and
            # are not flattened into this text fallback.
            if row.role == "tool":
                content = _tool_result_wire_content(row.tool_result_value)
            else:
                content = blocks_to_markdown(row.content_blocks) if row.content_blocks else row.content
            message = {"role": row.role, "content": content}
            if row.role == "assistant":
                reasoning_content = row.provider_payload.get("reasoning_content")
                if isinstance(reasoning_content, str):
                    message["reasoning_content"] = reasoning_content
                refusal = row.provider_payload.get("refusal")
                if isinstance(refusal, str):
                    message["refusal"] = refusal
                tool_calls = row.provider_payload.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    message["tool_calls"] = tool_calls
            if row.role == "tool":
                message["tool_call_id"] = row.provider_payload.get("tool_call_id", "")
            provider_messages.append(message)
        return _merge_leading_system_messages(provider_messages)


def _merge_leading_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project leading context as one broadly compatible system message.

    Chat Completions permits multiple system rows, but several otherwise
    compatible model chat templates require exactly one system row at index
    zero.  Canonical context providers remain independently owned; this wire
    projection preserves their order and visible boundary without rewriting a
    later system message that would indicate a real transcript-shape error.
    """

    leading_count = 0
    for message in messages:
        if message.get("role") != "system":
            break
        leading_count += 1
    if leading_count <= 1:
        return messages
    content = "\n\n".join(str(message.get("content") or "") for message in messages[:leading_count])
    return [{"role": "system", "content": content}, *messages[leading_count:]]


def _tool_result_wire_content(value: Any) -> str:
    """Encode one direct canonical ToolResult for this OpenAI-compatible wire."""

    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def extract_reasoning_content(raw_payload: dict[str, Any]) -> str | None:
    choices = raw_payload.get("choices")
    if isinstance(choices, list):
        parts = [
            str(reasoning_content)
            for choice in choices
            if isinstance(choice, dict)
            for message in [choice.get("message")]
            if isinstance(message, dict)
            for reasoning_content in [message.get("reasoning_content")]
            if isinstance(reasoning_content, str)
        ]
        if parts:
            return "".join(parts)

    chunks = raw_payload.get("chunks")
    if not isinstance(chunks, list):
        return None

    parts = [
        str(reasoning_content)
        for chunk in chunks
        if isinstance(chunk, dict)
        for choice in chunk.get("choices") or []
        if isinstance(choice, dict)
        for delta in [choice.get("delta")]
        if isinstance(delta, dict)
        for reasoning_content in [delta.get("reasoning_content")]
        if isinstance(reasoning_content, str)
    ]
    if parts:
        return "".join(parts)
    return None
