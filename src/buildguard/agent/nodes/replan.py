"""One bounded replanning transition."""

from buildguard.agent.nodes.planner import generate_plan
from buildguard.agent.state import AgentState
from buildguard.config import AgentConfig
from buildguard.llm.base import LocalLLMBackend


def replan(
    state: AgentState,
    backend: LocalLLMBackend,
    config: AgentConfig,
    *,
    tool_metadata: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if state["image_paths"] and state["plan_phase"] in {
        "inspection_enrichment",
        "risk",
    }:
        return {
            "plan": state["plan"],
            "current_step": 0,
            "errors": [],
            "retry_count": state["retry_count"] + 1,
            "status": "running",
        }
    update = generate_plan(
        state,
        backend,
        config,
        replanning=True,
        tool_metadata=tool_metadata,
    )
    update["retry_count"] = state["retry_count"] + 1
    update["status"] = "running"
    return update
