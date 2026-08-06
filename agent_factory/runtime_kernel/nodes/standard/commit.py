from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class TerminalCommitNode:
    impl_id = "terminal.commit"
    node_type = "terminal"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"memory", "execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        return {
            "execution": {"current_node": context.node_id, "route_decision": "always"},
        }
