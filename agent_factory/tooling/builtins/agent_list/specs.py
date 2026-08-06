from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_LIST_TOOL_ID = "agent_list"


def get_agent_list_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_LIST_TOOL_ID,
            description=(
                "Lists published assignable Agents as a read-only fallback when agent_search recall is "
                "insufficient. It does not perform semantic ranking or manufacture Agents. Returned "
                "package_id values support manual review; a coordinating Agent should still prefer "
                "agent_search candidates before creating work."
            ),
            entrypoint="agent_factory.tooling.builtins.agent_list.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Maximum number of Agents to return.",
                    }
                },
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {"type": "string", "enum": ["completed"]},
                    "agents": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "count": {"type": "integer"},
                    "message": {"type": "string"},
                },
                "required": ["status", "agents", "count", "message"],
            },
            risk_level="low",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_list.tool:evaluate_risk",
            ),
            concurrent=True,
        )
    ]
