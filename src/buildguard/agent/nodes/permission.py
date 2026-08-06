"""Tool confirmation policy node."""

from buildguard.agent.state import AgentState
from buildguard.config import AgentConfig


def check_permission(state: AgentState, config: AgentConfig) -> dict[str, object]:
    if state["status"] == "safe_failure":
        return {"status": "safe_failure", "errors": state["errors"]}
    if state["confirmation_denied"]:
        return {"status": "safe_failure", "errors": ["User denied tool execution"]}
    plan = state["plan"]
    if plan is None:
        return {"status": "safe_failure", "errors": [*state["errors"], "Plan is missing"]}
    restricted = [
        step.tool_name
        for step in plan.steps
        if step.requires_confirmation or step.tool_name in config.confirmation_tools
    ]
    if restricted and not state["confirmation_granted"]:
        return {
            "status": "WAIT_FOR_CONFIRMATION",
            "pending_confirmation": {
                "task_id": state["task_id"],
                "tools": restricted,
                "message": "Local tool execution requires user confirmation",
            },
        }
    return {"status": "running", "pending_confirmation": None}
