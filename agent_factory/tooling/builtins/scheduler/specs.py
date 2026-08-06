from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def get_scheduler_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="scheduler",
            description=(
                "Creates, lists, pauses, resumes, deletes, or immediately runs scheduled jobs. Scheduled scripts "
                "and tool calls execute through the AgentFactory tool gateway. When creating a job, set "
                "job.task_content to the user's natural-language intent so completion can be summarized consistently."
            ),
            entrypoint="agent_factory.scheduler_system.tools:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                "scheduler_runtime": "scheduler_runtime",
                "runtime_execution_config": "runtime_execution_config",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.scheduler_system.tools:evaluate_risk",
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "describe", "pause", "resume", "delete", "run_now"],
            },
            "job_id": {"type": "string"},
            "job": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "job_id": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "task_content": {
                        "type": "string",
                        "description": "Original user intent for the scheduled task, used in completion summaries.",
                    },
                    "schedule_type": {
                        "type": "string",
                        "enum": ["cron", "interval", "date"],
                        "description": "cron uses a five-field crontab; interval uses seconds; date uses an ISO datetime.",
                    },
                    "schedule_expr": {
                        "type": "string",
                        "description": (
                            "Schedule expression. cron: five-field crontab; interval: positive integer seconds "
                            "or seconds=<positive integer>; date: ISO datetime. Do not use named units such as "
                            "minutes= or hours=."
                        ),
                    },
                    "timezone": {"type": "string"},
                    "feedback": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "mode": {"type": "string", "enum": ["llm_summary"]},
                        },
                    },
                    "target": _target_schema(),
                    "concurrency_policy": {"type": "string", "enum": ["skip", "queue", "replace"]},
                    "max_concurrent_runs": {"type": "integer", "minimum": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                    "retry_policy": {"type": "object"},
                    "failure_policy": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "max_consecutive_failures": {"type": "integer", "minimum": 1},
                            "action": {"type": "string", "enum": ["pause"]},
                        },
                        "description": "Failure policy; by default the job pauses after the consecutive-failure threshold.",
                    },
                    "unattended_policy": {
                        "type": "string",
                        "enum": ["deny_if_approval_required", "pause_and_wait_for_user", "allow_preapproved_only"],
                    },
                },
                "required": ["schedule_type", "schedule_expr", "target"],
                "allOf": [_interval_schedule_expr_rule()],
            },
        },
        "required": ["action"],
        "oneOf": [
            {"properties": {"action": {"const": "create"}}, "required": ["action", "job"]},
            {"properties": {"action": {"const": "list"}}, "required": ["action"]},
            {"properties": {"action": {"enum": ["describe", "pause", "resume", "delete", "run_now"]}}, "required": ["action", "job_id"]},
        ],
    }


def _interval_schedule_expr_rule() -> dict:
    return {
        "if": {
            "properties": {"schedule_type": {"const": "interval"}},
            "required": ["schedule_type"],
        },
        "then": {
            "properties": {
                "schedule_expr": {
                    "pattern": r"^(seconds=)?[1-9][0-9]*$",
                    "description": "An interval accepts only positive integer seconds or seconds=<positive integer>.",
                }
            }
        },
    }


def _target_schema() -> dict:
    return {
        "oneOf": [
            _graph_run_target_schema(),
            _script_run_target_schema(),
            _tool_call_target_schema(),
        ]
    }


def _graph_run_target_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "target_type": {"const": "graph_run"},
            "payload": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "message": {
                        "type": "string",
                        "minLength": 1,
                        "description": "User message passed to the Agent Graph when the schedule fires.",
                    },
                },
                "required": ["message"],
            },
        },
        "required": ["target_type", "payload"],
    }


def _script_run_target_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "target_type": {"const": "script_run"},
            "payload": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "command": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Command text executed by the current platform shell tool.",
                    },
                    "cwd": {"type": "string"},
                    "mode": {"type": "string", "enum": ["foreground", "background"]},
                    "max_output_chars": {"type": "integer", "minimum": 1, "maximum": 200000},
                },
                "required": ["command"],
            },
        },
        "required": ["target_type", "payload"],
    }


def _tool_call_target_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "target_type": {"const": "tool_call"},
            "payload": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tool_id": {"type": "string", "minLength": 1},
                    "arguments": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Argument object passed to the target tool.",
                    },
                },
                "required": ["tool_id"],
            },
        },
        "required": ["target_type", "payload"],
    }
