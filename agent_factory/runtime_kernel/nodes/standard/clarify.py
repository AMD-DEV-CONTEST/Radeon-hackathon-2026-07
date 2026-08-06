from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.nodes.standard.answer import CognitiveAnswerNode
from agent_factory.runtime_kernel.state import RuntimeState


class CognitiveClarifyNode(CognitiveAnswerNode):
    impl_id = "cognitive.clarify"

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        if not context.bindings:
            context.bindings.append(
                {
                    "binding_type": "prompt",
                    "payload": {
                        "prompt_id": "prompt.clarify.default",
                        "template": "Clarify missing user intent.",
                        "variables": ["conversation"],
                    },
                }
            )
        return super().execute(state, context)
