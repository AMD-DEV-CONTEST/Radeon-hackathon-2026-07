from __future__ import annotations

from typing import Any

from agent_factory.tooling.builtins.process.manager import PROCESS_MANAGER, output_limit, required_string
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    _ = context
    if not isinstance(arguments.get("process_id"), str) or not arguments.get("process_id", "").strip():
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["process_id is required"],
        ).model_dump(mode="json")
    return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    _ = resources
    process_id = required_string(arguments, "process_id")
    return tool_envelope(
        PROCESS_MANAGER.snapshot(
            process_id=process_id,
            max_output_chars=output_limit(arguments),
        )
    )
