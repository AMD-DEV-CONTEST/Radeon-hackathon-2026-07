from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from agent_factory.models.content import content_to_text, strip_internal_snapshot_blocks
from agent_factory.models.message_layout import system_messages_first
from agent_factory.runtime_kernel.adapters.model import (
    ModelRole,
    _bind_tools,
    _configured_model_for_role,
    _tool_calls_from_response,
)
from agent_factory.runtime_kernel.model_inputs import build_runtime_model_input
from agent_factory.runtime_kernel.types import ModelInvocationResult
from agent_factory.models.reasoning import reasoning_content_from_message
from agent_factory.model_pool.runtime_override import (
    resolve_runtime_main_chat_model_from_state,
    resolve_runtime_reasoning_model,
)
from agent_factory.model_pool.schema import ModelBindingRuntimeOverrides
from agent_factory.context_system.events import emit_context_event
from agent_factory.context_system.token_counter import (
    context_window_payload,
    model_context_limits,
    provider_token_budget_payload,
    token_count_from_usage_metadata,
)
from agent_factory.models.usage import normalize_usage_metadata
from agent_factory.tooling.description_context import contextualize_tool_descriptions

_DEFAULT_STRUCTURED_METHOD = "json_mode"


class ModelOperationService:
    """Kernel-level model operations used by generated Agent runtimes.

    The service is intentionally limited to model invocation shapes. It does
    not decide graph routes, plan tools, approve tools, or execute tools.
    """

    def __init__(
        self,
        *,
        role: ModelRole = "main",
        model: Any | None = None,
        settings: Any | None = None,
        models_by_role: Mapping[str, tuple[Any, Any]] | None = None,
        require_runtime_profile: bool = False,
        runtime_profile_overrides: ModelBindingRuntimeOverrides | None = None,
    ) -> None:
        self.model_role = role
        self._model = model
        self._settings = settings
        self._models_by_role = dict(models_by_role or {})
        self._require_runtime_profile = require_runtime_profile
        self._runtime_profile_overrides = runtime_profile_overrides or ModelBindingRuntimeOverrides()

    def text(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        emit_event=None,
        model_role: ModelRole | None = None,
    ) -> ModelInvocationResult:
        return self.tool_bound_chat(
            state=state,
            prompt_binding=prompt_binding,
            messages=messages,
            tools=[],
            emit_event=emit_event,
            model_role=model_role,
        )

    def tool_bound_chat(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
        emit_event=None,
        services: Any | None = None,
        node_id: str | None = None,
        model_role: ModelRole | None = None,
    ) -> ModelInvocationResult:
        model, metadata = self._resolve_model(model_role, state=state)
        effective_model_role = str(metadata.get("model_role") or model_role or self.model_role)
        tool_list = contextualize_tool_descriptions(tools or [])
        envelope = build_runtime_model_input(
            state=state,
            prompt_binding=prompt_binding or {},
            messages=messages or [],
            tools=tool_list,
            node_id=node_id,
            image_input_enabled=bool(metadata.get("multimodal")),
        )
        trace_span_id = _start_trace_span(
            state=state,
            services=services,
            node_id=node_id,
            operation="tool_bound_chat",
            payload={"model_role": effective_model_role, **envelope.diagnostics()},
        )
        stream_id = uuid4().hex
        _emit(
            emit_event,
            "model_call_started",
            {"operation": "tool_bound_chat", "model_role": effective_model_role, "stream_id": stream_id},
        )
        try:
            response = _invoke_tool_bound_chat(
                model=_bind_tools(model, tool_list),
                messages=envelope.messages,
                emit_event=emit_event,
                stream_id=stream_id,
            )
        except Exception as exc:
            _emit(emit_event, "model_call_failed", {"operation": "tool_bound_chat", "error": str(exc)})
            _finish_trace_span(
                state=state,
                services=services,
                node_id=node_id,
                span_id=trace_span_id,
                operation="tool_bound_chat",
                status="failed",
                payload={"error": str(exc)},
            )
            raise
        text = strip_internal_snapshot_blocks(content_to_text(getattr(response, "content", response))).strip()
        reasoning_content = reasoning_content_from_message(response)
        tool_calls = _tool_calls_from_response(response)
        usage_metadata = getattr(response, "usage_metadata", None) or {}
        _record_provider_token_budget(
            state=state,
            node_id=node_id,
            model_role=effective_model_role,
            usage_metadata=usage_metadata,
        )
        cache_metrics = _model_cache_metrics_payload(
            state=state,
            node_id=node_id,
            model_metadata=metadata,
            usage_metadata=usage_metadata,
            input_diagnostics=envelope.diagnostics(),
        )
        _emit(
            emit_event,
            "model_call_completed",
            {
                "operation": "tool_bound_chat",
                "tool_call_count": len(tool_calls),
                "usage_metadata": usage_metadata,
                "model_input": envelope.diagnostics(),
            },
        )
        _emit(emit_event, "model_cache_metrics", cache_metrics)
        _emit_provider_usage_context_window(
            state=state,
            services=services,
            node_id=node_id,
            response=response,
            model_role=effective_model_role,
        )
        _finish_trace_span(
            state=state,
            services=services,
            node_id=node_id,
            span_id=trace_span_id,
            operation="tool_bound_chat",
            status="completed",
            payload={
                "tool_call_count": len(tool_calls),
                "usage_metadata": usage_metadata,
                "model_input": envelope.diagnostics(),
                "model_cache": cache_metrics,
            },
        )
        return ModelInvocationResult(
            ai_message=response if isinstance(response, BaseMessage) else None,
            assistant_draft=text,
            final_answer=None if tool_calls else text,
            tool_calls=tool_calls,
            metadata={
                **metadata,
                "tool_count": len(tool_list),
                "usage_metadata": usage_metadata,
                "provider_input_tokens": token_count_from_usage_metadata(usage_metadata),
                "reasoning_content": reasoning_content,
                **envelope.diagnostics(),
            },
        )

    def structured_json(
        self,
        *,
        output_model: type[BaseModel],
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        prebuilt_messages: list[Any] | None = None,
        structured_method: str | None = None,
        config_tags: list[str] | None = None,
        max_attempts: int = 3,
        emit_event=None,
        operation_metadata: dict[str, Any] | None = None,
        services: Any | None = None,
        node_id: str | None = None,
        model_role: ModelRole | None = None,
    ) -> BaseModel:
        model, metadata = self._resolve_model(model_role, state=state)
        effective_model_role = str(metadata.get("model_role") or model_role or self.model_role)
        envelope = None
        if prebuilt_messages is not None:
            request_messages = list(prebuilt_messages)
        else:
            envelope = build_runtime_model_input(
                state=state,
                prompt_binding=prompt_binding or {},
                messages=messages or [],
                tools=[],
                node_id=node_id,
                image_input_enabled=bool(metadata.get("multimodal")),
            )
            request_messages = envelope.messages
        attempts = max(1, int(max_attempts))
        last_error: Exception | None = None
        effective_structured_method = _effective_structured_method(
            requested=structured_method,
            model_metadata=metadata,
        )
        operation_context = {
            **metadata,
            "structured_output_method": effective_structured_method,
            **(operation_metadata or {}),
        }
        schema_payload = _schema_payload(output_model)
        request_messages = _structured_request_messages(
            messages=request_messages,
            output_model=output_model,
            output_json_schema=schema_payload,
            structured_method=effective_structured_method,
        )
        request_messages = system_messages_first(request_messages)
        input_diagnostics = _structured_input_diagnostics(
            envelope=envelope,
            request_messages=request_messages,
            tool_count=0,
        )
        trace_span_id = _start_trace_span(
            state=state,
            services=services,
            node_id=node_id,
            operation="structured_json",
            payload={"schema_name": output_model.__name__, **operation_context, "model_input": input_diagnostics},
        )
        for attempt in range(1, attempts + 1):
            _emit(
                emit_event,
                "model_call_started",
                {"operation": "structured_json", "attempt": attempt, "max_attempts": attempts, **operation_context},
            )
            try:
                structured_model = _structured_model(
                    model=model,
                    output_model=output_model,
                    method=effective_structured_method,
                    config_tags=_structured_config_tags(config_tags),
                )
                result = structured_model.invoke(request_messages)
                if isinstance(result, output_model):
                    parsed = result
                else:
                    parsed = output_model.model_validate(result)
                usage_metadata = getattr(result, "usage_metadata", None) or {}
                _record_provider_token_budget(
                    state=state,
                    node_id=node_id,
                    model_role=effective_model_role,
                    usage_metadata=usage_metadata,
                )
                cache_metrics = _model_cache_metrics_payload(
                    state=state,
                    node_id=node_id,
                    model_metadata=metadata,
                    usage_metadata=usage_metadata,
                    input_diagnostics=input_diagnostics,
                )
                _emit(
                    emit_event,
                    "model_call_completed",
                    {
                        "operation": "structured_json",
                        "attempt": attempt,
                        "usage_metadata": usage_metadata,
                        "model_input": input_diagnostics,
                    },
                )
                _emit(emit_event, "model_cache_metrics", cache_metrics)
                _emit_provider_usage_context_window(
                    state=state,
                    services=services,
                    node_id=node_id,
                    response=result,
                    model_role=effective_model_role,
                )
                _finish_trace_span(
                    state=state,
                    services=services,
                    node_id=node_id,
                    span_id=trace_span_id,
                    operation="structured_json",
                    status="completed",
                    payload={
                        "attempt": attempt,
                        "schema_name": output_model.__name__,
                        "usage_metadata": usage_metadata,
                        "model_input": input_diagnostics,
                        "model_cache": cache_metrics,
                    },
                )
                return parsed
            except Exception as exc:
                last_error = exc
                _emit(
                    emit_event,
                    "model_call_failed",
                    {
                        "operation": "structured_json",
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "error": str(exc),
                        **operation_context,
                    },
                )
                if attempt < attempts:
                    request_messages = [
                        *request_messages,
                        HumanMessage(
                            content=_structured_retry_instruction(
                                output_model=output_model,
                                error=exc,
                                attempt=attempt,
                                max_attempts=attempts,
                                output_json_schema=schema_payload,
                            )
                        ),
                    ]
                    input_diagnostics = _structured_input_diagnostics(
                        envelope=envelope,
                        request_messages=request_messages,
                        tool_count=0,
                    )
        _finish_trace_span(
            state=state,
            services=services,
            node_id=node_id,
            span_id=trace_span_id,
            operation="structured_json",
            status="failed",
            payload={"error": str(last_error), "schema_name": output_model.__name__},
        )
        raise RuntimeError(f"structured model operation failed after {attempts} attempts: {last_error}")

    def _resolve_model(self, role: ModelRole | None = None, *, state: Any | None = None) -> tuple[Any, dict[str, Any]]:
        requested_role = role or self.model_role
        if state is not None and (requested_role == "main" or self._require_runtime_profile):
            override = resolve_runtime_main_chat_model_from_state(
                state,
                overrides=self._runtime_profile_overrides,
            )
            if override is not None:
                return self._apply_runtime_reasoning(
                    override.model,
                    override.settings,
                    state,
                    {
                        "runtime_model_override": True,
                        "runtime_model_override_role": requested_role,
                    },
                    model_role="main",
                    requested_model_role=requested_role,
                )
        if self._require_runtime_profile:
            raise RuntimeError("runtime main model profile is not selected")
        if self._models_by_role:
            item = self._models_by_role.get(requested_role)
            resolved_role = requested_role
            if item is None:
                item = self._fallback_model_item_for_role(requested_role, state=state)
                resolved_role = "main"
            if item is None:
                raise RuntimeError(f"{requested_role} model is not configured for AgentPackage runtime")
            model, settings = item
            return self._apply_runtime_reasoning(
                model,
                settings,
                state,
                {
                    "model": "injected",
                },
                model_role=resolved_role,
                requested_model_role=requested_role,
            )
        if self._model is not None:
            if role is not None and role != self.model_role:
                model, settings = _configured_model_for_role(role)
                if model is None:
                    raise RuntimeError(f"{role} model is not configured for AgentPackage runtime")
                resolved_role = self._model_role_from_settings(settings, default=role)
                return self._apply_runtime_reasoning(
                    model,
                    settings,
                    state,
                    {},
                    model_role=resolved_role,
                    requested_model_role=role,
                )
            return self._apply_runtime_reasoning(
                self._model,
                self._settings,
                state,
                {"model": "injected"},
                model_role=self.model_role,
                requested_model_role=requested_role,
            )
        model, settings = _configured_model_for_role(requested_role)
        if model is None:
            raise RuntimeError(f"{requested_role} model is not configured for AgentPackage runtime")
        resolved_role = self._model_role_from_settings(settings, default=requested_role)
        return self._apply_runtime_reasoning(
            model,
            settings,
            state,
            {},
            model_role=resolved_role,
            requested_model_role=requested_role,
        )

    @staticmethod
    def _apply_runtime_reasoning(
        model: Any,
        settings: Any,
        state: Any | None,
        metadata: dict[str, Any],
        *,
        model_role: ModelRole,
        requested_model_role: ModelRole | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        if state is not None:
            if settings is None:
                _, settings = _configured_model_for_role(model_role)
            if settings is None:
                raise RuntimeError(f"{model_role} model settings are not configured")
            model, settings = resolve_runtime_reasoning_model(model, settings, state)
        requested_role = requested_model_role or model_role
        result = {
            **metadata,
            **(settings.metadata() if hasattr(settings, "metadata") else {}),
            "model_role": model_role,
            "requested_model_role": requested_role,
        }
        if requested_role != model_role:
            result["model_role_fallback"] = model_role
        return model, result

    @staticmethod
    def _model_role_from_settings(settings: Any, *, default: ModelRole) -> ModelRole:
        configured_role = getattr(settings, "role", None)
        if configured_role in {"main", "task", "compression"}:
            return configured_role
        return default

    def _fallback_model_item_for_role(self, role: ModelRole, *, state: Any | None = None) -> tuple[Any, Any] | None:
        if role != "task":
            return None
        item = self._models_by_role.get("main")
        if item is not None:
            return item
        if state is not None:
            override = resolve_runtime_main_chat_model_from_state(
                state,
                overrides=self._runtime_profile_overrides,
            )
            if override is not None:
                return override.model, override.settings
        model, settings = _configured_model_for_role("main")
        if model is None:
            return None
        return model, settings

    def model_for_role(self, role: str | None = None) -> Any | None:
        requested_role = role if role in {"main", "task", "compression"} else self.model_role
        try:
            model, _metadata = self._resolve_model(requested_role)  # type: ignore[arg-type]
        except RuntimeError:
            return None
        return model

    def context_limits_for_role(
        self,
        role: str | None = None,
        *,
        state: Any | None = None,
    ) -> dict[str, int | None]:
        requested_role = role if role in {"main", "task", "compression"} else self.model_role
        _model, metadata = self._resolve_model(requested_role, state=state)  # type: ignore[arg-type]
        return {
            "max_input_tokens": metadata.get("max_input_tokens"),
            "compression_trigger_tokens": metadata.get("compression_trigger_tokens"),
        }


def _emit(emit_event, event_type: str, payload: dict[str, Any]) -> None:
    if emit_event is None:
        return
    emit_event({"event_type": event_type, **payload})


def _record_provider_token_budget(
    *,
    state: Any,
    node_id: str | None,
    model_role: str,
    usage_metadata: Any,
) -> None:
    if state is None or node_id is None:
        return
    context = getattr(state, "context", None)
    if context is None or not hasattr(context, "token_budget"):
        return
    payload = provider_token_budget_payload(
        usage_metadata=usage_metadata,
        node_id=node_id,
        model_role=model_role,
    )
    if not payload:
        return
    context.token_budget = {
        **dict(getattr(context, "token_budget", {}) or {}),
        **payload,
    }


def _invoke_tool_bound_chat(
    *,
    model: Any,
    messages: list[Any],
    emit_event,
    stream_id: str,
) -> Any:
    messages = system_messages_first(messages)
    stream = getattr(model, "stream", None)
    if not callable(stream):
        response = model.invoke(messages)
        _emit_model_message_completed(emit_event, stream_id=stream_id, response=response)
        return response
    chunks: list[Any] = []
    reasoning_parts: list[str] = []
    try:
        for chunk in stream(messages):
            chunks.append(chunk)
            reasoning_delta = reasoning_content_from_message(chunk)
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                _emit(
                    emit_event,
                    "model_reasoning_delta",
                    {
                        "stream_id": stream_id,
                        "delta": reasoning_delta,
                        "content_mode": "delta",
                    },
                )
            delta = strip_internal_snapshot_blocks(content_to_text(getattr(chunk, "content", chunk)))
            if delta:
                _emit(
                    emit_event,
                    "model_stream_delta",
                    {
                        "stream_id": stream_id,
                        "delta": delta,
                        "content_mode": "delta",
                    },
                )
    except (AttributeError, NotImplementedError):
        if chunks:
            raise
        response = model.invoke(messages)
        _emit_model_message_completed(emit_event, stream_id=stream_id, response=response)
        return response
    if not chunks:
        response = model.invoke(messages)
        _emit_model_message_completed(emit_event, stream_id=stream_id, response=response)
        return response
    response = _merge_stream_chunks(chunks)
    if reasoning_parts and not reasoning_content_from_message(response):
        _attach_reasoning_content(response, "".join(reasoning_parts))
    _emit_model_message_completed(emit_event, stream_id=stream_id, response=response)
    return response


def _merge_stream_chunks(chunks: list[Any]) -> Any:
    merged = chunks[0]
    for chunk in chunks[1:]:
        try:
            merged = merged + chunk
        except TypeError:
            merged = chunk
    return merged


def _attach_reasoning_content(response: Any, reasoning_content: str) -> None:
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        additional_kwargs["reasoning_content"] = reasoning_content
        return
    try:
        response.additional_kwargs = {"reasoning_content": reasoning_content}
    except Exception:
        return


def _emit_model_message_completed(emit_event, *, stream_id: str, response: Any) -> None:
    content = strip_internal_snapshot_blocks(content_to_text(getattr(response, "content", response))).strip()
    reasoning_content = reasoning_content_from_message(response)
    if reasoning_content:
        _emit(
            emit_event,
            "model_reasoning_completed",
            {
                "stream_id": stream_id,
                "content": reasoning_content,
                "content_mode": "snapshot",
                "completion_reason": "model_completed",
            },
        )
    _emit(
        emit_event,
        "model_message_completed",
        {
            "stream_id": stream_id,
            "content": content,
            "content_mode": "snapshot",
            "completion_reason": "model_completed",
            **({"reasoning_content": reasoning_content} if reasoning_content else {}),
        },
    )


def _model_cache_metrics_payload(
    *,
    state: Any,
    node_id: str | None,
    model_metadata: dict[str, Any],
    usage_metadata: dict[str, Any],
    input_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    normalized_usage = normalize_usage_metadata(usage_metadata)
    input_tokens = normalized_usage.input_tokens
    output_tokens = normalized_usage.output_tokens
    cached_input_tokens = normalized_usage.cache_hit_tokens
    hit_ratio = None
    if input_tokens and cached_input_tokens is not None:
        hit_ratio = round(float(cached_input_tokens) / float(input_tokens), 6)
    return {
        "version": "runtime_model_cache_metrics.v0",
        "node_id": node_id,
        "agent_id": str(getattr(getattr(state, "run", None), "agent_id", "") or ""),
        "session_id": str(getattr(getattr(state, "run", None), "session_id", "") or ""),
        "run_id": str(getattr(getattr(state, "run", None), "run_id", "") or ""),
        "pattern_id": str(getattr(getattr(state, "run", None), "pattern_id", "") or ""),
        "model_role": model_metadata.get("model_role"),
        "model": model_metadata.get("model"),
        "provider": model_metadata.get("provider"),
        "provider_display_name": model_metadata.get("provider_display_name"),
        "model_profile_id": model_metadata.get("model_profile_id"),
        "model_source": model_metadata.get("model_source"),
        "provider_cache": {
            "available": cached_input_tokens is not None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_miss_tokens": normalized_usage.cache_miss_tokens,
            "reasoning_tokens": normalized_usage.reasoning_tokens,
            "total_tokens": normalized_usage.total_tokens,
            "hit_ratio": hit_ratio,
            "source": "normalized_provider_usage" if cached_input_tokens is not None else None,
        },
        "model_input": input_diagnostics,
    }


def _start_trace_span(
    *,
    state: Any,
    services: Any | None,
    node_id: str | None,
    operation: str,
    payload: dict[str, Any],
) -> str | None:
    recorder = getattr(services, "trace_recorder", None) if services is not None else None
    if recorder is None or state is None:
        return None
    return recorder.start_span(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        span_kind="model.call",
        name=operation,
        node_id=node_id,
        payload=payload,
    )


def _finish_trace_span(
    *,
    state: Any,
    services: Any | None,
    node_id: str | None,
    span_id: str | None,
    operation: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    recorder = getattr(services, "trace_recorder", None) if services is not None else None
    if recorder is None or state is None or span_id is None:
        return
    recorder.finish_span(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        span_id=span_id,
        span_kind="model.call",
        name=operation,
        status=status,
        node_id=node_id,
        payload=payload,
    )


def _structured_input_diagnostics(
    *,
    envelope: Any | None,
    request_messages: list[Any],
    tool_count: int,
) -> dict[str, Any]:
    if envelope is not None:
        diagnostics = dict(envelope.diagnostics())
    else:
        diagnostics = {
            "stable_prefix_digest": "",
            "knowledge_guidance_digest": "",
            "dynamic_evidence_digest": "",
            "tool_surface_digest": "",
            "stable_system_chars": 0,
            "knowledge_guidance_chars": 0,
            "dynamic_evidence_chars": 0,
            "history_message_count": _base_message_count(request_messages),
            "tool_count": tool_count,
        }
    diagnostics["request_message_count"] = _base_message_count(request_messages)
    diagnostics["request_message_chars"] = _request_message_chars(request_messages)
    return diagnostics


def _base_message_count(messages: list[Any]) -> int:
    return sum(1 for message in messages if isinstance(message, BaseMessage))


def _request_message_chars(messages: list[Any]) -> int:
    return sum(len(_message_content_text(message)) for message in messages)


def _message_content_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)


def _structured_model(
    *,
    model: Any,
    output_model: type[BaseModel],
    method: str | None,
    config_tags: list[str] | None,
) -> Any:
    structured = (
        model.with_structured_output(output_model, method=method)
        if method
        else model.with_structured_output(output_model)
    )
    if config_tags and hasattr(structured, "with_config"):
        structured = structured.with_config(tags=list(config_tags))
    return structured


def _structured_config_tags(config_tags: list[str] | None) -> list[str]:
    tags = ["nostream"]
    for tag in config_tags or []:
        item = str(tag).strip()
        if item and item not in tags:
            tags.append(item)
    return tags


def _effective_structured_method(*, requested: str | None, model_metadata: dict[str, Any]) -> str:
    method = str(requested or model_metadata.get("structured_output_method") or "").strip()
    if not method:
        method = str(
            model_metadata.get("default_structured_output_method")
            or _DEFAULT_STRUCTURED_METHOD
        ).strip()
    supported = {
        str(item)
        for item in (model_metadata.get("structured_output_methods") or [])
        if str(item).strip()
    }
    if supported and method not in supported:
        provider = str(model_metadata.get("provider") or "model")
        supported_text = ", ".join(sorted(supported))
        raise RuntimeError(
            f"structured output method {method!r} is not supported by {provider}; "
            f"supported methods: {supported_text}"
        )
    return method or _DEFAULT_STRUCTURED_METHOD


def _structured_request_messages(
    *,
    messages: list[Any],
    output_model: type[BaseModel],
    output_json_schema: str,
    structured_method: str,
) -> list[Any]:
    if structured_method != "json_mode":
        return messages
    return [
        *messages,
        HumanMessage(
            content=_structured_json_mode_instruction(
                output_model=output_model,
                output_json_schema=output_json_schema,
            )
        ),
    ]


def _schema_payload(output_model: type[BaseModel]) -> str:
    try:
        return json.dumps(output_model.model_json_schema(), ensure_ascii=False, sort_keys=True)
    except Exception:
        return output_model.__name__


def _structured_json_mode_instruction(
    *,
    output_model: type[BaseModel],
    output_json_schema: str,
) -> str:
    return (
        "Return JSON only. Do not include markdown fences, comments, or explanatory text.\n"
        "The JSON response must validate against the schema below.\n"
        f"Schema name: {output_model.__name__}\n"
        f"Output JSON schema:\n{output_json_schema}"
    )


def _structured_retry_instruction(
    *,
    output_model: type[BaseModel],
    error: Exception,
    attempt: int,
    max_attempts: int,
    output_json_schema: Any,
) -> str:
    return (
        "The previous structured JSON output failed schema validation.\n"
        "Regenerate the full response as JSON only. Do not explain the error.\n"
        "You must obey every JSON schema constraint, including required fields, enum values, "
        "minItems, maxItems, field types, numeric ranges, and extra=forbid.\n"
        f"Schema name: {output_model.__name__}\n"
        f"Validation observation from attempt {attempt}/{max_attempts}:\n{type(error).__name__}: {error}\n\n"
        f"Output JSON schema:\n{output_json_schema}"
    )


def _emit_provider_usage_context_window(
    *,
    state: Any,
    services: Any | None,
    node_id: str | None,
    response: Any,
    model_role: str,
) -> None:
    if services is None or node_id is None:
        return
    token_count = token_count_from_usage_metadata(getattr(response, "usage_metadata", None))
    if token_count is None:
        return
    limits = model_context_limits(services=services, state=state, model_role=model_role)
    context_runtime = getattr(services, "context_system", None)
    resolve_context_limits = getattr(context_runtime, "model_context_limits", None)
    if callable(resolve_context_limits):
        limits = resolve_context_limits(
            services=services,
            state=state,
            model_role=model_role,
        )
    emit_context_event(
        services=services,
        state=state,
        event_type="context_window_updated",
        node_id=node_id,
        payload=context_window_payload(
            node_id=node_id,
            token_count=token_count,
            token_count_method="provider_usage",
            compression_threshold_tokens=limits.compression_trigger_tokens,
            context_window_tokens=limits.context_window_tokens,
            model_role=model_role,
            source="model_operation.provider_usage",
        ),
    )
