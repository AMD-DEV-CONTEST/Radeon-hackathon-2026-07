from __future__ import annotations

from typing import Any

from agent_factory.knowledge_system.guidance import KNOWLEDGE_GUIDANCE_CONTEXT_KEY, knowledge_guidance_text
from agent_factory.knowledge_system.runtime import KnowledgeRuntime
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


KNOWLEDGE_GUIDANCE_SYSTEM_WRAPPER_ID = "system.knowledge_guidance"


class KnowledgeGuidanceSystemWrapper:
    wrapper_id = KNOWLEDGE_GUIDANCE_SYSTEM_WRAPPER_ID
    before_stage = "pre_execute"

    def before(self, *, state: RuntimeState, context: NodeExecutionContext) -> tuple[RuntimeState, dict[str, Any]]:
        if not context.impl.startswith("cognitive."):
            return state, {}
        runtime = getattr(context.services, "knowledge_runtime", None)
        if not isinstance(runtime, KnowledgeRuntime):
            return state, {}
        guidance = knowledge_guidance_text(runtime)
        updated = state.model_copy(deep=True)
        model_context = dict(updated.context.model_context)
        if guidance:
            model_context[KNOWLEDGE_GUIDANCE_CONTEXT_KEY] = guidance
        else:
            model_context.pop(KNOWLEDGE_GUIDANCE_CONTEXT_KEY, None)
        updated.context.model_context = model_context
        updated.context.assembly_log.append(f"system_knowledge_guidance:{context.node_id}")
        return updated, {"context": updated.context.model_dump(mode="json")}


SYSTEM_KNOWLEDGE_GUIDANCE_WRAPPER = KnowledgeGuidanceSystemWrapper()
