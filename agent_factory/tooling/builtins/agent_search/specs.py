from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_SEARCH_TOOL_ID = "agent_search"


def get_agent_search_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_SEARCH_TOOL_ID,
            description=(
                "Searches published child Agents by task requirements. Before creating a multi-Agent "
                "subtask, use this tool to find candidates and assign only package_id values returned in "
                "candidates. This tool searches existing Agents and does not manufacture one. When status "
                "is no_suitable_agent, the primary Agent may separately request manufacturing based on "
                "manufacturing_recommendation."
            ),
            entrypoint="agent_factory.tooling.builtins.agent_search.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language task requirement or subtask description; do not reduce it to capability tags.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {"type": "string", "enum": ["matched", "no_suitable_agent"]},
                    "query": {"type": "string"},
                    "candidates": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "manufacturing_recommendation": {"type": "object", "additionalProperties": True},
                    "embedding_used": {"type": "boolean"},
                    "message": {"type": "string"},
                },
                "required": ["status", "query", "candidates", "embedding_used", "message"],
            },
            risk_level="low",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_search.tool:evaluate_risk",
            ),
            concurrent=True,
        )
    ]
