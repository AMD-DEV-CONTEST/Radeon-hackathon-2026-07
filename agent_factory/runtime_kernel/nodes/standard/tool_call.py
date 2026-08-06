from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.plan_execute_tools import (
    PLAN_EXECUTE_CASUAL_NODE_ID,
    PLAN_EXECUTE_EXECUTOR_NODE_ID,
    PLAN_EXECUTE_FINAL_NODE_ID,
    PLAN_EXECUTE_PLANNER_NODE_ID,
    merge_tool_ids,
    plan_and_execute_delegated_tool_ids,
    plan_and_execute_runtime_plan_tool_ids,
    system_tool_ids,
    tool_access_ids,
    tool_access_ids_for_node,
)
from agent_factory.runtime_kernel.planning import (
    RUNTIME_PLAN_TOOL_ID,
    execute_runtime_plan_action,
    is_plan_and_execute_pattern_id,
)
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.nodes.standard.tool_visibility import (
    runtime_excluded_tool_ids,
    runtime_extra_allowed_tool_ids,
)
from agent_factory.tooling.langgraph_node import (
    build_tool_node_runner,
    latest_ai_tool_calls,
    tool_observation_message,
    tool_messages_to_runtime_patch,
)
from agent_factory.tooling.envelope import runtime_wait_control
from agent_factory.runtime_kernel.tool_governance import preflight_tool_calls, record_tool_call_outcomes


class OperationalToolCallNode:
    impl_id = "operational.tool_call"
    node_type = "operational"
    supports_interrupt = True
    supports_subgraph_slot = True
    writable_sections = {"tools", "plan", "policy", "execution", "observability"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        _ai_message, tool_calls = latest_ai_tool_calls(context.graph_messages)
        if not tool_calls:
            return {"execution": {"current_node": context.node_id, "route_decision": "tool.completed"}}
        origin_node_id = _origin_node_id(state, tool_calls)
        runtime_plan_calls, delegated_calls = _partition_runtime_plan_calls(tool_calls)
        allowed_for_origin = (
            plan_and_execute_runtime_plan_tool_ids(
                origin_node_id=origin_node_id,
                all_bindings=context.all_bindings,
            )
            if is_plan_and_execute_pattern_id(state.run.pattern_id)
            else tool_access_ids_for_node(context.all_bindings, node_id=origin_node_id)
        )
        runtime_plan_messages, plan_patch, working_state = _execute_runtime_plan_calls(
            state,
            runtime_plan_calls,
            allowed_tool_ids=allowed_for_origin,
        )

        registry = context.services.tool_registry
        if delegated_calls and (registry is None or not hasattr(registry, "model_tools")):
            messages = [*runtime_plan_messages, *_tool_registry_missing_messages(delegated_calls)]
            _results, failures, _policy_patch, route_decision = tool_messages_to_runtime_patch(messages)
            return {
                "messages": messages,
                **plan_patch,
                "tools": {
                    "tool_failures": [*state.tools.tool_failures, *failures],
                    "pending_tool_call": None,
                    "pending_tool_calls": [],
                },
                "execution": {"current_node": context.node_id, "route_decision": route_decision},
            }

        visible_tool_ids = _visible_tool_ids(state, context, registry, origin_node_id=origin_node_id)
        visible_tools = list(registry.model_tools(visible_tool_ids)) if delegated_calls else []
        messages: list[ToolMessage] = list(runtime_plan_messages)
        preflight = preflight_tool_calls(working_state, delegated_calls, visible_tools)
        executable_calls = preflight.allowed_calls
        messages.extend(preflight.denied_messages)
        if executable_calls:
            runner = build_tool_node_runner(
                visible_tools,
                node_id=context.node_id,
                name=context.node_id,
                allowed_tool_ids=set(visible_tool_ids),
                known_tool_ids=set(registry.list_tool_ids()) if hasattr(registry, "list_tool_ids") else set(visible_tool_ids),
                origin_node_id=origin_node_id,
                origin_impl="cognitive.answer",
                emit_event=context.emit_event,
            )
            output = runner.invoke(
                {
                    "messages": _messages_with_tool_calls(context.graph_messages, executable_calls),
                    "runtime": working_state.model_dump(mode="json"),
                },
                config=context.graph_config,
                runtime=context.graph_runtime,
            )
            messages.extend(output.get("messages") or [])
        results, failures, policy_patch, route_decision = tool_messages_to_runtime_patch(messages)
        governance = record_tool_call_outcomes(
            preflight.governance,
            executable_calls,
            [*results, *failures],
            visible_tools,
        )
        route_decision = _caller_route_decision(working_state, origin_node_id, route_decision)
        wait_control = runtime_wait_control(results)
        execution_patch: dict[str, Any] = {
            "current_node": context.node_id,
            "route_decision": route_decision,
        }
        if wait_control is not None:
            execution_patch.update(
                {
                    "route_decision": "execution.finished",
                    "finished": True,
                    "finish_status": wait_control["status"],
                }
            )
        patch: dict[str, Any] = {
            "messages": messages,
            **plan_patch,
            "tools": {
                "tool_results": [*state.tools.tool_results, *results],
                "tool_failures": [*state.tools.tool_failures, *failures],
                "last_tool_result": results[-1] if results else state.tools.last_tool_result,
                "pending_tool_call": None,
                "pending_tool_calls": [],
                "loop_governance": governance.model_dump(mode="json"),
            },
            "execution": execution_patch,
        }
        if policy_patch:
            patch["policy"] = policy_patch
        return patch


def _visible_tool_ids(
    state: RuntimeState,
    context: NodeExecutionContext,
    registry: Any,
    *,
    origin_node_id: str,
) -> list[str]:
    if is_plan_and_execute_pattern_id(state.run.pattern_id):
        visible_tool_ids = _plan_and_execute_delegated_tool_ids(
            state,
            context,
            registry,
            origin_node_id=origin_node_id,
        )
    else:
        visible_tool_ids = merge_tool_ids([
            *_allowed_tool_ids(context),
            *runtime_extra_allowed_tool_ids(state),
            *system_tool_ids(registry),
        ])
    excluded_tool_ids = set(runtime_excluded_tool_ids(state))
    return [tool_id for tool_id in visible_tool_ids if tool_id not in excluded_tool_ids]


def _plan_and_execute_delegated_tool_ids(
    state: RuntimeState,
    context: NodeExecutionContext,
    registry: Any,
    *,
    origin_node_id: str,
) -> list[str]:
    return plan_and_execute_delegated_tool_ids(
        origin_node_id=origin_node_id,
        all_bindings=context.all_bindings,
        registry=registry,
        extra_tool_ids=runtime_extra_allowed_tool_ids(state),
    )


def _allowed_tool_ids(context: NodeExecutionContext) -> list[str]:
    current_node_tool_ids = tool_access_ids(context.bindings)
    if current_node_tool_ids:
        return current_node_tool_ids
    return tool_access_ids(context.all_bindings)


def _tool_registry_missing_messages(tool_calls: list[dict[str, Any]]):
    messages = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        tool_call_id = str(call.get("id") or tool_id)
        messages.append(
            tool_observation_message(
                status="tool_registry_missing",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message="tool registry missing",
                arguments=dict(call.get("args") or {}),
                retryable=False,
            )
        )
    return messages


def _origin_node_id(state: RuntimeState, tool_calls: list[dict[str, Any]]) -> str:
    origins = {str(call.get("origin_node_id") or "") for call in tool_calls}
    origins.discard("")
    if len(origins) == 1:
        return next(iter(origins))
    if is_plan_and_execute_pattern_id(state.run.pattern_id):
        raise RuntimeError("plan_and_execute tool calls must carry exactly one origin_node_id")
    return ""


def _partition_runtime_plan_calls(tool_calls: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runtime_plan_calls: list[dict[str, Any]] = []
    delegated_calls: list[dict[str, Any]] = []
    for call in tool_calls:
        if str(call.get("name") or "") == RUNTIME_PLAN_TOOL_ID:
            runtime_plan_calls.append(call)
        else:
            delegated_calls.append(call)
    return runtime_plan_calls, delegated_calls


def _execute_runtime_plan_calls(
    state: RuntimeState,
    calls: list[dict[str, Any]],
    *,
    allowed_tool_ids: list[str],
) -> tuple[list[ToolMessage], dict[str, Any], RuntimeState]:
    messages: list[ToolMessage] = []
    working_state = state
    plan_changed = False
    for call in calls:
        arguments = dict(call.get("args") or {})
        if RUNTIME_PLAN_TOOL_ID not in set(allowed_tool_ids):
            messages.append(
                tool_observation_message(
                    status="tool_not_allowed",
                    tool_id=RUNTIME_PLAN_TOOL_ID,
                    tool_call_id=str(call.get("id") or RUNTIME_PLAN_TOOL_ID),
                    message="runtime_plan is not visible to this node.",
                    arguments=arguments,
                    retryable=False,
                    errors=["runtime_plan is not visible to this node."],
                )
            )
            continue
        result = execute_runtime_plan_action(working_state, arguments)
        status = "completed" if result.status == "completed" else "execution_failed"
        if result.status == "completed":
            working_state = working_state.model_copy(update={"plan": result.plan}, deep=True)
            plan_changed = True
        messages.append(
            tool_observation_message(
                status=status,
                tool_id=RUNTIME_PLAN_TOOL_ID,
                tool_call_id=str(call.get("id") or RUNTIME_PLAN_TOOL_ID),
                message=result.message,
                arguments=arguments,
                retryable=result.status != "completed",
                output={"plan": result.plan.model_dump(mode="json")},
                evidence={"runtime_state_section": "plan"},
                execution_status="completed" if result.status == "completed" else "failed",
                contract_status="valid",
                errors=[] if result.status == "completed" else [result.message],
            )
        )
    return messages, {"plan": working_state.plan.model_dump(mode="json")} if plan_changed else {}, working_state


def _messages_with_tool_calls(messages: list[Any], tool_calls: list[dict[str, Any]]) -> list[Any]:
    from langchain_core.messages import AIMessage

    updated = list(messages)
    for index in range(len(updated) - 1, -1, -1):
        message = updated[index]
        if not isinstance(message, AIMessage):
            continue
        updated[index] = AIMessage(
            content=message.content,
            additional_kwargs=dict(message.additional_kwargs),
            response_metadata=dict(message.response_metadata),
            name=message.name,
            id=message.id,
            tool_calls=[
                {
                    "name": str(call.get("name") or ""),
                    "args": dict(call.get("args") or {}),
                    "id": str(call.get("id") or call.get("name") or ""),
                    "type": "tool_call",
                }
                for call in tool_calls
            ],
        )
        break
    return updated


def _caller_route_decision(state: RuntimeState, origin_node_id: str, route_decision: str) -> str:
    if not is_plan_and_execute_pattern_id(state.run.pattern_id):
        return route_decision
    if route_decision == "policy.blocked":
        return route_decision
    if origin_node_id == PLAN_EXECUTE_PLANNER_NODE_ID:
        if state.plan.status == "active":
            return "tool.return.executor"
        return "tool.return.planner"
    if origin_node_id == PLAN_EXECUTE_EXECUTOR_NODE_ID:
        return "tool.return.executor"
    if origin_node_id == PLAN_EXECUTE_FINAL_NODE_ID:
        return "tool.return.final_answer"
    if origin_node_id == PLAN_EXECUTE_CASUAL_NODE_ID:
        return route_decision
    return route_decision
