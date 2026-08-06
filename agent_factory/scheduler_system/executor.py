from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from agent_factory.scheduler_system.schema import SchedulerExecutionReport, SchedulerJob, SchedulerRun
from agent_factory.tooling.execution_context import tool_approval_override
from agent_factory.runtime_kernel.state import RuntimeState


SchedulerGraphRunner = Callable[[SchedulerJob, SchedulerRun], dict[str, Any]]
SchedulerToolRunner = Callable[[str, dict[str, Any], SchedulerJob, SchedulerRun], dict[str, Any]]


class SchedulerExecutor:
    def __init__(
        self,
        *,
        graph_runner: SchedulerGraphRunner | None = None,
        tool_runner: SchedulerToolRunner | None = None,
    ) -> None:
        self.graph_runner = graph_runner
        self.tool_runner = tool_runner

    def execute(self, *, job: SchedulerJob, run: SchedulerRun) -> SchedulerExecutionReport:
        started = _now()
        try:
            if job.target.target_type == "graph_run":
                output = self._execute_graph(job, run)
            elif job.target.target_type == "script_run":
                output = self._execute_script(job, run)
            else:
                output = self._execute_tool(job, run)
            status = "completed" if str(output.get("status") or "completed") == "completed" else "failed"
            error_summary = _error_summary(status=status, evidence=output)
            return self._report(
                job=job,
                run=run,
                started=started,
                status=status,
                output_summary=_output_summary(output),
                error_summary=error_summary,
                evidence=_execution_evidence(job=job, run=run, output=output),
            )
        except Exception as exc:
            return self._report(
                job=job,
                run=run,
                started=started,
                status="failed",
                error_summary=f"{type(exc).__name__}: {exc}",
                evidence=_execution_evidence(job=job, run=run, exception=exc),
            )

    def _execute_graph(self, job: SchedulerJob, run: SchedulerRun) -> dict[str, Any]:
        if self.graph_runner is None:
            raise RuntimeError("scheduler graph_run target is not configured for this runtime")
        return self.graph_runner(job, run)

    def _execute_script(self, job: SchedulerJob, run: SchedulerRun) -> dict[str, Any]:
        payload = job.target.payload
        command = payload.get("command")
        if self.tool_runner is None:
            raise RuntimeError("scheduler script_run target requires a tool runner")
        return self.tool_runner("shell", {"command": command, **_optional_tool_args(payload)}, job, run)

    def _execute_tool(self, job: SchedulerJob, run: SchedulerRun) -> dict[str, Any]:
        payload = job.target.payload
        tool_id = str(payload.get("tool_id") or "")
        arguments = dict(payload.get("arguments") or {})
        if self.tool_runner is None:
            raise RuntimeError("scheduler tool_call target requires a tool runner")
        return self.tool_runner(tool_id, arguments, job, run)

    def _report(
        self,
        *,
        job: SchedulerJob,
        run: SchedulerRun,
        started: datetime,
        status: str,
        output_summary: str | None = None,
        error_summary: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> SchedulerExecutionReport:
        completed = _now()
        duration_ms = int((completed - started).total_seconds() * 1000)
        evidence = evidence or {}
        return SchedulerExecutionReport(
            run_id=run.run_id,
            job_id=job.job_id,
            owner_type=job.owner_type,
            owner_id=job.owner_id,
            target_type=job.target.target_type,
            status=status,  # type: ignore[arg-type]
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            duration_ms=duration_ms,
            output_summary=output_summary,
            error_summary=error_summary,
            stdout_preview=_stdout_preview(evidence),
            stderr_preview=_stderr_preview(evidence),
            exit_code=_exit_code(evidence),
            evidence=evidence,
        )


def runtime_tool_runner(registry: Any) -> SchedulerToolRunner:
    def run(tool_id: str, arguments: dict[str, Any], job: SchedulerJob, run_record: SchedulerRun) -> dict[str, Any]:
        state = RuntimeState()
        state.run.agent_id = job.owner_id
        state.run.run_id = run_record.run_id
        state.runtime_config.agent_config["triggered_by"] = "scheduler"
        state.runtime_config.agent_config["scheduler_job_id"] = job.job_id
        with scheduler_tool_approval_override(job=job, tool_id=tool_id):
            result = registry.execute(tool_id, arguments, state=state)
        output = result.output if isinstance(result.output, dict) else {"value": result.output}
        return {
            "status": result.status,
            "error": result.error,
            "observation_summary": result.observation_summary,
            **(output or {}),
        }

    return run


def scheduler_tool_approval_override(*, job: SchedulerJob, tool_id: str):
    return tool_approval_override(
        reason=(
            f"scheduler job {job.job_id} was approved at creation time; "
            f"skip human approval interrupt for scheduled tool {tool_id}"
        )
    )


def _optional_tool_args(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("cwd", "mode", "max_output_chars"):
        if key in payload:
            result[key] = payload[key]
    return result


def _execution_evidence(
    *,
    job: SchedulerJob,
    run: SchedulerRun,
    output: dict[str, Any] | None = None,
    exception: Exception | None = None,
) -> dict[str, Any]:
    output = output or {}
    return {
        "job": _job_evidence(job),
        "run": _run_evidence(run),
        "target": _target_evidence(job),
        "execution": _execution_summary(output=output, exception=exception),
    }


def _job_evidence(job: SchedulerJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "owner_type": job.owner_type,
        "owner_id": job.owner_id,
        "schedule_type": job.schedule_type,
        "schedule_expr": _summary(job.schedule_expr, limit=120),
        "timezone": job.timezone,
        "task_content_preview": _summary(job.task_content, limit=240),
    }


def _run_evidence(run: SchedulerRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "trigger_reason": run.trigger_reason,
        "scheduled_at": run.scheduled_at,
    }


def _target_evidence(job: SchedulerJob) -> dict[str, Any]:
    target = job.target
    payload = dict(target.payload or {})
    if target.target_type == "script_run":
        command = payload.get("command")
        return {
            "target_type": target.target_type,
            "tool_id": "shell",
            "command_preview": _command_preview(command),
            "option_keys": sorted(key for key in payload if key != "command"),
        }
    if target.target_type == "tool_call":
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        return {
            "target_type": target.target_type,
            "tool_id": _summary(payload.get("tool_id"), limit=120),
            "argument_keys": sorted(str(key) for key in arguments),
            "argument_shape": _shape_preview(arguments),
        }
    return {
        "target_type": target.target_type,
        "message_preview": _summary(payload.get("message"), limit=360),
    }


def _execution_summary(*, output: dict[str, Any], exception: Exception | None) -> dict[str, Any]:
    if exception is not None:
        return {
            "status": "failed",
            "failure_phase": "target_execution",
            "error_type": type(exception).__name__,
            "error_summary": _summary(str(exception), limit=500),
        }
    return {
        "status": _summary(output.get("status"), limit=80) or "completed",
        "request_id": _summary(output.get("request_id"), limit=120),
        "target_scope": _summary(output.get("target_scope"), limit=80),
        "package_id": _summary(output.get("package_id"), limit=160),
        "package_name": _summary(output.get("package_name"), limit=200),
        "agent_session": output.get("agent_session") if isinstance(output.get("agent_session"), dict) else None,
        "conversation": output.get("conversation") if isinstance(output.get("conversation"), dict) else None,
        "message": _summary(output.get("message"), limit=500),
        "error": _summary(_result_value(output, "error"), limit=500),
        "error_summary": _summary(_result_value(output, "error_summary"), limit=500),
        "observation_summary": _summary(_result_value(output, "observation_summary"), limit=500),
        "output_summary": _output_summary(output),
        "stdout_preview": _stdout_preview(output),
        "stderr_preview": _stderr_preview(output),
        "exit_code": _exit_code(output),
        "result_keys": _result_keys(output),
    }


def _command_preview(command: Any) -> str | None:
    if isinstance(command, str):
        return _summary(command, limit=500)
    return _summary(command, limit=500)


def _shape_preview(value: dict[str, Any]) -> dict[str, str]:
    return {str(key): type(item).__name__ for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:32]}


def _result_keys(output: dict[str, Any]) -> list[str]:
    keys = set(str(key) for key in output)
    nested = _output_payload(output)
    keys.update(f"output.{key}" for key in nested)
    return sorted(keys)


def _now() -> datetime:
    return datetime.now(UTC)


def _summary(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit]}..."


def _output_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    output = evidence.get("output")
    return output if isinstance(output, dict) else {}


def _result_value(evidence: dict[str, Any], key: str) -> Any:
    if key in evidence:
        return evidence[key]
    execution = evidence.get("execution")
    if isinstance(execution, dict):
        if key in execution:
            return execution[key]
        preview_key = f"{key}_preview"
        if preview_key in execution:
            return execution[preview_key]
    return _output_payload(evidence).get(key)


def _stdout_preview(evidence: dict[str, Any]) -> str | None:
    return _summary(_result_value(evidence, "stdout"))


def _stderr_preview(evidence: dict[str, Any]) -> str | None:
    return _summary(_result_value(evidence, "stderr"))


def _output_summary(evidence: dict[str, Any]) -> str | None:
    stdout = _stdout_preview(evidence)
    if stdout:
        return stdout
    for key in ("output_summary", "final_answer", "summary", "message"):
        summary = _summary(_result_value(evidence, key))
        if summary:
            return summary
    return None


def _error_summary(*, status: str, evidence: dict[str, Any]) -> str | None:
    if status == "completed":
        return None
    for key in ("error", "error_summary"):
        summary = _summary(_result_value(evidence, key))
        if summary:
            return summary
    stderr = _stderr_preview(evidence)
    if stderr:
        return stderr
    for key in ("observation_summary", "message"):
        summary = _summary(_result_value(evidence, key))
        if summary:
            return summary
    return None


def _exit_code(evidence: dict[str, Any]) -> int | None:
    value = _result_value(evidence, "exit_code")
    if isinstance(value, int):
        return value
    return None
