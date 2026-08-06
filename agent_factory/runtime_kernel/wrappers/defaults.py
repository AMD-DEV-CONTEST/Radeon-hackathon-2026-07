from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.wrappers.base import NodeWrapper
from agent_factory.runtime_kernel.wrappers.decorators import wrap_node


class ConsoleTraceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None


@wrap_node(
    "console.node_trace",
    phases={"before", "after"},
    reads={"execution"},
    writes={"observability"},
    config_schema=ConsoleTraceConfig,
    description="Print and trace node before/after execution.",
)
class ConsoleNodeTraceWrapper(NodeWrapper):
    def before(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        print(f"节点 {context.node_id} 前")
        return {
            "observability": {
                "debug_refs": [
                    *state.observability.debug_refs,
                    {"kind": "node_wrapper", "wrapper_id": self.wrapper_id, "phase": "before", "node_id": context.node_id},
                ]
            }
        }

    def after(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        config: dict[str, Any],
        node_result: dict[str, Any],
    ) -> dict[str, Any]:
        print(f"节点 {context.node_id} 后")
        return {
            "observability": {
                "debug_refs": [
                    *state.observability.debug_refs,
                    {"kind": "node_wrapper", "wrapper_id": self.wrapper_id, "phase": "after", "node_id": context.node_id},
                ]
            }
        }


class PrepareModelContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_user_config: bool = True


@wrap_node(
    "context.prepare_model_context",
    phases={"before"},
    reads={"conversation", "context", "policy", "runtime_config"},
    writes={"context"},
    config_schema=PrepareModelContextConfig,
    description="Build model context before a cognitive node runs.",
)
class PrepareModelContextWrapper(NodeWrapper):
    def before(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        prompt_binding = _first_binding_payload(context.bindings, "prompt")
        model_context = context.services.context_engine.build_model_context(
            state=state,
            binding=prompt_binding,
        )
        if config.get("include_user_config", True):
            model_context["user_config"] = dict(state.runtime_config.user_config)
        return {
            "context": {
                "model_context": model_context,
                "assembly_log": [*state.context.assembly_log, f"wrapper:{self.wrapper_id}:{context.node_id}"],
            }
        }


@wrap_node(
    "context.prepare_tool_context",
    phases={"before"},
    reads={"conversation", "context", "policy", "runtime_config"},
    writes={"context"},
    description="Build tool context before an operational node runs.",
)
class PrepareToolContextWrapper(NodeWrapper):
    def before(
        self,
        *,
        state: RuntimeState,
        context: NodeExecutionContext,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        tool_binding = _first_binding_payload(context.bindings, "tool_access")
        tool_context = context.services.context_engine.build_tool_context(
            state=state,
            binding=tool_binding,
        )
        tool_context["user_config"] = dict(state.runtime_config.user_config)
        return {
            "context": {
                "tool_context": tool_context,
                "assembly_log": [*state.context.assembly_log, f"wrapper:{self.wrapper_id}:{context.node_id}"],
            }
        }


def _first_binding_payload(bindings: list[dict[str, Any]], binding_type: str) -> dict[str, Any] | None:
    for binding in bindings:
        if binding.get("binding_type") == binding_type:
            return dict(binding.get("payload") or {})
    return None
