from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_MANUFACTURE_TOOL_ID = "agent_manufacture"


def get_agent_manufacture_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_MANUFACTURE_TOOL_ID,
            description=(
                "Asynchronously manufactures and publishes a new Agent. Use only when agent_search returns "
                "no reusable candidate and existing Agents cannot complete the task. The tool registers a "
                "request with the host manufacturing service without blocking the conversation. After start, "
                "briefly summarize the manufacturing goal to the user, end the response, and do not query "
                "progress. A package that passes full_static is automatically published and reported back "
                "to the primary Agent session. After completion, call agent_search again to confirm the usable package_id."
            ),
            entrypoint="agent_factory.tooling.builtins.agent_manufacture.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "agent_name": {"type": "string", "description": "Requested name for the new Agent."},
                    "purpose": {"type": "string", "description": "Clear purpose of the new Agent."},
                    "target_tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Task types the new Agent must handle.",
                    },
                    "delivery_standards": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Testable delivery standards.",
                    },
                    "reason_existing_agents_insufficient": {
                        "type": "string",
                        "description": "Specific reason existing Agents are insufficient, derived from agent_search results.",
                    },
                    "preferred_pattern": {
                        "type": "string",
                        "enum": ["react_agent", "plan_and_execute"],
                        "description": "Preferred runtime pattern.",
                    },
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Boundaries, constraints, or prohibited behavior.",
                    },
                    "source_agent_search": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Summary of the prerequisite agent_search, including query, status, and why candidates were insufficient.",
                    },
                },
                "required": [
                    "agent_name",
                    "purpose",
                    "delivery_standards",
                    "reason_existing_agents_insufficient",
                ],
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "queued",
                            "claimed",
                            "running",
                            "waiting_approval",
                            "waiting_external",
                            "cancelling",
                            "succeeded",
                            "failed",
                            "cancelled"
                        ],
                    },
                    "request_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "create_agent_session_id": {"type": ["string", "null"]},
                    "message": {"type": "string"},
                    "next_step": {"type": "string"},
                },
                "required": [
                    "status",
                    "request_id",
                    "task_id",
                    "message",
                    "next_step"
                ],
            },
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_manufacture.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]
