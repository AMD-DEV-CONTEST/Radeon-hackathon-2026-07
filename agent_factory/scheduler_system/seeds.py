from __future__ import annotations

import hashlib
import json
from typing import Any

from agent_factory.scheduler_system.runtime import SchedulerRuntime
from agent_factory.scheduler_system.schema import SchedulerJob, SchedulerJobOrigin, SchedulerSeedPlan


def scheduler_seed_hash(seed: SchedulerSeedPlan) -> str:
    payload = seed.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deterministic_seed_job_id(*, package_id: str, seed_id: str) -> str:
    safe_package = _safe_id(package_id or "package")
    safe_seed = _safe_id(seed_id or "seed")
    return f"seed_{safe_package}_{safe_seed}"


def apply_scheduler_seed_contract(
    *,
    runtime: SchedulerRuntime,
    contract_payload: dict[str, Any] | None,
    package_id: str,
) -> list[SchedulerJob]:
    if not contract_payload or not bool(contract_payload.get("enabled", True)):
        return []
    config = contract_payload.get("config") if isinstance(contract_payload.get("config"), dict) else {}
    raw_seeds = config.get("seeds") if isinstance(config, dict) else []
    if not isinstance(raw_seeds, list):
        runtime.emit(
            "scheduler_seed_failed",
            status="failed",
            payload={"package_id": package_id, "error": "scheduler_seed.config.seeds must be a list"},
        )
        return []

    applied: list[SchedulerJob] = []
    for raw_seed in raw_seeds:
        try:
            seed = SchedulerSeedPlan.model_validate(raw_seed)
            runtime.emit(
                "scheduler_seed_detected",
                status="detected",
                payload={"package_id": package_id, "seed_id": seed.seed_id, "title": seed.title},
            )
            job = _apply_seed(runtime=runtime, seed=seed, package_id=package_id)
            applied.append(job)
        except Exception as exc:
            seed_id = raw_seed.get("seed_id") if isinstance(raw_seed, dict) else None
            runtime.emit(
                "scheduler_seed_failed",
                status="failed",
                payload={
                    "package_id": package_id,
                    "seed_id": str(seed_id or ""),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
    return applied


def _apply_seed(*, runtime: SchedulerRuntime, seed: SchedulerSeedPlan, package_id: str) -> SchedulerJob:
    seed_hash = scheduler_seed_hash(seed)
    job_id = deterministic_seed_job_id(package_id=package_id, seed_id=seed.seed_id)
    existing = runtime.store.get_job(job_id)
    if existing is not None and existing.origin is not None and existing.origin.seed_hash == seed_hash:
        runtime.emit(
            "scheduler_seed_unchanged",
            job=existing,
            status="unchanged",
            payload={"package_id": package_id, "seed_id": seed.seed_id, "seed_hash": seed_hash},
        )
        return existing

    job = runtime.upsert_job(
        {
            "job_id": job_id,
            "enabled": bool(seed.enabled_on_apply),
            "schedule_type": seed.schedule_type,
            "schedule_expr": seed.schedule_expr,
            "timezone": seed.timezone,
            "task_content": seed.task_content,
            "target": seed.target.model_dump(mode="json"),
            "feedback": seed.feedback.model_dump(mode="json"),
            "concurrency_policy": seed.concurrency_policy,
            "max_concurrent_runs": seed.max_concurrent_runs,
            "timeout_seconds": seed.timeout_seconds,
            "failure_policy": seed.failure_policy.model_dump(mode="json"),
            "unattended_policy": seed.unattended_policy,
            "origin": SchedulerJobOrigin(
                source_type="package_seed",
                package_id=package_id,
                seed_id=seed.seed_id,
                seed_hash=seed_hash,
            ).model_dump(mode="json"),
        }
    )
    runtime.emit(
        "scheduler_seed_applied",
        job=job,
        status="applied",
        payload={"package_id": package_id, "seed_id": seed.seed_id, "seed_hash": seed_hash},
    )
    return job


def _safe_id(value: str) -> str:
    result = []
    previous_sep = False
    for char in value.lower():
        if char.isalnum() or char in {"_", "-"}:
            result.append(char)
            previous_sep = False
        elif not previous_sep:
            result.append("_")
            previous_sep = True
    text = "".join(result).strip("_-")
    return text or "item"
