from __future__ import annotations

from typing import Any

from langchain_core.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from agent_factory.context_system.events import emit_context_event
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.planning import is_plan_and_execute_pattern_id
from agent_factory.runtime_kernel.state import RuntimeState


CONTEXT_PREPARE_SYSTEM_WRAPPER_ID = "system.context_prepare"
PLAN_AND_EXECUTE_DYNAMIC_CONTEXT_NODES = frozenset({"executor", "casual_react"})


class ContextPrepareSystemWrapper:
    wrapper_id = CONTEXT_PREPARE_SYSTEM_WRAPPER_ID
    before_stage = "pre_execute"

    def before(self, *, state: RuntimeState, context: NodeExecutionContext) -> tuple[RuntimeState, dict[str, Any]]:
        if not context.impl.startswith("cognitive."):
            return state, {}
        runtime = getattr(context.services, "context_system", None)
        if runtime is None:
            return state, {}
        emit_context_event(
            services=context.services,
            state=state,
            event_type="context_prepare_started",
            node_id=context.node_id,
            payload={"node_id": context.node_id, "status": "started"},
        )
        try:
            result = runtime.prepare_before_model_call(
                state=state,
                node_id=context.node_id,
                impl=context.impl,
                messages=list(context.graph_messages or []),
                services=context.services,
                resources=getattr(context.services, "runtime_resources", {}) or {},
                enable_dynamic_evidence=_dynamic_evidence_enabled(state=state, context=context),
            )
        except Exception as exc:
            emit_context_event(
                services=context.services,
                state=state,
                event_type="context_prepare_failed",
                node_id=context.node_id,
                payload={
                    "node_id": context.node_id,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise
        context.graph_messages = list(result.messages)
        patch: dict[str, Any] = {"context": result.state.context.model_dump(mode="json")}
        if result.messages_changed:
            patch["messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES), *result.messages]
        emit_context_event(
            services=context.services,
            state=result.state,
            event_type="context_prepare_completed",
            node_id=context.node_id,
            payload={
                "node_id": context.node_id,
                "status": "completed",
                "messages_changed": result.messages_changed,
                "item_count": len(result.frame.items) if result.frame is not None else 0,
                "token_estimate": result.frame.token_estimate if result.frame is not None else 0,
            },
        )
        return result.state, patch


def _dynamic_evidence_enabled(*, state: RuntimeState, context: NodeExecutionContext) -> bool:
    if not is_plan_and_execute_pattern_id(state.run.pattern_id):
        return True
    return context.node_id in PLAN_AND_EXECUTE_DYNAMIC_CONTEXT_NODES


SYSTEM_CONTEXT_PREPARE_WRAPPER = ContextPrepareSystemWrapper()
