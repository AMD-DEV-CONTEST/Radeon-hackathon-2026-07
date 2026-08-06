from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class CognitiveRouteNode:
    impl_id = "cognitive.route"
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        route = "subgraph.done"
        if state.policy.blocked:
            route = "subgraph.blocked"
        elif state.conversation.clarification_question:
            route = "subgraph.need_more_input"
        return {
            "execution": {
                "current_node": context.node_id,
                "route_decision": route,
            }
        }
