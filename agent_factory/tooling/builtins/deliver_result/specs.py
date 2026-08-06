from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


DELIVER_RESULT_TOOL_ID = "deliver_result"


def get_deliver_result_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=DELIVER_RESULT_TOOL_ID,
            description=(
                "Formally delivers the current delegated task to its parent Agent and is available only in a "
                "child run delegated by a parent. Call it once before finishing, with the true status, a concise "
                "summary, and any workspace files or directories to transfer. The system validates provenance, "
                "transfers artifacts transactionally, and sends a structured report to the parent. An ordinary "
                "text response is not formal delivery."
            ),
            entrypoint="agent_factory.tooling.builtins.deliver_result.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="low",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.deliver_result.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    text_array = {"type": "array", "items": {"type": "string", "minLength": 1}}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"type": "string", "enum": ["completed", "partial", "blocked", "failed"]},
            "summary": {"type": "string", "minLength": 1},
            "artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                    },
                    "required": ["path", "description"],
                },
            },
            "key_findings": text_array,
            "remaining_issues": text_array,
            "recommended_next_actions": text_array,
        },
        "required": ["status", "summary"],
    }
