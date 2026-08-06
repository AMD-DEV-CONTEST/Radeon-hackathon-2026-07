from __future__ import annotations

import json
from contextlib import nullcontext
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from agent_factory.runtime_kernel.observability.tool_events import emit_runtime_tool_activity
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids
from agent_factory.tooling.execution_context import (
    current_runtime_run_control,
    current_tool_approval_override,
    tool_approval_override,
    tool_call_context,
)
from agent_factory.tooling.gateway import (
    DEFAULT_TOOL_APPROVAL_TRUST_STORE,
    TRUST_TOOL_ACTIONS,
    parse_approval_decision,
)
from agent_factory.tooling.redaction import redact_json_pointer_paths
from agent_factory.tooling.runtime_resources import runtime_resource_overrides_from_state


ToolEventCallback = Callable[[dict[str, Any]], None]


class AgentFactoryToolNode:
    """Thin adapter around LangGraph's native ToolNode.

    The adapter keeps ToolNode as the execution primitive while adding
    AgentFactory's shared concerns at the boundary: ordered batching for
    non-concurrent tools, permission observations, tool-call events, and
    normalized ToolMessage observations.
    """

    def __init__(
        self,
        tools: Sequence[BaseTool],
        *,
        node_id: str,
        name: str | None = None,
        messages_key: str = "messages",
        allowed_tool_ids: set[str] | None = None,
        known_tool_ids: set[str] | None = None,
        origin_node_id: str = "",
        origin_impl: str = "",
        emit_event: ToolEventCallback | None = None,
        stream_events: bool = False,
    ) -> None:
        self.node_id = node_id
        self.origin_node_id = origin_node_id
        self.origin_impl = origin_impl
        self.messages_key = messages_key
        self.allowed_tool_ids = set(allowed_tool_ids) if allowed_tool_ids is not None else None
        self.known_tool_ids = set(known_tool_ids or {tool.name for tool in tools})
        self.emit_event = emit_event
        self.stream_events = stream_events
        self._concurrent_by_name = {tool.name: _tool_concurrent(tool) for tool in tools}
        self._approval_request_by_name = {tool.name: _tool_approval_request(tool) for tool in tools}
        self._sensitive_argument_paths_by_name = {
            tool.name: _tool_sensitive_argument_paths(tool) for tool in tools
        }
        self._tool_node = ToolNode(
            list(tools),
            name=name or node_id,
            messages_key=messages_key,
            wrap_tool_call=self._wrap_tool_call,
        )

    def __call__(
        self,
        state: Mapping[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, list[ToolMessage]]:
        return self.invoke(state, config=config, runtime=runtime)

    def invoke(
        self,
        state: Mapping[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, list[ToolMessage]]:
        messages = list(state.get(self.messages_key) or [])
        ai_message, tool_calls = latest_ai_tool_calls(messages)
        if ai_message is None or not tool_calls:
            return {self.messages_key: []}
        outputs: list[ToolMessage] = []
        invalid_calls, executable_calls = _partition_invalid_tool_calls(tool_calls)
        outputs.extend(_invalid_tool_call_messages(invalid_calls))
        batches = _tool_call_batches(executable_calls, self._concurrent_by_name)
        for batch_index, batch in enumerate(batches):
            if _runtime_stop_requested():
                outputs.extend(_cancelled_tool_messages(_remaining_batches(batches, batch_index)))
                break
            approval_requests = self._approval_requests_for_batch(batch, state=state)
            if approval_requests:
                decision = interrupt(_batch_approval_payload(approval_requests))
                parsed = parse_approval_decision(decision)
                if _is_trust_tool_decision(decision):
                    for request in approval_requests:
                        DEFAULT_TOOL_APPROVAL_TRUST_STORE.trust_tool(str(request.get("tool_name") or ""))
                if parsed.action != "approve":
                    outputs.extend(_approval_rejection_messages(batch, parsed.action, parsed.revision_guidance))
                    continue
            batch_state = dict(state)
            batch_state[self.messages_key] = _replace_latest_ai_tool_calls(messages, ai_message, batch)
            approval_context = (
                tool_approval_override(reason="approved by batch tool approval")
                if approval_requests
                else nullcontext()
            )
            with approval_context:
                raw_output = self._invoke_native_tool_node(batch_state, config=config, runtime=runtime)
            outputs.extend(_messages_from_tool_node_output(raw_output, self.messages_key))
            if _runtime_stop_requested():
                outputs.extend(_cancelled_tool_messages(_remaining_batches(batches, batch_index + 1)))
                break
        return {self.messages_key: _complete_tool_message_set(tool_calls, outputs)}

    def _approval_requests_for_batch(
        self,
        batch: Sequence[dict[str, Any]],
        *,
        state: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if current_tool_approval_override() is not None:
            return []
        requests: list[dict[str, Any]] = []
        for call in batch:
            tool_id = str(call.get("name") or "")
            if self.allowed_tool_ids is not None and tool_id not in self.allowed_tool_ids:
                continue
            approval_request = self._approval_request_by_name.get(tool_id)
            if approval_request is None:
                continue
            tool_call_id = str(call.get("id") or tool_id)
            with tool_call_context(
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                origin_node_id=self.origin_node_id,
                origin_impl=self.origin_impl,
                runtime_resource_overrides=runtime_resource_overrides_from_state(state),
            ):
                request = approval_request(dict(call.get("args") or {}), tool_call_id=tool_call_id)
            if isinstance(request, dict):
                requests.append(request)
        return requests

    def _invoke_native_tool_node(
        self,
        state: Mapping[str, Any],
        *,
        config: RunnableConfig,
        runtime: Runtime,
    ) -> Any:
        return self._tool_node.invoke(state, config, runtime=runtime or Runtime())

    def _wrap_tool_call(self, request: ToolCallRequest, execute: Callable[[ToolCallRequest], Any]) -> Any:
        tool_call = dict(request.tool_call)
        tool_id = str(tool_call.get("name") or "")
        tool_call_id = str(tool_call.get("id") or tool_id)
        arguments = dict(tool_call.get("args") or {})
        public_arguments = self._public_arguments(tool_id, arguments)
        if self.allowed_tool_ids is not None and tool_id not in self.allowed_tool_ids:
            message = "Tool is not visible to this node."
            payload = _observation_payload(
                status="tool_not_allowed",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message=message,
                arguments=public_arguments,
                output={"visible_tool_ids": sorted(self.allowed_tool_ids)},
                retryable=True,
            )
            self._emit(
                {
                    "event_type": "tool_failed",
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "arguments": public_arguments,
                    "status": "failed",
                    "error": message,
                    "observation": payload,
                    "message": message,
                }
            )
            return _tool_message(tool_id=tool_id, tool_call_id=tool_call_id, payload=payload, status="error")
        self._emit(
            {
                "event_type": "tool_proposed",
                "tool_id": tool_id,
                "tool_call_id": tool_call_id,
                "arguments": public_arguments,
                "status": "proposed",
            }
        )
        with tool_call_context(
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            origin_node_id=self.origin_node_id,
            origin_impl=self.origin_impl,
            event_sink=self._emit,
            runtime_resource_overrides=runtime_resource_overrides_from_state(request.state),
        ):
            result = execute(request)
        if isinstance(result, ToolMessage):
            normalized = _normalize_tool_message(
                result,
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                arguments=public_arguments,
            )
            event_type = _tool_event_type(normalized)
            self._emit(
                {
                    "event_type": event_type,
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "arguments": public_arguments,
                    "status": "completed" if event_type in {"tool_completed", "tool_contract_invalid"} else "failed",
                    "result": normalized,
                    "output": normalized.get("output"),
                    "evidence": normalized.get("evidence") if isinstance(normalized.get("evidence"), dict) else {},
                    "execution_status": str(normalized.get("execution_status") or ""),
                    "contract_status": str(normalized.get("contract_status") or ""),
                    "observation": normalized,
                    "error": None if event_type in {"tool_completed", "tool_contract_invalid"} else normalized.get("message"),
                    "message": str(normalized.get("message") or ""),
                }
            )
            return _tool_message(
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                payload=normalized,
                status="success" if event_type in {"tool_completed", "tool_contract_invalid"} else "error",
            )
        self._emit(
            {
                "event_type": "tool_completed",
                "tool_id": tool_id,
                "tool_call_id": tool_call_id,
                "arguments": public_arguments,
                "status": "completed",
                "message": "Tool returned a LangGraph command.",
            }
        )
        return result

    def _public_arguments(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        redacted = redact_json_pointer_paths(
            arguments,
            self._sensitive_argument_paths_by_name.get(tool_id, []),
        )
        return redacted if isinstance(redacted, dict) else {}

    def _emit(self, payload: dict[str, Any]) -> None:
        payload = {"node_id": self.node_id, **payload}
        if self.emit_event is not None:
            self.emit_event(payload)
        if self.stream_events:
            emit_runtime_tool_activity(payload, node_id=self.node_id)


def build_tool_node_runner(
    tools: Sequence[BaseTool],
    *,
    node_id: str,
    name: str | None = None,
    messages_key: str = "messages",
    allowed_tool_ids: set[str] | None = None,
    known_tool_ids: set[str] | None = None,
    origin_node_id: str = "",
    origin_impl: str = "",
    emit_event: ToolEventCallback | None = None,
    stream_events: bool = False,
) -> AgentFactoryToolNode:
    return AgentFactoryToolNode(
        tools,
        node_id=node_id,
        name=name,
        messages_key=messages_key,
        allowed_tool_ids=allowed_tool_ids,
        known_tool_ids=known_tool_ids,
        origin_node_id=origin_node_id,
        origin_impl=origin_impl,
        emit_event=emit_event,
        stream_events=stream_events,
    )


def _tool_approval_request(tool: BaseTool) -> Callable[..., dict[str, Any] | None] | None:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    agent_factory = metadata.get("agent_factory")
    if not isinstance(agent_factory, dict):
        return None
    approval_request = agent_factory.get("approval_request")
    return approval_request if callable(approval_request) else None


def _tool_sensitive_argument_paths(tool: BaseTool) -> list[str]:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return []
    agent_factory = metadata.get("agent_factory")
    if not isinstance(agent_factory, dict):
        return []
    paths = agent_factory.get("sensitive_argument_paths")
    return [str(item) for item in paths] if isinstance(paths, list) else []


def _batch_approval_payload(requests: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "tool_approval",
        "message": "检测到需要人工确认的工具调用，请确认执行、拒绝、信任工具，或输入审查意见让模型重写工具调用。",
        "choices": {"approve": "-y", "deny": "-n", "trust_tool": "-t", "revise": "custom"},
        "requests": [dict(request) for request in requests],
    }


def _approval_rejection_messages(
    tool_calls: Sequence[dict[str, Any]],
    action: str,
    guidance: str,
) -> list[ToolMessage]:
    status = "revision_requested" if action == "revise" else "denied"
    message = "Human requested argument revision before execution." if action == "revise" else "Tool call denied by human review."
    if guidance:
        message = f"{message} {guidance}"
    return [
        tool_observation_message(
            status=status,
            tool_id=str(call.get("name") or ""),
            tool_call_id=str(call.get("id") or call.get("name") or ""),
            message=message,
            arguments=dict(call.get("args") or {}),
            retryable=True,
        )
        for call in tool_calls
    ]


def _runtime_stop_requested() -> bool:
    control = current_runtime_run_control()
    return bool(control is not None and getattr(control, "drain_requested", False))


def _remaining_batches(
    batches: Sequence[Sequence[dict[str, Any]]],
    start: int,
) -> list[dict[str, Any]]:
    return [dict(call) for batch in batches[start:] for call in batch]


def _cancelled_tool_messages(tool_calls: Sequence[dict[str, Any]]) -> list[ToolMessage]:
    return [
        tool_observation_message(
            status="cancelled",
            tool_id=str(call.get("name") or ""),
            tool_call_id=str(call.get("id") or call.get("name") or ""),
            message="Tool call was cancelled before execution because the user stopped the run.",
            arguments=dict(call.get("args") or {}),
            retryable=False,
        )
        for call in tool_calls
    ]


def _is_trust_tool_decision(decision: Any) -> bool:
    if isinstance(decision, str):
        return decision.strip().lower() in TRUST_TOOL_ACTIONS or decision.strip().lower() in {"-t", "t", "trust me"}
    if isinstance(decision, dict):
        action = str(decision.get("action") or decision.get("choice") or "").strip().lower()
        if action in TRUST_TOOL_ACTIONS:
            return True
        return bool(decision.get("trust_tool") or decision.get("no_approval"))
    return False


def latest_ai_tool_calls(messages: Sequence[Any]) -> tuple[AIMessage | None, list[dict[str, Any]]]:
    following_tool_message_ids: set[str] = set()
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            tool_call_id = str(getattr(message, "tool_call_id", "") or "")
            if tool_call_id:
                following_tool_message_ids.add(tool_call_id)
            continue
        if not isinstance(message, AIMessage):
            continue
        normalized = _declared_ai_tool_calls(message)
        unresolved = [
            call
            for call in normalized
            if str(call.get("id") or "") and str(call.get("id") or "") not in following_tool_message_ids
        ]
        return message, unresolved
    return None, []


def latest_ai_declared_tool_calls(messages: Sequence[Any]) -> tuple[AIMessage | None, list[dict[str, Any]]]:
    """Return every tool call declared by the latest AI message, including completed calls."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message, _declared_ai_tool_calls(message)
    return None, []


def _declared_ai_tool_calls(message: AIMessage) -> list[dict[str, Any]]:
    calls = [
        *list(getattr(message, "tool_calls", None) or []),
        *list(getattr(message, "invalid_tool_calls", None) or []),
    ]
    origin_node_id = _message_origin_node_id(message)
    origin_impl = _message_origin_impl(message)
    return [
        _normalize_tool_call(item, index=index, origin_node_id=origin_node_id, origin_impl=origin_impl)
        for index, item in enumerate(calls)
    ]


def _partition_invalid_tool_calls(tool_calls: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    invalid: list[dict[str, Any]] = []
    executable: list[dict[str, Any]] = []
    for call in tool_calls:
        if call.get("invalid_tool_call"):
            invalid.append(dict(call))
        else:
            executable.append(dict(call))
    return invalid, executable


def _invalid_tool_call_messages(tool_calls: Sequence[dict[str, Any]]) -> list[ToolMessage]:
    messages: list[ToolMessage] = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        tool_call_id = str(call.get("id") or tool_id)
        raw_args = str(call.get("raw_args") or "")
        error = str(call.get("error") or "").strip()
        details = "The model emitted an invalid native tool call. Retry the same intent with valid JSON tool arguments."
        if error:
            details = f"{details} Parser error: {error}"
        messages.append(
            tool_observation_message(
                status="invalid_tool_call",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message=details,
                arguments={"raw_args": raw_args} if raw_args else {},
                retryable=True,
                errors=[error] if error else [],
            )
        )
    return messages


def _complete_tool_message_set(
    tool_calls: Sequence[dict[str, Any]],
    messages: Sequence[ToolMessage],
) -> list[ToolMessage]:
    by_call_id: dict[str, ToolMessage] = {}
    for message in messages:
        tool_call_id = str(getattr(message, "tool_call_id", "") or "")
        if tool_call_id and tool_call_id not in by_call_id:
            by_call_id[tool_call_id] = message
    completed: list[ToolMessage] = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        tool_call_id = str(call.get("id") or tool_id)
        if tool_call_id in by_call_id:
            completed.append(by_call_id[tool_call_id])
            continue
        completed.append(
            tool_observation_message(
                status="execution_failed",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                message="ToolNode did not return an observation for this tool call.",
                arguments=dict(call.get("args") or {}),
                retryable=True,
            )
        )
    return completed


def tool_messages_to_runtime_patch(
    messages: Sequence[ToolMessage],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    policy_patch: dict[str, Any] = {}
    route_decision = "tool.completed"
    for message in messages:
        payload = _parse_tool_message_content(message.content)
        if not isinstance(payload, dict):
            payload = _observation_payload(
                status="completed" if getattr(message, "status", "success") != "error" else "execution_failed",
                tool_id=str(message.name or ""),
                tool_call_id=str(message.tool_call_id or ""),
                message=str(message.content),
                arguments={},
                output={"value": message.content},
                retryable=getattr(message, "status", "success") == "error",
            )
        if _observation_completed(payload):
            results.append(payload)
            continue
        failures.append(payload)
        if route_decision == "tool.completed":
            route_decision = "tool.failed"
    return results, failures, policy_patch, route_decision


def tool_observation_message(
    *,
    status: str,
    tool_id: str,
    tool_call_id: str,
    message: str,
    arguments: dict[str, Any],
    retryable: bool,
    output: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    execution_status: str | None = None,
    contract_status: str | None = None,
    errors: list[str] | None = None,
) -> ToolMessage:
    return _tool_message(
        tool_id=tool_id,
        tool_call_id=tool_call_id,
        status="success" if status == "completed" else "error",
        payload=_observation_payload(
            status=status,
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=message,
            arguments=arguments,
            retryable=retryable,
            output=output,
            evidence=evidence,
            execution_status=execution_status,
            contract_status=contract_status,
            errors=errors,
        ),
    )


def _tool_call_batches(
    tool_calls: Sequence[dict[str, Any]],
    concurrent_by_name: Mapping[str, bool],
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    for call in tool_calls:
        tool_id = str(call.get("name") or "")
        if concurrent_by_name.get(tool_id, True):
            if not batches:
                batches.append([])
            batches[0].append(call)
            continue
        for batch in batches:
            if all(str(item.get("name") or "") != tool_id for item in batch):
                batch.append(call)
                break
        else:
            batches.append([call])
    return batches


def _replace_latest_ai_tool_calls(
    messages: Sequence[Any],
    target: AIMessage,
    tool_calls: Sequence[dict[str, Any]],
) -> list[Any]:
    replaced = list(messages)
    for index in range(len(replaced) - 1, -1, -1):
        if replaced[index] is not target:
            continue
        replaced[index] = AIMessage(
            content=target.content,
            additional_kwargs=dict(target.additional_kwargs),
            response_metadata=dict(target.response_metadata),
            name=target.name,
            id=target.id,
            tool_calls=[_langchain_tool_call(item) for item in tool_calls],
        )
        break
    return replaced


def _messages_from_tool_node_output(output: Any, messages_key: str) -> list[ToolMessage]:
    if isinstance(output, dict):
        candidates = output.get(messages_key) or []
    elif isinstance(output, list):
        candidates = output
    else:
        candidates = []
    return [item for item in candidates if isinstance(item, ToolMessage)]


def _tool_concurrent(tool: BaseTool) -> bool:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return True
    agent_factory = metadata.get("agent_factory")
    if not isinstance(agent_factory, dict):
        return True
    return bool(agent_factory.get("concurrent", True))


def _normalize_tool_call(
    item: Any,
    *,
    index: int,
    origin_node_id: str = "",
    origin_impl: str = "",
) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    name = str(item.get("name") or item.get("tool_id") or "")
    args = item.get("args") or item.get("arguments") or {}
    invalid = str(item.get("type") or "") == "invalid_tool_call"
    return {
        "name": name,
        "args": dict(args) if isinstance(args, dict) else {},
        "id": str(item.get("id") or item.get("tool_call_id") or f"call_{index}_{name}"),
        "type": "tool_call",
        "origin_node_id": str(item.get("origin_node_id") or origin_node_id or ""),
        "origin_impl": str(item.get("origin_impl") or origin_impl or ""),
        "invalid_tool_call": invalid,
        "raw_args": args if invalid and isinstance(args, str) else "",
        "error": str(item.get("error") or "") if invalid else "",
    }


def _message_origin_node_id(message: AIMessage) -> str:
    kwargs = getattr(message, "additional_kwargs", None)
    return str(kwargs.get("agent_factory_origin_node_id") or "") if isinstance(kwargs, dict) else ""


def _message_origin_impl(message: AIMessage) -> str:
    kwargs = getattr(message, "additional_kwargs", None)
    return str(kwargs.get("agent_factory_origin_impl") or "") if isinstance(kwargs, dict) else ""


def _langchain_tool_call(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or ""),
        "args": dict(item.get("args") or {}),
        "id": str(item.get("id") or item.get("name") or ""),
        "type": "tool_call",
    }


def _normalize_tool_message(
    message: ToolMessage,
    *,
    tool_id: str,
    tool_call_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    payload = _parse_tool_message_content(message.content)
    if not isinstance(payload, dict):
        return _observation_payload(
            status="completed" if getattr(message, "status", "success") != "error" else "execution_failed",
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=str(message.content),
            arguments=arguments,
            output={"value": message.content},
            retryable=getattr(message, "status", "success") == "error",
        )
    if payload.get("type") != "tool_observation":
        return _observation_payload(
            status=str(payload.get("status") or "completed"),
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            message=str(payload.get("message") or "Tool execution completed."),
            arguments=arguments,
            output=payload,
            retryable=False,
        )
    payload = dict(payload)
    payload["tool_id"] = str(payload.get("tool_id") or tool_id)
    payload["tool_call_id"] = str(payload.get("tool_call_id") or tool_call_id)
    if not isinstance(payload.get("arguments"), dict):
        payload["arguments"] = arguments
    return payload


def _parse_tool_message_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


def _observation_completed(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "completed":
        return False
    if payload.get("type") == "tool_observation":
        return True
    return True


def _tool_event_type(payload: dict[str, Any]) -> str:
    if _observation_completed(payload):
        return "tool_completed"
    if payload.get("execution_status") == "completed" and payload.get("contract_status") == "invalid":
        return "tool_contract_invalid"
    return "tool_failed"


def _tool_message(*, tool_id: str, tool_call_id: str, payload: dict[str, Any], status: str = "success") -> ToolMessage:
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        name=tool_id,
        tool_call_id=tool_call_id,
        status=status,  # type: ignore[arg-type]
    )


def _observation_payload(
    *,
    status: str,
    tool_id: str,
    tool_call_id: str,
    message: str,
    arguments: dict[str, Any],
    retryable: bool,
    output: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    execution_status: str | None = None,
    contract_status: str | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "tool_observation",
        "status": status,
        "tool_id": tool_id,
        "tool_call_id": tool_call_id,
        "message": message,
        "retryable": retryable,
        "arguments": arguments,
        "output": output,
        "evidence": evidence or {},
        "execution_status": execution_status or ("completed" if status == "completed" else "failed"),
        "contract_status": contract_status or "valid",
        "errors": errors if errors is not None else ([] if status == "completed" else [message]),
    }
