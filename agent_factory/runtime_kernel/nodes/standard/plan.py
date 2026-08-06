from __future__ import annotations

from agent_factory.runtime_kernel.nodes.standard.answer import CognitiveAnswerNode


class CognitivePlanNode(CognitiveAnswerNode):
    impl_id = "cognitive.plan"
