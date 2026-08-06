from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class TerminalCloseNode:
    impl_id = "terminal.close"
    node_type = "terminal"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        return {
            "execution": {
                "current_node": context.node_id,
                "finished": True,
                "finish_status": state.execution.finish_status or "completed",
            }
        }
