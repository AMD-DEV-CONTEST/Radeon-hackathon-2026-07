from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


BACKGROUND_TASKS_TOOL_ID = "background_tasks"


def get_background_tasks_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=BACKGROUND_TASKS_TOOL_ID,
            description=(
                "Diagnoses or manages manufacturing, evolution, single-Agent delegation, and multi-Agent team "
                "tasks started by the current conversation. action=list returns summaries; action=get returns a "
                "task's phases, members, subtasks, activity, artifacts, pending items, and errors. Background tasks "
                "actively send progress and completion updates, so this tool is not a wait mechanism. Do not poll "
                "with list/get; call only when the user explicitly asks, when cancelling, or when diagnosing an anomaly."
            ),
            entrypoint="agent_factory.tooling.builtins.background_tasks.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["list", "get", "cancel"]},
                    "task_id": {"type": "string", "minLength": 1},
                    "reason": {"type": "string"},
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {
                            "properties": {"action": {"enum": ["get", "cancel"]}},
                            "required": ["action"]
                        },
                        "then": {"required": ["task_id"]},
                    }
                ],
            },
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="low",
            concurrent=False,
        )
    ]
