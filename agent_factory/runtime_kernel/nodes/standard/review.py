from __future__ import annotations

from agent_factory.runtime_kernel.nodes.standard.answer import CognitiveAnswerNode


class CognitiveReviewNode(CognitiveAnswerNode):
    impl_id = "cognitive.review"
