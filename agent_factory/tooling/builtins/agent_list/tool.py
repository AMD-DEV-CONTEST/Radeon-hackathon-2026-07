from __future__ import annotations

from typing import Any

from agent_factory.agent_registry import list_agents
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    del resources
    output = list_agents(arguments)
    return tool_envelope(output, summary=str(output.get("message") or ""))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del arguments, context
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["agent_list only reads the local Agent registry index"],
    ).model_dump(mode="json")
