from __future__ import annotations

from typing import Any, Mapping

from agent_factory.scheduler_system.schema import SchedulerJob


def scheduler_run_user_config(
    job: SchedulerJob,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(fallback or {})
    captured = dict(job.runtime_config.user_config)
    fallback_overrides = merged.get("model_profile_overrides")
    captured_overrides = captured.get("model_profile_overrides")
    if isinstance(fallback_overrides, Mapping) or isinstance(captured_overrides, Mapping):
        captured["model_profile_overrides"] = {
            **(dict(fallback_overrides) if isinstance(fallback_overrides, Mapping) else {}),
            **(dict(captured_overrides) if isinstance(captured_overrides, Mapping) else {}),
        }
    merged.update(captured)
    return merged


def scheduler_run_max_retries(job: SchedulerJob, fallback: int) -> int:
    return _non_negative_runtime_request_int(job, "max_retries", fallback)


def scheduler_run_timeout_seconds(job: SchedulerJob, fallback: int) -> int:
    return _non_negative_runtime_request_int(job, "timeout_seconds", fallback)


def _non_negative_runtime_request_int(
    job: SchedulerJob,
    key: str,
    fallback: int,
) -> int:
    value = job.runtime_config.runtime_request.get(key)
    if isinstance(value, bool):
        return fallback
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, normalized)
