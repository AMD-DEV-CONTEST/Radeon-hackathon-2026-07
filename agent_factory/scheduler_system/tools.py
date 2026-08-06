from __future__ import annotations

from typing import Any

from agent_factory.scheduler_system.runtime import SchedulerRuntime
from agent_factory.tooling.envelope import tool_envelope, tool_failure


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get("scheduler_runtime")
    if not isinstance(runtime, SchedulerRuntime):
        return tool_failure(
            "scheduler runtime is not configured",
            output={"status": "failed"},
        )
    action = str(arguments.get("action") or "").strip()
    if action == "create":
        job = runtime.create_job(_job_payload(arguments, resources))
        return tool_envelope({"status": "completed", "job": job.model_dump(mode="json")})
    if action == "list":
        jobs = runtime.list_jobs()
        return tool_envelope({"status": "completed", "jobs": [job.model_dump(mode="json") for job in jobs]})
    if action == "describe":
        return tool_envelope({"status": "completed", **runtime.describe_job(_job_id(arguments))})
    if action == "pause":
        job = runtime.set_job_enabled(_job_id(arguments), False)
        return tool_envelope({"status": "completed", "job": job.model_dump(mode="json")})
    if action == "resume":
        job = runtime.set_job_enabled(_job_id(arguments), True)
        return tool_envelope({"status": "completed", "job": job.model_dump(mode="json")})
    if action == "delete":
        return tool_envelope({"status": "completed", "deleted": runtime.delete_job(_job_id(arguments))})
    if action == "run_now":
        report = runtime.run_now(_job_id(arguments))
        output = {"status": report.status, "report": report.model_dump(mode="json")}
        if report.status == "failed":
            error = report.error_summary or "scheduled job failed"
            return tool_failure(error, output=output)
        return tool_envelope(output)
    error = f"unsupported scheduler action: {action}"
    return tool_failure(error, output={"status": "failed"})


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"list", "describe"}:
        return {"action": "allow", "risk_level": "low", "reasons": ["read-only scheduler action"]}
    if action in {"create", "pause", "resume", "delete", "run_now"}:
        return {"action": "ask", "risk_level": "medium", "reasons": [f"scheduler action requires review: {action}"]}
    return {"action": "deny", "risk_level": "medium", "reasons": [f"unknown scheduler action: {action}"]}


def _job_id(arguments: dict[str, Any]) -> str:
    job_id = str(arguments.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("scheduler action requires job_id")
    return job_id


def _job_payload(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    job = arguments.get("job")
    if not isinstance(job, dict):
        raise ValueError("scheduler create action requires job object")
    payload = dict(job)
    if "runtime_config" not in payload:
        runtime_config = resources.get("runtime_execution_config")
        if isinstance(runtime_config, dict):
            payload["runtime_config"] = _persistable_runtime_config(runtime_config)
    return payload


def _persistable_runtime_config(runtime_config: dict[str, Any]) -> dict[str, Any]:
    user_config = runtime_config.get("user_config")
    runtime_request = runtime_config.get("runtime_request")
    safe_user_config = {}
    if isinstance(user_config, dict):
        for key in ("model_profile_overrides", "reasoning_intensity"):
            if key in user_config:
                safe_user_config[key] = user_config[key]
    safe_runtime_request = {}
    if isinstance(runtime_request, dict):
        for key in ("timeout_seconds", "max_retries"):
            if key in runtime_request:
                safe_runtime_request[key] = runtime_request[key]
    return {
        "user_config": safe_user_config,
        "runtime_request": safe_runtime_request,
    }
