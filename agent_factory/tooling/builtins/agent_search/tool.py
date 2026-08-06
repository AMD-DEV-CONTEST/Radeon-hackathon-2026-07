from __future__ import annotations

from typing import Any

from agent_factory.agent_registry import search_agents
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    del resources
    output = search_agents(arguments)
    return tool_envelope(output, summary=str(output.get("message") or ""))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    query = str(arguments.get("query") or "").strip()
    if not query:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=["agent_search requires a non-empty query"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["agent_search only reads the local Agent registry index"],
        facts={"query_length": len(query)},
    ).model_dump(mode="json")
