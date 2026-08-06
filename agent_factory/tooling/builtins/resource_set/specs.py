"""ToolSpec definitions for the resource_set builtin tool."""

from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


RESOURCE_SET_TOOL_ID = "resource_set"


def get_resource_set_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=RESOURCE_SET_TOOL_ID,
            description=(
                "Tracks resource paths explored in the current session. Use action=add for a path already read, "
                "action=list to inspect the record, and action=remove to remove an entry."
            ),
            entrypoint="agent_factory.tooling.builtins.resource_set.resource_set:run",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "remove"],
                        "description": "Action to perform on the resource set.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Single path to add or remove.",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Multiple paths to add or remove.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "status": {"type": "string"},
                    "message": {"type": "string"},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "added": {"type": "array", "items": {"type": "string"}},
                    "removed": {"type": "array", "items": {"type": "string"}},
                    "total": {"type": "integer"},
                },
                "required": ["action", "status", "message", "total"],
                "additionalProperties": False,
            },
            resources={"store": "resource_set_store"},
            risk_level="low",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.resource_set.resource_set:evaluate_risk"
            ),
            concurrent=True,
        )
    ]
