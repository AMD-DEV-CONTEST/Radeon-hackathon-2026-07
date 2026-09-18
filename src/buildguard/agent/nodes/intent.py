"""Intent classification node."""

from buildguard.agent.nodes.prompts import load_prompt
from buildguard.agent.state import AgentState, IntentResult
from buildguard.llm.base import ChatMessage, LocalLLMBackend


def classify_intent(state: AgentState, backend: LocalLLMBackend) -> dict[str, object]:
    # Explicit image attachments are already a high-confidence inspection intent.
    # The remaining planning, execution, analysis, verification and reply nodes
    # still run through the Agent graph.
    if state["image_paths"]:
        return {
            "intent": IntentResult(
                category="inspection",
                complexity="multi_step",
                confidence=1.0,
            )
        }
    action = state["requested_action"]
    action_hint = f"\nExplicit user action hint: {action}." if action else ""
    prompt = (
        f"{load_prompt('intent.txt')}\nUser query: {state['user_query']}"
        f"{action_hint}"
    )
    intent = backend.structured_chat(
        [ChatMessage(role="user", content=prompt)], IntentResult, thinking=False
    )
    return {
        "intent": intent,
        "performance_trace": list(getattr(backend, "metrics_history", [])[-1:]),
    }
