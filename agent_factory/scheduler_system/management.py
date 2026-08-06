from __future__ import annotations

from typing import Any, Callable

from agent_factory.scheduler_system.events import SchedulerEventPayload


SchedulerEventEmitter = Callable[[SchedulerEventPayload], None]


def manage_scheduler_runtime(
    *,
    runtime: Any,
    payload: dict[str, Any],
    emit: SchedulerEventEmitter,
    tool_registry: Any | None = None,
    default_limit: int = 20,
) -> None:
    previous_event_sink = getattr(runtime, "event_sink", None)
    runtime.event_sink = emit
    try:
        _manage_scheduler_runtime(
            runtime=runtime,
            payload=payload,
            emit=emit,
            tool_registry=tool_registry,
            default_limit=default_limit,
        )
    finally:
        runtime.event_sink = previous_event_sink


def _manage_scheduler_runtime(
    *,
    runtime: Any,
    payload: dict[str, Any],
    emit: SchedulerEventEmitter,
    tool_registry: Any | None,
    default_limit: int,
) -> None:
    action = str(payload.get("action") or "list").strip()
    job_id = str(payload.get("job_id") or "").strip()
    limit = _bounded_int(payload.get("limit"), default=default_limit, minimum=1, maximum=200)

    if action == "options":
        emit(
            SchedulerEventPayload(
                event_type="scheduler_options_listed",
                owner_type=runtime.owner_type,
                owner_id=runtime.owner_id,
                status="listed",
                payload={"tools": _tool_options(tool_registry)},
            )
        )
        return

    if action == "list":
        jobs = runtime.list_jobs()
        emit(
            SchedulerEventPayload(
                event_type="scheduler_jobs_listed",
                owner_type=runtime.owner_type,
                owner_id=runtime.owner_id,
                status="listed",
                payload={"jobs": [job.model_dump(mode="json") for job in jobs], "count": len(jobs)},
            )
        )
        return

    if action == "create":
        job_payload = payload.get("job") if isinstance(payload.get("job"), dict) else payload
        runtime.create_job(_normalized_scheduler_job_payload(dict(job_payload)))
        return

    if action == "update":
        job_payload = payload.get("job") if isinstance(payload.get("job"), dict) else payload
        runtime.upsert_job(_normalized_scheduler_job_payload(dict(job_payload)))
        return

    if action == "describe":
        if not job_id:
            raise ValueError("scheduler describe requires job_id")
        description = runtime.describe_job(job_id)
        job_payload = description.get("job") if isinstance(description.get("job"), dict) else {}
        target_payload = job_payload.get("target", {}) if isinstance(job_payload, dict) else {}
        emit(
            SchedulerEventPayload(
                event_type="scheduler_job_described",
                job_id=job_id,
                owner_type=runtime.owner_type,
                owner_id=runtime.owner_id,
                target_type=target_payload.get("target_type") if isinstance(target_payload, dict) else None,
                status="described",
                payload=description,
            )
        )
        return

    if action == "runs":
        runs = runtime.store.list_runs(job_id=job_id or None, limit=limit)
        emit(
            SchedulerEventPayload(
                event_type="scheduler_runs_listed",
                job_id=job_id or None,
                owner_type=runtime.owner_type,
                owner_id=runtime.owner_id,
                status="listed",
                payload={"runs": [run.model_dump(mode="json") for run in runs], "count": len(runs), "limit": limit},
            )
        )
        return

    if action == "pause":
        if not job_id:
            raise ValueError("scheduler pause requires job_id")
        runtime.set_job_enabled(job_id, False)
        return

    if action == "resume":
        if not job_id:
            raise ValueError("scheduler resume requires job_id")
        runtime.set_job_enabled(job_id, True)
        return

    if action == "delete":
        if not job_id:
            raise ValueError("scheduler delete requires job_id")
        deleted = runtime.delete_job(job_id)
        if not deleted:
            emit(
                SchedulerEventPayload(
                    event_type="scheduler_job_deleted",
                    job_id=job_id,
                    owner_type=runtime.owner_type,
                    owner_id=runtime.owner_id,
                    status="missing",
                    payload={"deleted": False},
                )
            )
        return

    if action == "run_now":
        if not job_id:
            raise ValueError("scheduler run_now requires job_id")
        runtime.run_now(job_id)
        return

    raise ValueError(f"unsupported scheduler action: {action}")


def _normalized_scheduler_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    target = result.get("target")
    if not isinstance(target, dict):
        raise ValueError("scheduler job requires target")
    normalized_target = dict(target)
    target_payload = normalized_target.get("payload")
    normalized_target["payload"] = dict(target_payload) if isinstance(target_payload, dict) else {}
    result["target"] = normalized_target
    result.pop("owner_type", None)
    result.pop("owner_id", None)
    return result


def _tool_options(tool_registry: Any | None) -> list[dict[str, Any]]:
    if tool_registry is None or not hasattr(tool_registry, "model_tools"):
        return []
    options: list[dict[str, Any]] = []
    for tool in tool_registry.model_tools():
        tool_id = str(getattr(tool, "name", "") or "")
        if not tool_id or tool_id == "scheduler":
            continue
        metadata = getattr(tool, "metadata", None)
        agent_factory = metadata.get("agent_factory", {}) if isinstance(metadata, dict) else {}
        options.append(
            {
                "id": tool_id,
                "name": tool_id,
                "description": str(getattr(tool, "description", "") or ""),
                "risk_level": str(agent_factory.get("risk_level") or "low"),
                "input_schema": _tool_input_schema(tool),
            }
        )
    return options


def _tool_input_schema(tool: Any) -> dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if isinstance(args_schema, dict):
        return args_schema
    if hasattr(args_schema, "model_json_schema"):
        schema = args_schema.model_json_schema()
        return schema if isinstance(schema, dict) else {}
    if hasattr(args_schema, "schema"):
        schema = args_schema.schema()
        return schema if isinstance(schema, dict) else {}
    return {}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
