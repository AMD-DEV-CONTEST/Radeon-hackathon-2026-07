from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal, Protocol

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from agent_factory.models import ChatModelSettings
from agent_factory.models.content import content_to_text, strip_internal_snapshot_blocks
from agent_factory.models.reasoning import reasoning_content_from_message
from agent_factory.model_pool.runtime_override import (
    resolve_runtime_main_chat_model_from_state,
    resolve_runtime_reasoning_model,
)
from agent_factory.model_pool.schema import ModelBindingRuntimeOverrides
from agent_factory.local_inference.request_context import inference_request_context
from agent_factory.runtime_kernel.model_inputs import build_runtime_model_input
from agent_factory.runtime_kernel.types import ModelInvocationResult
from agent_factory.tooling.description_context import contextualize_tool_descriptions


ModelRole = Literal["main", "task", "compression"]


class ModelServiceAdapter(Protocol):
    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
    ) -> ModelInvocationResult:
        ...


class ScriptedModelService:
    def __init__(self, responses: Sequence[ModelInvocationResult] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
    ) -> ModelInvocationResult:
        self.calls.append({"state": state, "prompt_binding": prompt_binding or {}})
        if self._responses:
            return self._responses.pop(0)
        current_input = getattr(getattr(state, "conversation", None), "current_user_input", None)
        text = str(current_input or "")
        prompt_id = str((prompt_binding or {}).get("prompt_id") or "")
        if "clarify" in prompt_id and len(text.strip()) < 12:
            return ModelInvocationResult(
                assistant_draft="我需要更多信息来继续。",
                clarification_question="请补充你的目标或使用场景。",
            )
        return ModelInvocationResult(
            assistant_draft=f"Echo: {text}",
            final_answer=f"Echo: {text}",
        )


class LangChainModelServiceAdapter:
    """RuntimeKernel model adapter backed by a configured Factory model role.

    This adapter deliberately performs only model invocation. It does not plan
    tools, choose routes, approve actions, or synthesize graph control.
    """

    def __init__(
        self,
        *,
        role: ModelRole = "main",
        model: Any | None = None,
        settings: ChatModelSettings | None = None,
        require_runtime_profile: bool = False,
        runtime_profile_overrides: ModelBindingRuntimeOverrides | None = None,
    ) -> None:
        self.model_role = role
        self._model = model
        self._settings = settings
        self._require_runtime_profile = require_runtime_profile
        self._runtime_profile_overrides = runtime_profile_overrides or ModelBindingRuntimeOverrides()

    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
    ) -> ModelInvocationResult:
        model, settings = self._resolve_model(state=state)
        model, settings = resolve_runtime_reasoning_model(model, settings, state)
        if model is None:
            raise RuntimeError(f"{self.model_role} model is not configured for AgentPackage runtime")
        contextual_tools = contextualize_tool_descriptions(tools or [])
        bound_model = _bind_tools(model, contextual_tools)
        envelope = build_runtime_model_input(
            state=state,
            prompt_binding=prompt_binding or {},
            messages=messages or [],
            tools=contextual_tools,
            image_input_enabled=bool(settings.multimodal),
        )
        with inference_request_context(session_id=state.run.session_id):
            response = bound_model.invoke(envelope.messages)
        text = strip_internal_snapshot_blocks(content_to_text(getattr(response, "content", response))).strip()
        tool_calls = _tool_calls_from_response(response)
        reasoning_content = reasoning_content_from_message(response)
        return ModelInvocationResult(
            ai_message=response if isinstance(response, BaseMessage) else None,
            assistant_draft=text,
            final_answer=None if tool_calls else text,
            tool_calls=tool_calls,
            metadata={
                **settings.metadata(),
                "tool_count": len(contextual_tools),
                **envelope.diagnostics(),
                **({"reasoning_content": reasoning_content} if reasoning_content else {}),
            },
        )

    def _resolve_model(self, *, state: Any | None = None) -> tuple[Any, ChatModelSettings]:
        if self.model_role == "main" and state is not None:
            override = resolve_runtime_main_chat_model_from_state(
                state,
                overrides=self._runtime_profile_overrides,
            )
            if override is not None:
                return override.model, override.settings
        if self._require_runtime_profile:
            raise RuntimeError("runtime main model profile is not selected")
        if self._model is not None and self._settings is not None:
            return self._model, self._settings
        return _configured_model_for_role(self.model_role)


def _configured_model_for_role(role: ModelRole) -> tuple[Any, ChatModelSettings]:
    from agent_factory.model_pool.resolver import resolve_available_chat_model

    resolved = resolve_available_chat_model(role)
    if resolved is None and role == "task":
        resolved = resolve_available_chat_model("main")
    if resolved is None:
        raise RuntimeError(f"{role} model is not configured in the model pool")
    return resolved.model, resolved.settings


def _bind_tools(model: Any, tools: list[BaseTool]) -> Any:
    if not tools:
        return model
    return model.bind_tools(tools, tool_choice="auto")


def _tool_calls_from_response(response: Any) -> list[dict[str, Any]]:
    calls = _response_tool_call_candidates(response)
    normalized: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        normalized_call = _normalize_tool_call_candidate(call, index=index)
        if normalized_call is None:
            continue
        existing_index = _matching_tool_call_index(normalized, normalized_call)
        if existing_index is None:
            normalized.append(normalized_call)
            continue
        normalized[existing_index] = _merge_tool_call(normalized[existing_index], normalized_call)
    return normalized


def _response_tool_call_candidates(response: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for value in [
        getattr(response, "tool_calls", None),
        getattr(response, "invalid_tool_calls", None),
        getattr(response, "tool_call_chunks", None),
        _additional_kwarg_tool_calls(response),
        _content_tool_calls(getattr(response, "content", None)),
    ]:
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    return candidates


def _additional_kwarg_tool_calls(response: Any) -> list[dict[str, Any]]:
    additional_kwargs = getattr(response, "additional_kwargs", None) or {}
    if not isinstance(additional_kwargs, dict):
        return []
    calls: list[dict[str, Any]] = []
    for key in ("tool_calls", "invalid_tool_calls", "tool_call_chunks"):
        value = additional_kwargs.get(key)
        if isinstance(value, list):
            calls.extend(item for item in value if isinstance(item, dict))
    return calls


def _content_tool_calls(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or "").strip()
        if block_type != "tool_use":
            continue
        calls.append(
            {
                "name": item.get("name"),
                "args": item.get("input"),
                "id": item.get("id"),
                "type": "tool_call",
            }
        )
    return calls


def _normalize_tool_call_candidate(call: dict[str, Any], *, index: int) -> dict[str, Any] | None:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = str(call.get("name") or function.get("name") or "")
    if not name:
        return None
    args = _first_present_tool_call_args(
        call.get("args"),
        function.get("arguments"),
        call.get("arguments"),
        call.get("input"),
    )
    return {
        "name": name,
        "args": _tool_call_args(args),
        "id": str(call.get("id") or call.get("tool_call_id") or f"call_{index}_{name}"),
        "type": "tool_call",
    }


def _first_present_tool_call_args(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _matching_tool_call_index(calls: list[dict[str, Any]], call: dict[str, Any]) -> int | None:
    call_id = str(call.get("id") or "")
    if call_id:
        for index, existing in enumerate(calls):
            if str(existing.get("id") or "") == call_id:
                return index
    name = str(call.get("name") or "")
    for index, existing in enumerate(calls):
        if str(existing.get("name") or "") == name and not existing.get("args"):
            return index
    return None


def _merge_tool_call(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_args = existing.get("args") if isinstance(existing.get("args"), dict) else {}
    incoming_args = incoming.get("args") if isinstance(incoming.get("args"), dict) else {}
    return {
        "name": str(existing.get("name") or incoming.get("name") or ""),
        "args": incoming_args if incoming_args else existing_args,
        "id": str(existing.get("id") or incoming.get("id") or ""),
        "type": "tool_call",
    }


def _tool_call_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}
