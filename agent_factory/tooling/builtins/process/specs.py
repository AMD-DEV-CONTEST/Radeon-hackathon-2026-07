from __future__ import annotations

from agent_factory.tooling.builtins.process.runtime import host_shell_display_name
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_PROCESS_RESOURCE = {"process_runtime": "process_runtime"}
_PROCESS_MODULE = "agent_factory.tooling.builtins.process"
_CWD_BOUNDARY_DESCRIPTION = (
    "Optional working directory. The default '.' is the current session workspace root, so callers normally "
    "do not need cwd or an initial cd command. Use relative paths for workspace files. When cwd is supplied, "
    "prefer a relative subdirectory inside the workspace. Do not use file-tool sandbox aliases, /tmp, host "
    "paths, or arbitrary absolute paths unless the runtime explicitly allows external paths."
)

_PROCESS_STATUS_VALUES = ["running", "completed", "failed", "stopped"]
_PROCESS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "process_id": _STRING,
        "status": {"type": "string", "enum": _PROCESS_STATUS_VALUES},
        "command": _STRING,
        "shell": _STRING,
        "shell_executable": _STRING,
        "cwd": _STRING,
        "exit_code": {"type": ["integer", "null"]},
        "stdout": _STRING,
        "stderr": _STRING,
        "stdout_truncated": _BOOLEAN,
        "stderr_truncated": _BOOLEAN,
        "duration_ms": _INTEGER,
    },
    "required": [
        "process_id",
        "status",
        "command",
        "shell",
        "shell_executable",
        "cwd",
        "exit_code",
        "stdout",
        "stderr",
        "stdout_truncated",
        "stderr_truncated",
        "duration_ms",
    ],
    "additionalProperties": False,
}


PROCESS_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="shell",
        description=(
            f"Runs a command through the current platform's {host_shell_display_name()} inside the workspace "
            "boundary. The child process starts at the session workspace root, so use relative paths without "
            "an initial cd. foreground continuously returns stdout/stderr and waits for the final state, so one "
            "call provides the complete result. Use background only for long-running services or listeners that "
            "must outlive the current turn."
        ),
        entrypoint="agent_factory.tooling.builtins.process.shell:run",
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        f"Command text for the current platform's {host_shell_display_name()}."
                    ),
                },
                "cwd": {"type": "string", "default": ".", "description": _CWD_BOUNDARY_DESCRIPTION},
                "mode": {
                    "type": "string",
                    "enum": ["foreground", "background"],
                    "default": "foreground",
                    "description": (
                        "Use foreground for ordinary commands; it waits until completed, failed, or stopped, so "
                        "shell_status is unnecessary. Use background only for long-running work that must persist "
                        "across turns; background returns a process_id immediately."
                    ),
                },
                "max_output_chars": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200000,
                    "default": 12000,
                    "description": "Maximum number of trailing stdout/stderr characters returned in this call.",
                },
                "fallback_reason": {
                    "type": "string",
                    "description": (
                        "Required from an executor node: explain why available package/runtime tools cannot "
                        "complete this plan step and why platform shell fallback is necessary."
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        output_schema=_PROCESS_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        risk_level="high",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_PROCESS_MODULE}.shell:evaluate_risk"),
        concurrent=False,
    ),
    ToolSpec(
        id="shell_status",
        description=(
            "Reads status and collected output for a process started by shell in background mode. Do not call "
            "it for foreground commands, which stream output and return their final state in the original call."
        ),
        entrypoint="agent_factory.tooling.builtins.process.shell_status:run",
        input_schema={
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "description": "process_id returned by shell."},
                "max_output_chars": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200000,
                    "default": 12000,
                    "description": "Maximum number of trailing stdout/stderr characters returned in this call.",
                },
            },
            "required": ["process_id"],
            "additionalProperties": False,
        },
        output_schema=_PROCESS_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_PROCESS_MODULE}.shell_status:evaluate_risk"),
        concurrent=True,
    ),
    ToolSpec(
        id="shell_stop",
        description="Terminates a process tree started by shell and returns its final state and output.",
        entrypoint="agent_factory.tooling.builtins.process.shell_stop:run",
        input_schema={
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "description": "process_id returned by shell."},
                "grace_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 300,
                    "default": 2,
                    "description": "Seconds to wait after requesting termination before forcing the process tree to stop.",
                },
                "max_output_chars": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200000,
                    "default": 12000,
                    "description": "Maximum number of trailing stdout/stderr characters returned in this call.",
                },
            },
            "required": ["process_id"],
            "additionalProperties": False,
        },
        output_schema=_PROCESS_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_PROCESS_MODULE}.shell_stop:evaluate_risk"),
        concurrent=False,
    ),
]


def get_process_tool_specs() -> list[ToolSpec]:
    return [tool.model_copy(deep=True) for tool in PROCESS_TOOL_SPECS]
