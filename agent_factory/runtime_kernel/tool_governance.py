from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from collections.abc import Mapping
from typing import Any, Iterable

from langchain_core.messages import ToolMessage

from agent_factory.runtime_kernel.state import RuntimeState, ToolLoopGovernanceState, ToolLoopMetrics, ToolState
from agent_factory.tooling.langgraph_node import tool_observation_message
from agent_factory.tooling.spec import ToolLoopPolicyConfig


@dataclass(slots=True)
class ToolCallPreflight:
    allowed_calls: list[dict[str, Any]]
    denied_messages: list[ToolMessage]
    governance: ToolLoopGovernanceState


def preflight_tool_calls(
    state: RuntimeState,
    calls: list[dict[str, Any]],
    tools: Iterable[Any],
) -> ToolCallPreflight:
    policies = _tool_policies(tools)
    governance = state.tools.loop_governance.model_copy(deep=True)
    allowed: list[dict[str, Any]] = []
    denied: list[ToolMessage] = []
    reserved_total: dict[str, int] = {}
    reserved_exact: dict[tuple[str, str], int] = {}
    reserved_semantic: dict[tuple[str, str], int] = {}
    for call in calls:
        tool_id = str(call.get("name") or "")
        policy = policies.get(tool_id)
        if policy is None or not policy.enabled:
            allowed.append(call)
            continue
        metrics = governance.tools.setdefault(tool_id, ToolLoopMetrics())
        exact_key = _call_fingerprint(tool_id, dict(call.get("args") or {}))
        semantic_key = _semantic_fingerprint(policy, dict(call.get("args") or {}))
        reason = _preflight_denial_reason(
            policy=policy,
            metrics=metrics,
            tool_id=tool_id,
            exact_key=exact_key,
            semantic_key=semantic_key,
            reserved_total=reserved_total,
            reserved_exact=reserved_exact,
            reserved_semantic=reserved_semantic,
        )
        if reason:
            if reason[0] == "exhausted":
                metrics.exhausted = True
                metrics.exhaustion_reason = reason[1]
            denied.append(_governance_denial_message(call, reason=reason[1]))
            continue
        allowed.append(call)
        reserved_total[tool_id] = reserved_total.get(tool_id, 0) + 1
        reserved_exact[(tool_id, exact_key)] = reserved_exact.get((tool_id, exact_key), 0) + 1
        if semantic_key is not None:
            reserved_semantic[(tool_id, semantic_key)] = reserved_semantic.get((tool_id, semantic_key), 0) + 1
    return ToolCallPreflight(allowed_calls=allowed, denied_messages=denied, governance=governance)


def record_tool_call_outcomes(
    governance: ToolLoopGovernanceState,
    calls: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    tools: Iterable[Any],
) -> ToolLoopGovernanceState:
    policies = _tool_policies(tools)
    by_call_id = {
        str(item.get("tool_call_id") or ""): item
        for item in observations
        if isinstance(item, dict) and str(item.get("tool_call_id") or "")
    }
    updated = governance.model_copy(deep=True)
    for call in calls:
        tool_id = str(call.get("name") or "")
        policy = policies.get(tool_id)
        if policy is None or not policy.enabled:
            continue
        call_id = str(call.get("id") or tool_id)
        observation = by_call_id.get(call_id)
        if observation is None:
            continue
        metrics = updated.tools.setdefault(tool_id, ToolLoopMetrics())
        arguments = dict(call.get("args") or {})
        exact_key = _call_fingerprint(tool_id, arguments)
        semantic_key = _semantic_fingerprint(policy, arguments)
        metrics.call_count += 1
        metrics.exact_call_counts[exact_key] = metrics.exact_call_counts.get(exact_key, 0) + 1
        if semantic_key is not None:
            metrics.semantic_call_counts[semantic_key] = metrics.semantic_call_counts.get(semantic_key, 0) + 1
        completed = str(observation.get("status") or "") == "completed"
        metrics.consecutive_failures = 0 if completed else metrics.consecutive_failures + 1
        if completed and policy.evidence_output_pointers:
            _record_evidence(metrics, policy, observation.get("output"))
        _apply_exhaustion(policy, metrics)
    return updated


def exhausted_tool_ids(state: RuntimeState) -> set[str]:
    return {
        tool_id
        for tool_id, metrics in state.tools.loop_governance.tools.items()
        if metrics.exhausted
    }


def tool_governance_prompt(state: Any) -> str:
    tool_state = _tool_state_from_model_state(state)
    if tool_state is None:
        return ""
    exhausted = [
        (tool_id, metrics)
        for tool_id, metrics in tool_state.loop_governance.tools.items()
        if metrics.exhausted
    ]
    if not exhausted:
        return ""
    lines = [
        "Tool loop governance has stopped further calls for the following tools:",
        *[
            f"- {tool_id}: {metrics.exhaustion_reason or 'configured call budget exhausted'}"
            for tool_id, metrics in exhausted
        ],
        (
            "Do not retry or rephrase calls to these tools in this turn. Complete the task from evidence already obtained, "
            "explicitly identify unavailable facts, and do not claim missing evidence was retrieved."
        ),
    ]
    return "\n".join(lines)


def _tool_state_from_model_state(state: Any) -> ToolState | None:
    value = state.get("tools") if isinstance(state, Mapping) else getattr(state, "tools", None)
    if value is None:
        return None
    if isinstance(value, ToolState):
        return value
    if isinstance(value, Mapping):
        return ToolState.model_validate(value)
    raise TypeError(f"runtime tool state must be ToolState or mapping, got {type(value).__name__}")


def _tool_policies(tools: Iterable[Any]) -> dict[str, ToolLoopPolicyConfig]:
    policies: dict[str, ToolLoopPolicyConfig] = {}
    for tool in tools:
        metadata = getattr(tool, "metadata", None)
        agent_factory = metadata.get("agent_factory") if isinstance(metadata, dict) else None
        raw = agent_factory.get("loop_policy") if isinstance(agent_factory, dict) else None
        policy = ToolLoopPolicyConfig.model_validate(raw or {})
        if policy.enabled:
            policies[str(getattr(tool, "name", "") or "")] = policy
    return policies


def _preflight_denial_reason(
    *,
    policy: ToolLoopPolicyConfig,
    metrics: ToolLoopMetrics,
    tool_id: str,
    exact_key: str,
    semantic_key: str | None,
    reserved_total: dict[str, int],
    reserved_exact: dict[tuple[str, str], int],
    reserved_semantic: dict[tuple[str, str], int],
) -> tuple[str, str] | None:
    if metrics.exhausted:
        return "exhausted", metrics.exhaustion_reason or "configured tool call budget exhausted"
    if policy.max_calls is not None and metrics.call_count + reserved_total.get(tool_id, 0) >= policy.max_calls:
        return "exhausted", f"maximum tool calls reached ({policy.max_calls})"
    exact_count = metrics.exact_call_counts.get(exact_key, 0) + reserved_exact.get((tool_id, exact_key), 0)
    if policy.max_identical_calls is not None and exact_count >= policy.max_identical_calls:
        return "duplicate", "identical tool arguments already reached the configured limit"
    if semantic_key is not None and policy.max_semantic_calls is not None:
        semantic_count = metrics.semantic_call_counts.get(semantic_key, 0) + reserved_semantic.get(
            (tool_id, semantic_key), 0
        )
        if semantic_count >= policy.max_semantic_calls:
            return "duplicate", "semantically equivalent tool request already reached the configured limit"
    return None


def _governance_denial_message(call: dict[str, Any], *, reason: str) -> ToolMessage:
    tool_id = str(call.get("name") or "")
    return tool_observation_message(
        status="execution_failed",
        tool_id=tool_id,
        tool_call_id=str(call.get("id") or tool_id),
        message=f"Tool loop governance denied this call: {reason}.",
        arguments=dict(call.get("args") or {}),
        retryable=False,
        evidence={"tool_loop_governance": {"denied": True, "reason": reason}},
        execution_status="failed",
        contract_status="valid",
        errors=[reason],
    )


def _record_evidence(metrics: ToolLoopMetrics, policy: ToolLoopPolicyConfig, output: Any) -> None:
    values = [_json_pointer_value(output, pointer) for pointer in policy.evidence_output_pointers]
    if all(_empty_evidence(value) for value in values):
        metrics.consecutive_empty_results += 1
        metrics.consecutive_no_new_evidence += 1
        return
    metrics.consecutive_empty_results = 0
    fingerprint = _fingerprint(values)
    if fingerprint in metrics.evidence_fingerprints:
        metrics.consecutive_no_new_evidence += 1
        return
    metrics.evidence_fingerprints.append(fingerprint)
    if policy.max_calls is not None:
        metrics.evidence_fingerprints = metrics.evidence_fingerprints[-policy.max_calls :]
    metrics.consecutive_no_new_evidence = 0


def _apply_exhaustion(policy: ToolLoopPolicyConfig, metrics: ToolLoopMetrics) -> None:
    reasons = [
        (
            policy.max_calls is not None and metrics.call_count >= policy.max_calls,
            f"maximum tool calls reached ({policy.max_calls})",
        ),
        (
            policy.max_consecutive_failures is not None
            and metrics.consecutive_failures >= policy.max_consecutive_failures,
            f"consecutive failures reached {policy.max_consecutive_failures}",
        ),
        (
            policy.max_consecutive_empty_results is not None
            and metrics.consecutive_empty_results >= policy.max_consecutive_empty_results,
            f"consecutive empty results reached {policy.max_consecutive_empty_results}",
        ),
        (
            policy.max_consecutive_no_new_evidence is not None
            and metrics.consecutive_no_new_evidence >= policy.max_consecutive_no_new_evidence,
            f"consecutive calls without new evidence reached {policy.max_consecutive_no_new_evidence}",
        ),
    ]
    for matched, reason in reasons:
        if matched:
            metrics.exhausted = True
            metrics.exhaustion_reason = reason
            return


def _semantic_fingerprint(policy: ToolLoopPolicyConfig, arguments: dict[str, Any]) -> str | None:
    if not policy.semantic_argument_pointers:
        return None
    values = [_json_pointer_value(arguments, pointer) for pointer in policy.semantic_argument_pointers]
    if all(value is None for value in values):
        return None
    return _fingerprint(values)


def _call_fingerprint(tool_id: str, arguments: dict[str, Any]) -> str:
    return _fingerprint({"tool_id": tool_id, "arguments": arguments})


def _fingerprint(value: Any) -> str:
    payload = json.dumps(_canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


def _json_pointer_value(value: Any, pointer: str) -> Any:
    current = value
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
                continue
            except (ValueError, IndexError):
                pass
        return None
    return current


def _empty_evidence(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
