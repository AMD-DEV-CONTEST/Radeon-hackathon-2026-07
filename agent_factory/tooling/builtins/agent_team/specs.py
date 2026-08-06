from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_TEAM_TOOL_ID = "agent_team"


def get_agent_team_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_TEAM_TOOL_ID,
            description=(
                "Splits one objective across multiple published Agents for parallel or dependency-ordered "
                "execution. Each member keeps an independent session and workspace and returns results "
                "through deliver_result. Confirm every package_id with agent_search first. After start, "
                "briefly summarize member assignments to the user and end the response. Do not poll; member "
                "status changes actively resume the current session. Use depends_on whenever a task consumes "
                "another task's output, and leave it empty only for genuinely independent work."
            ),
            entrypoint="agent_factory.tooling.builtins.agent_team.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_team.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    task = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "task_key": {"type": "string", "minLength": 1},
            "package_id": {"type": "string", "minLength": 1},
            "task": {"type": "string", "minLength": 1},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
            "depends_on": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "expected_artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "description": {"type": "string", "minLength": 1},
                        "suggested_name": {"type": "string", "minLength": 1},
                    },
                    "required": ["description"],
                },
            },
            "context": {"type": "object", "additionalProperties": True},
        },
        "required": ["task_key", "package_id", "task", "acceptance_criteria"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["start", "cancel"]},
            "title": {"type": "string", "minLength": 1},
            "tasks": {"type": "array", "items": task, "minItems": 2, "maxItems": 12},
            "task_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1
            },
            "reason": {"type": "string"},
        },
        "required": ["action"],
        "allOf": [
            {
                "if": {"properties": {"action": {"const": "start"}}, "required": ["action"]},
                "then": {"required": ["title", "tasks"]},
            },
            {
                "if": {"properties": {"action": {"const": "cancel"}}, "required": ["action"]},
                "then": {"required": ["task_ids"]},
            },
        ],
    }
