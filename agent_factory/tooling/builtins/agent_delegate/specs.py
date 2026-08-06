from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_DELEGATE_TOOL_ID = "agent_delegate"


def get_agent_delegate_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_DELEGATE_TOOL_ID,
            description=(
                "Asynchronously delegates one well-bounded task to a published child Agent. "
                "Use agent_search first to obtain a real package_id, then action=start. "
                "The child keeps an independent session and workspace and must formally deliver through "
                "deliver_result. Artifacts are transferred transactionally into the current workspace and "
                "the current session is actively resumed for acceptance and synthesis. After a successful "
                "start, briefly summarize the task and assignment to the user, end the response, and wait "
                "for active updates. Do not query progress. action=cancel stops an unfinished task."
            ),
            entrypoint="agent_factory.tooling.builtins.agent_delegate.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_delegate.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["start", "cancel"]},
            "package_id": {"type": "string", "minLength": 1},
            "task": {"type": "string", "minLength": 1},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
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
            "task_id": {"type": "string", "minLength": 1},
            "reason": {"type": "string"},
        },
        "required": ["action"],
        "allOf": [
            {
                "if": {"properties": {"action": {"const": "start"}}, "required": ["action"]},
                "then": {"required": ["package_id", "task", "acceptance_criteria"]},
            },
            {
                "if": {"properties": {"action": {"const": "cancel"}}, "required": ["action"]},
                "then": {"required": ["task_id"]},
            },
        ],
    }
