from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import AIMessage

from agent_factory.runtime_kernel.adapters.model import ModelRole
from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.plan_execute_tools import (
    PLAN_EXECUTE_NODE_IDS,
    merge_tool_ids,
    plan_and_execute_model_tool_ids,
    system_tool_ids,
    tool_access_ids,
)
from agent_factory.runtime_kernel.planning import (
    RUNTIME_PLAN_TOOL_ID,
    is_plan_and_execute_pattern_id,
    runtime_plan_model_tool,
)
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.nodes.standard.tool_visibility import (
    runtime_excluded_tool_ids,
    runtime_extra_allowed_tool_ids,
)
from agent_factory.context_system.token_counter import provider_token_budget_payload
from agent_factory.runtime_kernel.tool_governance import exhausted_tool_ids


class CognitiveAnswerNode:
    impl_id = "cognitive.answer"
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"conversation", "context", "tools", "execution"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        binding_payload = _prompt_binding_payload(context)
        model_operation_service = context.services.model_operation_service
        if model_operation_service is None:
            raise RuntimeKernelError("cognitive.answer requires model_operation_service.")
        visible_tools = _visible_tools(context, state)
        result = model_operation_service.tool_bound_chat(
            state=state,
            prompt_binding=binding_payload,
            messages=context.graph_messages,
            tools=visible_tools,
            emit_event=context.emit_event,
            services=context.services,
            node_id=context.node_id,
            model_role=_model_role_from_payload(_model_operation_payload(context.bindings), default="main"),
        )
        if result.clarification_question:
            reasoning_content = _reasoning_content_from_metadata(result.metadata)
            return {
                "messages": [AIMessage(content=result.clarification_question)],
                **_context_token_budget_patch(result.metadata, context.node_id),
                "conversation": {
                    "assistant_draft": result.assistant_draft,
                    "reasoning_content": reasoning_content,
                    "clarification_question": result.clarification_question,
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": result.route_decision or "subgraph.need_more_input",
                },
            }
        ai_message = result.ai_message if isinstance(result.ai_message, AIMessage) else None
        tool_calls = _message_tool_calls(ai_message) or list(result.tool_calls or [])
        reasoning_content = _reasoning_content_from_metadata(result.metadata)
        if tool_calls:
            return {
                "messages": [
                    _ai_message_with_origin(
                        result.assistant_draft or "",
                        tool_calls,
                        context,
                        reasoning_content=reasoning_content,
                    )
                ],
                **_context_token_budget_patch(result.metadata, context.node_id),
                "conversation": {
                    "assistant_draft": result.assistant_draft,
                    "reasoning_content": reasoning_content,
                },
                "tools": {
                    "pending_tool_call": None,
                    "pending_tool_calls": [],
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": "model.requests_tool",
                },
            }
        final_answer = result.final_answer or result.assistant_draft or ""
        response_message = AIMessage(
            content=final_answer,
            additional_kwargs=(
                {"reasoning_content": reasoning_content}
                if reasoning_content
                else {}
            ),
        )
        route_decision = result.route_decision or "model.ready_to_answer"
        if _plan_and_execute_planner_waiting_for_input(context=context, state=state):
            route_decision = "subgraph.need_more_input"
        return {
            "messages": [response_message],
            **_context_token_budget_patch(result.metadata, context.node_id),
            "conversation": {
                "assistant_draft": result.assistant_draft,
                "reasoning_content": reasoning_content,
                "final_answer": final_answer,
            },
            "execution": {
                "current_node": context.node_id,
                "route_decision": route_decision,
            },
        }


def _prompt_binding_payload(context: NodeExecutionContext) -> dict[str, Any] | None:
    model_operation = _model_operation_payload(context.bindings)
    prompt_id = str(model_operation.get("prompt_id") or "").strip()
    if prompt_id:
        return _prompt_binding_by_id(context, prompt_id)
    for binding in context.bindings:
        if binding.get("binding_type") == "prompt":
            return dict(binding.get("payload") or {})
    return None


def _model_operation_payload(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    for binding in bindings:
        if binding.get("binding_type") == "model_operation":
            return dict(binding.get("payload") or {})
    return {}


def _model_role_from_payload(payload: dict[str, Any], *, default: ModelRole) -> ModelRole:
    value = str(payload.get("model_role") or default).strip()
    if value not in {"main", "task", "compression"}:
        raise RuntimeKernelError(f"unsupported model_operation.model_role: {value}")
    return cast(ModelRole, value)


def _prompt_binding_by_id(context: NodeExecutionContext, prompt_id: str) -> dict[str, Any] | None:
    for binding in context.bindings:
        if binding.get("binding_type") != "prompt":
            continue
        payload = dict(binding.get("payload") or {})
        if payload.get("prompt_id") == prompt_id:
            return payload
    for binding in context.all_bindings:
        if binding.get("binding_type") != "prompt":
            continue
        target = dict(binding.get("target") or {})
        if target.get("node_id") != context.node_id or target.get("impl") != context.impl:
            continue
        payload = dict(binding.get("payload") or {})
        if payload.get("prompt_id") == prompt_id:
            return payload
    raise RuntimeKernelError(f"cognitive.answer prompt binding not found: {prompt_id}")


def _context_token_budget_patch(metadata: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    data = dict(metadata or {})
    usage_metadata = data.get("usage_metadata") if isinstance(data.get("usage_metadata"), dict) else {}
    token_budget = provider_token_budget_payload(
        usage_metadata=usage_metadata,
        provider_input_tokens=data.get("provider_input_tokens"),
        node_id=node_id,
        model_role=str(data.get("model_role") or ""),
    )
    if not token_budget:
        return {}
    return {
        "context": {
            "token_budget": token_budget,
        }
    }


def _message_tool_calls(message: AIMessage | None) -> list[dict[str, Any]]:
    if message is None:
        return []
    calls = getattr(message, "tool_calls", None) or []
    return [dict(item) for item in calls if isinstance(item, dict)]


def _visible_tools(context: NodeExecutionContext, state: RuntimeState) -> list[Any]:
    registry = context.services.tool_registry
    allowed_tool_ids = _model_visible_tool_ids(context, state, registry)
    tools: list[Any] = []
    if registry is None or not hasattr(registry, "model_tools"):
        registry_tools = []
    else:
        registry_tools = list(registry.model_tools(allowed_tool_ids))
    tools.extend(registry_tools)
    if _runtime_plan_visible(context=context, state=state, allowed_tool_ids=allowed_tool_ids):
        tools.append(runtime_plan_model_tool())
    return tools


def _model_visible_tool_ids(context: NodeExecutionContext, state: RuntimeState, registry: Any) -> list[str]:
    if _is_plan_and_execute_node(context, state):
        visible_tool_ids = plan_and_execute_model_tool_ids(
            node_id=context.node_id,
            node_bindings=context.bindings,
            all_bindings=context.all_bindings,
            registry=registry,
            extra_tool_ids=runtime_extra_allowed_tool_ids(state),
        )
    else:
        visible_tool_ids = merge_tool_ids([
            *_allowed_tool_ids(context),
            *runtime_extra_allowed_tool_ids(state),
            *system_tool_ids(registry),
        ])
    excluded_tool_ids = set(runtime_excluded_tool_ids(state))
    unavailable_tool_ids = excluded_tool_ids | exhausted_tool_ids(state)
    return [tool_id for tool_id in visible_tool_ids if tool_id not in unavailable_tool_ids]


def _allowed_tool_ids(context: NodeExecutionContext) -> list[str]:
    current_node_tool_ids = tool_access_ids(context.bindings)
    if current_node_tool_ids:
        return current_node_tool_ids
    return tool_access_ids(context.all_bindings)


def _runtime_plan_visible(*, context: NodeExecutionContext, state: RuntimeState, allowed_tool_ids: list[str]) -> bool:
    if not is_plan_and_execute_pattern_id(state.run.pattern_id):
        return False
    if context.node_id not in {"planner", "executor"}:
        return False
    return RUNTIME_PLAN_TOOL_ID in set(allowed_tool_ids)


def _is_plan_and_execute_node(context: NodeExecutionContext, state: RuntimeState) -> bool:
    if not is_plan_and_execute_pattern_id(state.run.pattern_id):
        return False
    return context.node_id in PLAN_EXECUTE_NODE_IDS


def _plan_and_execute_planner_waiting_for_input(*, context: NodeExecutionContext, state: RuntimeState) -> bool:
    if not is_plan_and_execute_pattern_id(state.run.pattern_id):
        return False
    if context.node_id != "planner":
        return False
    return getattr(state.plan, "status", "empty") == "empty"


def _reasoning_content_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    value = (metadata or {}).get("reasoning_content")
    if isinstance(value, str):
        return value.strip() or None
    return None


def _ai_message_with_origin(
    content: str,
    tool_calls: list[dict[str, Any]],
    context: NodeExecutionContext,
    *,
    reasoning_content: str | None = None,
) -> AIMessage:
    additional_kwargs = {
        "agent_factory_origin_node_id": context.node_id,
        "agent_factory_origin_impl": context.impl,
    }
    if reasoning_content:
        additional_kwargs["reasoning_content"] = reasoning_content
    return AIMessage(
        content=content,
        tool_calls=tool_calls,
        additional_kwargs=additional_kwargs,
    )
