from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.observability.render_events import emit_runtime_render_event
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_render import RuntimeRenderEvent


RENDER_NODE_SYSTEM_WRAPPER_ID = "observability.render_node"


class RenderNodeSystemWrapper:
    wrapper_id = RENDER_NODE_SYSTEM_WRAPPER_ID
    before_stage = "node_start"

    def before(self, *, state: RuntimeState, context: NodeExecutionContext) -> None:
        self._emit(
            state=state,
            context=context,
            event_type="node_started",
            payload=_base_payload(context),
        )

    def after(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        node_result: dict[str, Any],
        duration_ms: int,
    ) -> None:
        payload = {
            **_base_payload(context),
            "duration_ms": duration_ms,
            "output_summary": _output_summary(node_result),
        }
        self._emit(
            state=state,
            context=context,
            event_type="node_completed",
            payload=payload,
        )

    def on_error(self, *, state: RuntimeState, context: NodeExecutionContext, error: Exception) -> None:
        payload = {
            **_base_payload(context),
            "error_summary": str(error),
        }
        self._emit(
            state=state,
            context=context,
            event_type="node_failed",
            severity="error",
            message=str(error),
            payload=payload,
        )

    def _emit(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        event_type: str,
        payload: dict[str, Any],
        severity: str = "info",
        message: str | None = None,
    ) -> None:
        spec = context.render_spec
        if spec is None:
            return
        render_event = RuntimeRenderEvent(
            event_type=event_type,  # type: ignore[arg-type]
            producer_type="agent",
            session_id=state.run.session_id,
            run_id=state.run.run_id,
            graph_id=state.run.pattern_id,
            node_id=spec.node_id,
            node_label=spec.label,
            node_kind=spec.kind,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            payload=payload,
        )
        emit_runtime_render_event(
            services=context.services,
            state=state,
            render_event=render_event,
        )


SYSTEM_RENDER_NODE_WRAPPER = RenderNodeSystemWrapper()


def _base_payload(context: NodeExecutionContext) -> dict[str, Any]:
    spec = context.render_spec
    if spec is None:
        return {}
    return {
        "wrapper_id": RENDER_NODE_SYSTEM_WRAPPER_ID,
        "purpose": spec.purpose,
        "doing": spec.doing,
        "expected_output": spec.expected_output,
        "visible_to_user": spec.visible_to_user,
    }


def _output_summary(node_result: dict[str, Any]) -> str:
    if not node_result:
        return "Node completed without state changes."
    keys = ", ".join(sorted(str(key) for key in node_result)[:8])
    return f"Node produced state sections: {keys}."
