from __future__ import annotations

from time import perf_counter
import traceback
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.runtime import Runtime

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent
from agent_factory.runtime_kernel.observability.node_events import emit_runtime_node_event
from agent_factory.runtime_kernel.observability.tool_events import emit_runtime_tool_activity
from agent_factory.runtime_kernel.patterns.state_patches import (
    runtime_graph_patch,
    runtime_state_from_graph,
    split_graph_patch,
    validate_package_state_patch,
    validate_patch_sections,
)
from agent_factory.runtime_kernel.patterns.node_observability import (
    apply_node_metrics,
    emit_state_event,
    record_bookmark,
)
from agent_factory.runtime_kernel.patterns.routing import (
    finish_state,
    must_repair_tool_protocol,
    resolve_after_node,
    timed_out,
)
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec, PatternNodeSpec, PatternNodeWrapperSpec
from agent_factory.runtime_kernel.patterns.wrapper_pipeline import (
    execute_with_retries,
    run_node_wrappers,
    run_post_hooks,
    run_pre_hooks,
    run_system_after,
    run_system_before,
    run_system_on_error,
)
from agent_factory.runtime_kernel.state import RuntimeState, merge_state_patch
from agent_factory.runtime_kernel.state_contracts import PackageStateManager
from agent_factory.runtime_kernel.trace_policy import classify_node_failure
from agent_factory.runtime_kernel.wrappers import NodeWrapperRegistry
from agent_factory.runtime_render import NodeRenderSpec


def make_wrapped_runner(
    *,
    node: PatternNodeSpec,
    pattern: GraphPatternSpec,
    bindings: list[dict[str, Any]],
    all_bindings: list[dict[str, Any]],
    hook_bindings: list[dict[str, Any]],
    services: RuntimeServices,
    execute,
    validate_sections: bool,
    span_type: str,
    node_wrappers: list[PatternNodeWrapperSpec],
    node_wrapper_registry: NodeWrapperRegistry,
    render_spec: NodeRenderSpec | None,
    system_wrappers: list[Any],
    package_state_manager: PackageStateManager | None,
    writable_sections: set[str],
):
    node_wrappers = sorted(node_wrappers, key=lambda item: int(item.order))

    def runner(
        raw_state: dict[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, Any]:
        state = runtime_state_from_graph(raw_state)
        if state.execution.finished:
            return runtime_graph_patch(state)
        if timed_out(state) and not must_repair_tool_protocol(node, raw_state):
            finish_state(state, status="failed", error="Execution timed out before node execution.")
            return runtime_graph_patch(state)
        started = perf_counter()
        trace_recorder = getattr(services, "trace_recorder", None)
        trace_span_id = None
        if trace_recorder is not None:
            trace_span_id = trace_recorder.start_span(
                trace_id=state.observability.trace_id,
                run_id=state.run.run_id,
                span_kind=span_type,
                name=node.id,
                node_id=node.id,
                payload={"impl": node.impl, "node_id": node.id},
            )
        emit_state_event(services, state, "node_entered", node_id=node.id, payload={"impl": node.impl})
        emitted_events: list[dict[str, Any]] = []

        def emit_event(payload: dict[str, Any]) -> None:
            event = RuntimeObservationEvent(
                trace_id=state.observability.trace_id,
                run_id=state.run.run_id,
                event_type=payload.get("event_type", "node_event"),
                node_id=node.id,
                payload=payload,
            )
            services.observability_manager.emit(event)
            emit_runtime_node_event(event)
            if event.persistence == "durable":
                emitted_events.append(event.model_dump(mode="json"))
            if trace_recorder is not None:
                trace_recorder.record_event(
                    trace_id=state.observability.trace_id,
                    run_id=state.run.run_id,
                    event_type=event.event_type,
                    node_id=node.id,
                    message=event.message,
                    payload=event.payload,
                )
            emit_runtime_tool_activity(payload, node_id=node.id)

        context = NodeExecutionContext(
            node_id=node.id,
            impl=node.impl,
            bindings=bindings,
            all_bindings=all_bindings,
            hook_bindings=hook_bindings,
            services=services,
            emit_event=emit_event,
            render_spec=render_spec,
            graph_messages=list(raw_state.get("messages") or []),
            graph_config=config,
            graph_runtime=runtime,
        )
        record_bookmark(services, state, context, "entry")
        active_state = state
        system_messages_patch: list[Any] = []
        try:
            active_state, _system_start_patch = run_system_before(
                stage="node_start",
                wrappers=system_wrappers,
                state=active_state,
                context=context,
            )
            working_state, _pre_patch = run_pre_hooks(active_state, context)
            active_state = working_state
            before_state, _before_patch = run_node_wrappers(
                phase="before",
                state=working_state,
                context=context,
                wrapper_specs=node_wrappers,
                wrapper_registry=node_wrapper_registry,
                services=services,
                package_state_manager=package_state_manager,
            )
            active_state = before_state
            memory_state, memory_patch = run_system_before(
                stage="pre_execute",
                wrappers=system_wrappers,
                state=before_state,
                context=context,
            )
            active_state = memory_state
            system_pre_messages, system_runtime_patch = split_graph_patch(memory_patch)
            if system_runtime_patch:
                validate_package_state_patch(package_state_manager, node.id, system_runtime_patch)
                memory_state = merge_state_patch(memory_state, system_runtime_patch)
                active_state = memory_state
            system_messages_patch.extend(system_pre_messages)
            raw_patch = execute_with_retries(memory_state, context, execute)
            messages_patch, patch = split_graph_patch(raw_patch)
            if system_messages_patch:
                messages_patch = [*system_messages_patch, *messages_patch]
            if validate_sections:
                validate_patch_sections(node.impl, patch, writable_sections)
            validate_package_state_patch(package_state_manager, node.id, patch)
            updated = merge_state_patch(memory_state, patch)
            active_state = updated
            after_state, _after_patch = run_node_wrappers(
                phase="after",
                state=updated,
                context=context,
                wrapper_specs=node_wrappers,
                wrapper_registry=node_wrapper_registry,
                services=services,
                package_state_manager=package_state_manager,
                node_result=patch,
            )
            active_state = after_state
            updated = after_state
            post_patch = run_post_hooks(updated, context)
            if post_patch:
                updated = merge_state_patch(updated, post_patch)
            if emitted_events:
                updated.observability.events = [*updated.observability.events, *emitted_events]
            updated.execution.turn_count += 1
            apply_node_metrics(updated, perf_counter() - started)
            resolve_after_node(pattern=pattern, node=node, state=updated, services=services)
            duration_ms = int((perf_counter() - started) * 1000)
            run_system_after(
                wrappers=system_wrappers,
                state=updated,
                context=context,
                node_result=patch,
                duration_ms=duration_ms,
            )
            emit_state_event(
                services,
                updated,
                "node_completed",
                node_id=node.id,
                payload={"impl": node.impl, "duration_ms": duration_ms},
            )
            record_bookmark(services, updated, context, "completion")
            if trace_recorder is not None and trace_span_id is not None:
                trace_recorder.finish_span(
                    trace_id=updated.observability.trace_id,
                    run_id=updated.run.run_id,
                    span_id=trace_span_id,
                    span_kind=span_type,
                    name=node.id,
                    status="completed",
                    node_id=node.id,
                    payload={"node_id": node.id, "duration_ms": duration_ms},
                )
            return runtime_graph_patch(updated, messages=messages_patch)
        except GraphInterrupt:
            raise
        except Exception as exc:
            failed = active_state
            try:
                failed, on_error_patch = run_node_wrappers(
                    phase="on_error",
                    state=failed,
                    context=context,
                    wrapper_specs=node_wrappers,
                    wrapper_registry=node_wrapper_registry,
                    services=services,
                    package_state_manager=package_state_manager,
                    error=exc,
                )
                if on_error_patch:
                    failed = merge_state_patch(failed, on_error_patch)
            except Exception as wrapper_exc:
                exc = wrapper_exc
            failed.execution.retry_count += 1
            location = failed.execution.last_error_location or node.id
            finish_state(failed, status="failed", error=str(exc), location=location)
            run_system_on_error(wrappers=system_wrappers, state=failed, context=context, error=exc)
            failure = classify_node_failure(node_impl=node.impl, error=exc)
            if trace_recorder is not None and failure.domain == "runtime_kernel":
                trace_recorder.suppress_trace(
                    trace_id=failed.observability.trace_id,
                    run_id=failed.run.run_id,
                    reason=failure.reason,
                    payload={
                        "node_id": node.id,
                        "node_impl": node.impl,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": "".join(
                            traceback.TracebackException.from_exception(
                                exc,
                                capture_locals=False,
                            ).format()
                        ),
                    },
                )
            emit_state_event(
                services,
                failed,
                "node_failed",
                node_id=node.id,
                payload={"impl": node.impl, "error": str(exc)},
            )
            if trace_recorder is not None and trace_span_id is not None:
                trace_recorder.finish_span(
                    trace_id=failed.observability.trace_id,
                    run_id=failed.run.run_id,
                    span_id=trace_span_id,
                    span_kind=span_type,
                    name=node.id,
                    status="failed",
                    node_id=node.id,
                    payload={"node_id": node.id, "error": str(exc)},
                )
            return runtime_graph_patch(failed)

    return runner
