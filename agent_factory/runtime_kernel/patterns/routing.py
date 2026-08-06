from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.execution.routing import resolve_route
from agent_factory.runtime_kernel.patterns.node_observability import emit_state_event
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec, PatternNodeSpec
from agent_factory.runtime_kernel.patterns.state_patches import runtime_state_from_graph
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids


def make_entry_router(pattern: GraphPatternSpec):
    node_ids = {node.id for node in pattern.nodes}

    def route(raw_state: dict[str, Any]) -> str:
        state = runtime_state_from_graph(raw_state)
        if state.execution.current_node in node_ids and not state.execution.finished:
            return state.execution.current_node or pattern.entry_node
        return pattern.entry_node

    return route


def make_route_router(mapping: dict[str, str]):
    allowed = set(mapping)

    def route(raw_state: dict[str, Any]) -> str:
        state = runtime_state_from_graph(raw_state)
        if state.execution.finished or state.execution.interrupted or state.policy.interrupted:
            return "__end__"
        decision = state.execution.route_decision
        if decision in allowed:
            return decision or "__end__"
        return "__end__"

    return route


def resolve_after_node(
    *,
    pattern: GraphPatternSpec,
    node: PatternNodeSpec,
    state: RuntimeState,
    services: RuntimeServices,
) -> None:
    if timed_out(state) and state.execution.route_decision != "model.requests_tool":
        finish_state(state, status="failed", error="Execution timed out.")
        return
    if state.policy.interrupted or state.execution.interrupted:
        state.execution.interrupted = True
        state.execution.finished = True
        state.execution.finish_status = "interrupted"
        state.execution.current_node = node.id
        state.execution.interrupt_payload = interrupt_payload(state, node.id)
        return
    if state.policy.blocked:
        state.execution.finish_status = state.execution.finish_status or "blocked"
    if node.id in pattern.termination.success_nodes:
        state.execution.current_node = node.id
        state.execution.finished = True
        state.execution.finish_status = state.execution.finish_status or "completed"
        return
    if node.id in pattern.termination.failure_nodes:
        finish_state(state, status="failed", error=state.execution.last_error)
        state.execution.current_node = node.id
        return
    if state.execution.finished:
        state.execution.current_node = node.id
        state.execution.finish_status = state.execution.finish_status or (
            "blocked" if state.policy.blocked else "completed"
        )
        return
    route = resolve_route(pattern, current_node=node.id, state=state)
    if route.next_node is None or route.condition is None:
        finish_state(state, status="failed", error=f"No next node resolved from {node.id}.")
        state.execution.current_node = node.id
        return
    state.execution.route_decision = route.condition
    state.execution.current_node = route.next_node
    emit_state_event(
        services,
        state,
        "route_selected",
        node_id=node.id,
        payload={"condition": route.condition, "next_node": route.next_node},
    )


def finish_state(
    state: RuntimeState,
    *,
    status: str,
    error: str | None = None,
    location: str | None = None,
) -> None:
    state.execution.finished = True
    state.execution.finish_status = status
    state.execution.route_decision = "execution.finished"
    if error:
        state.execution.last_error = error
    if location:
        state.execution.last_error_location = location


def interrupt_payload(state: RuntimeState, node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "interrupt_type": state.policy.interrupt_type,
        "approval_required": state.policy.approval_required,
        "reason": state.policy.block_reason or state.policy.refusal_reason,
    }


def timed_out(state: RuntimeState) -> bool:
    if state.execution.timeout_seconds <= 0:
        return False
    try:
        started_at = datetime.fromisoformat(state.run.started_at)
    except ValueError:
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - started_at
    return elapsed.total_seconds() > state.execution.timeout_seconds


def must_repair_tool_protocol(node: PatternNodeSpec, raw_state: dict[str, Any]) -> bool:
    return node.impl == "operational.tool_call" and bool(incomplete_tool_call_ids(raw_state.get("messages") or []))
