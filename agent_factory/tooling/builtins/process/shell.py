from __future__ import annotations

from typing import Any

from agent_factory.tooling.builtins.process.manager import (
    PROCESS_MANAGER,
    ProcessCancellationCheck,
    ProcessOutputObserver,
    is_read_only_process_path,
    output_limit,
    process_runtime_allowed_roots,
    process_runtime_boundary,
    required_string,
    resolve_cwd,
)
from agent_factory.tooling.builtins.process.runtime import resolve_shell_runtime
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.execution_context import (
    current_runtime_run_control,
    current_tool_call,
    current_tool_event_sink,
)
from agent_factory.tooling.executor_fallback import executor_fallback_risk
from agent_factory.tooling.risk import merge_risk_results
from agent_factory.tooling.spec import ToolRiskResult


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=["shell command must be a non-empty string"],
        ).model_dump(mode="json")
    cwd_result = _evaluate_cwd(arguments, context)
    if cwd_result.action == "deny":
        return cwd_result.model_dump(mode="json")
    try:
        shell_runtime = resolve_shell_runtime()
        analysis = shell_runtime.analyze(command)
    except (RuntimeError, ValueError) as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[f"shell command cannot be evaluated safely: {exc}"],
            facts=dict(cwd_result.facts),
        ).model_dump(mode="json")
    facts = {
        **cwd_result.facts,
        "shell": shell_runtime.shell_id,
        "shell_executable": str(shell_runtime.executable),
        "command_binary": analysis.command_binary,
        "contains_shell_control": analysis.contains_shell_control,
    }
    reasons = [
        f"shell executes through {shell_runtime.display_name} and requires approval",
    ]
    if analysis.high_risk_binary:
        reasons.append(f"command starts with a high-risk executable: {analysis.command_binary}")
    if analysis.contains_shell_control:
        reasons.append("command contains shell control structure")
    command_risk = ToolRiskResult(
        action="ask",
        risk_level="high",
        reasons=reasons,
        facts=facts,
    )
    fallback_risk = executor_fallback_risk(arguments, context)
    risks = [command_risk, *([fallback_risk] if fallback_risk is not None else [])]
    return merge_risk_results(risks, base_risk_level="high").model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    command = required_string(arguments, "command")
    mode = str(arguments.get("mode", "foreground")).strip()
    if mode not in {"foreground", "background"}:
        raise ValueError("mode must be foreground or background")
    root, allow_external = process_runtime_boundary(resources)
    cwd = resolve_cwd(
        cwd=arguments.get("cwd"),
        root=root,
        allow_external=allow_external,
        allowed_roots=process_runtime_allowed_roots(resources),
    )
    if not cwd.exists():
        raise FileNotFoundError(str(cwd))
    if not cwd.is_dir():
        raise NotADirectoryError(str(cwd))
    if is_read_only_process_path(cwd, root=root, resources=resources):
        raise PermissionError(f"cwd is read-only runtime input: {cwd}")
    output_observer = _output_observer()
    return tool_envelope(
        PROCESS_MANAGER.start(
            command=command,
            cwd=cwd,
            mode=mode,
            max_output_chars=output_limit(arguments),
            on_output=output_observer,
            cancellation_requested=_cancellation_check() if mode == "foreground" else None,
        )
    )


def _output_observer() -> ProcessOutputObserver | None:
    current = current_tool_call()
    sink = current_tool_event_sink()
    if current is None or sink is None:
        return None

    def publish(output: dict[str, Any]) -> None:
        sink(
            {
                "event_type": "tool_output_delta",
                "tool_id": current.tool_id,
                "tool_call_id": current.tool_call_id,
                "status": "running",
                "output": output,
                "message": "Command output updated.",
            }
        )

    return publish


def _cancellation_check() -> ProcessCancellationCheck | None:
    control = current_runtime_run_control()
    if control is None:
        return None

    def requested() -> bool:
        return bool(getattr(control, "drain_requested", False))

    return requested


def _evaluate_cwd(arguments: dict[str, Any], context: dict[str, Any]) -> ToolRiskResult:
    tool_resources = dict(context.get("resources") or {})
    root, allow_external = process_runtime_boundary(tool_resources)
    try:
        cwd = resolve_cwd(
            cwd=arguments.get("cwd"),
            root=root,
            allow_external=allow_external,
            allowed_roots=process_runtime_allowed_roots(tool_resources),
        )
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[
                f"cwd is outside the configured process runtime boundary: {exc}",
                _process_workspace_guidance(root),
            ],
            facts={"process_root": str(root)},
        )
    if is_read_only_process_path(cwd, root=root, resources=tool_resources):
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=["cwd is read-only runtime input and cannot be used as a process working directory"],
            facts={
                "cwd": str(cwd),
                "process_root": str(root),
                "read_only_runtime_input": True,
            },
        )
    return ToolRiskResult(
        action="inherit",
        facts={
            "cwd": str(cwd),
            "process_root": str(root),
        },
    )


def _process_workspace_guidance(root: Any) -> str:
    return (
        "Use a relative cwd inside the workspace or an absolute cwd under "
        f"process root {root}; do not use temporary directories, host paths, or arbitrary absolute "
        "paths unless external paths are explicitly enabled."
    )
