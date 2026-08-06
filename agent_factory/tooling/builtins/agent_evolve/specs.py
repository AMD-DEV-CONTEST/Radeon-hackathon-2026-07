from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_EVOLVE_TOOL_ID = "agent_evolve"


def get_agent_evolve_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_EVOLVE_TOOL_ID,
            description=(
                "Asynchronously evolves a published Agent. After action=start succeeds, briefly summarize "
                "the evolution goal to the user and end the response. Do not poll; completion, failure, or "
                "requests for information actively return to this session. action=respond answers an evolution "
                "question or tool approval and must continue the original request_id. Use background_tasks only "
                "for exception diagnosis. action=cancel cancels and rolls back unfinished evolution."
            ),
            entrypoint="agent_factory.tooling.builtins.agent_evolve.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_evolve.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["start", "respond", "cancel"]},
            "package_id": {"type": "string", "minLength": 1},
            "goal": {"type": "string", "minLength": 1},
            "constraints": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "task_id": {"type": "string", "minLength": 1},
            "response": {"type": "string"},
            "decision": {"type": "string", "enum": ["approve", "deny", "revise"]},
            "reason": {"type": "string"},
        },
        "required": ["action"],
        "allOf": [
            {
                "if": {"properties": {"action": {"const": "start"}}, "required": ["action"]},
                "then": {"required": ["package_id", "goal"]},
            },
            {
                "if": {
                    "properties": {"action": {"enum": ["respond", "cancel"]}},
                    "required": ["action"],
                },
                "then": {"required": ["task_id"]},
            },
        ],
    }
