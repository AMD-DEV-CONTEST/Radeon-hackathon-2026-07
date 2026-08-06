from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.execution import ExecutionController
from agent_factory.runtime_kernel.kernel.models import CompiledKernelApp
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec, PatternIOContractSpec
from agent_factory.runtime_kernel.state import RuntimeState


def make_subgraph_executor(
    *,
    node_id: str,
    compiled: CompiledKernelApp,
    services: RuntimeServices,
    input_contract: PatternIOContractSpec,
    output_contract: PatternIOContractSpec,
    state_mode: str,
):
    controller = ExecutionController()

    def runner(parent_state: RuntimeState, _context: NodeExecutionContext) -> dict[str, Any]:
        if parent_state.execution.subgraph_depth >= parent_state.execution.max_subgraph_depth:
            return {
                "execution": {
                    "current_node": node_id,
                    "finished": True,
                    "finish_status": "failed",
                    "route_decision": "execution.finished",
                    "last_error": "Execution exceeded max_subgraph_depth.",
                }
            }
        entered = RuntimeObservationEvent(
            trace_id=parent_state.observability.trace_id,
            run_id=parent_state.run.run_id,
            event_type="subgraph_entered",
            node_id=node_id,
            subgraph_id=compiled.pattern_spec.pattern_id,
        )
        services.observability_manager.emit(entered)
        _record_trace_event(services, parent_state, entered)
        child_input = project_state_for_subgraph(
            parent_state,
            input_contract=input_contract,
            state_mode=state_mode,
        )
        child_input.execution.current_node = None
        child_input.execution.current_subgraph = compiled.pattern_spec.pattern_id
        child_input.execution.subgraph_depth = parent_state.execution.subgraph_depth + 1
        child_input.execution.finished = False
        child_input.execution.finish_status = None
        child_state = controller.run(compiled, child_input, thread_id=child_input.run.session_id)
        route = child_state.execution.route_decision or ""
        if route.startswith("subgraph."):
            exit_route = route.split(".", 1)[1]
        else:
            exit_route = child_state.execution.finish_status or "done"
            if exit_route == "completed":
                exit_route = "done"
        merged_sections = merge_subgraph_output(parent_state, child_state, output_contract)
        exited = RuntimeObservationEvent(
            trace_id=parent_state.observability.trace_id,
            run_id=parent_state.run.run_id,
            event_type="subgraph_exited",
            node_id=node_id,
            subgraph_id=compiled.pattern_spec.pattern_id,
            payload={"exit_route": exit_route},
        )
        services.observability_manager.emit(exited)
        _record_trace_event(services, parent_state, exited)
        return {
            **merged_sections,
            "execution": {
                "current_node": node_id,
                "route_decision": f"subgraph.{exit_route}",
                "current_subgraph": None,
                "subgraph_depth": parent_state.execution.subgraph_depth,
            },
            "observability": {
                "events": [
                    *parent_state.observability.events,
                    entered.model_dump(mode="json"),
                    *child_state.observability.events,
                    exited.model_dump(mode="json"),
                ],
                "debug_refs": [*parent_state.observability.debug_refs, *child_state.observability.debug_refs],
                "metrics": {
                    **parent_state.observability.metrics,
                    "subgraph_count": int(parent_state.observability.metrics.get("subgraph_count", 0)) + 1,
                },
            },
        }

    return runner


def _record_trace_event(services: RuntimeServices, state: RuntimeState, event: RuntimeObservationEvent) -> None:
    trace_recorder = getattr(services, "trace_recorder", None)
    if trace_recorder is None:
        return
    trace_recorder.record_event(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        event_type=event.event_type,
        node_id=event.node_id,
        message=event.message,
        payload=event.payload,
    )


def project_state_for_subgraph(
    state: RuntimeState,
    *,
    input_contract: PatternIOContractSpec,
    state_mode: str,
) -> RuntimeState:
    source = state.model_copy(deep=True) if state_mode == "isolated" else state.model_copy(deep=True)
    allowed = set(input_contract.readable_sections)
    if not allowed:
        return source
    data = source.model_dump(mode="python")
    for section in [
        "conversation",
        "context",
        "tools",
        "policy",
        "execution",
        "observability",
    ]:
        if section not in allowed:
            data[section] = RuntimeState().model_dump(mode="python")[section]
    return RuntimeState.model_validate(data)


def merge_subgraph_output(
    parent: RuntimeState,
    child: RuntimeState,
    output_contract: PatternIOContractSpec,
) -> dict[str, Any]:
    allowed = set(output_contract.writable_sections)
    if not allowed:
        return {}
    patch: dict[str, Any] = {}
    child_data = child.model_dump(mode="json")
    for section in allowed:
        if section in child_data:
            patch[section] = child_data[section]
    return patch


def validate_subgraph_exit_routes(*, node_id: str, pattern: GraphPatternSpec, child: GraphPatternSpec) -> None:
    expected = {f"subgraph.{route}" for route in child.exit_routes}
    actual = {edge.when for edge in pattern.edges if edge.from_ == node_id and edge.when.startswith("subgraph.")}
    missing = expected.difference(actual)
    if missing:
        raise ValueError(
            f"Parent pattern {pattern.pattern_id} is missing subgraph routes for {node_id}: {', '.join(sorted(missing))}"
        )
