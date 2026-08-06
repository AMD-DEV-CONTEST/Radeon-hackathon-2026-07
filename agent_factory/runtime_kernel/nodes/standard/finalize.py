from __future__ import annotations

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class FinalizeNode:
    impl_id = "finalize"
    node_type = "reserved"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"conversation", "execution"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, object]:
        final_answer = state.conversation.final_answer or state.conversation.assistant_draft or ""
        finish_status = "blocked" if state.policy.blocked else "completed"
        return {
            "conversation": {
                "final_answer": final_answer,
            },
            "execution": {
                "current_node": context.node_id,
                "finished": True,
                "finish_status": finish_status,
            },
        }
