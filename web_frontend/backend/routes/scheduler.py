from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import optional_package, request_id, resource_command


def create_scheduler_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/scheduler")

    @router.get("/jobs")
    async def scheduler_jobs(package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "scheduler_manage",
            {"action": "list", **optional_package(package_id)},
            {"scheduler_jobs_listed"},
        )
        return {"event": event}

    @router.get("/options")
    async def scheduler_options(package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "scheduler_manage",
            {"action": "options", **optional_package(package_id)},
            {"scheduler_options_listed"},
        )
        return {"event": event}

    @router.post("/jobs")
    async def create_scheduler_job(payload: dict[str, Any]):
        package_id = payload.get("package_id")
        job_payload = payload.get("job") if isinstance(payload.get("job"), dict) else {
            key: value for key, value in payload.items() if key != "package_id"
        }
        event = await resource_command(
            runtime_bridge,
            "scheduler_manage",
            {"action": "create", "job": job_payload, **optional_package(package_id)},
            {"scheduler_job_created"},
        )
        return {"event": event}

    @router.get("/jobs/{job_id}")
    async def describe_scheduler_job(job_id: str, package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "scheduler_manage",
            {"action": "describe", "job_id": job_id, **optional_package(package_id)},
            {"scheduler_job_described"},
        )
        return {"event": event}

    @router.get("/runs")
    async def scheduler_runs(
        job_id: str | None = None,
        package_id: str | None = None,
        limit: int = Query(default=20, ge=1, le=200),
    ):
        payload: dict[str, Any] = {"action": "runs", "limit": limit, **optional_package(package_id)}
        if job_id:
            payload["job_id"] = job_id
        event = await resource_command(runtime_bridge, "scheduler_manage", payload, {"scheduler_runs_listed"})
        return {"event": event}

    @router.post("/jobs/{job_id}/pause")
    async def pause_scheduler_job(job_id: str, payload: dict[str, Any] | None = None):
        event = await resource_command(
            runtime_bridge,
            "scheduler_manage",
            {"action": "pause", "job_id": job_id, **optional_package((payload or {}).get("package_id"))},
            {"scheduler_job_updated"},
        )
        return {"event": event}

    @router.post("/jobs/{job_id}/resume")
    async def resume_scheduler_job(job_id: str, payload: dict[str, Any] | None = None):
        event = await resource_command(
            runtime_bridge,
            "scheduler_manage",
            {"action": "resume", "job_id": job_id, **optional_package((payload or {}).get("package_id"))},
            {"scheduler_job_updated"},
        )
        return {"event": event}

    @router.delete("/jobs/{job_id}")
    async def delete_scheduler_job(job_id: str, package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "scheduler_manage",
            {"action": "delete", "job_id": job_id, **optional_package(package_id)},
            {"scheduler_job_deleted"},
        )
        return {"event": event}

    @router.post("/jobs/{job_id}/run")
    async def run_scheduler_job_now(job_id: str, payload: dict[str, Any] | None = None):
        command = FactoryFrontendCommand(
            type="scheduler_manage",
            request_id=request_id(),
            payload={"action": "run_now", "job_id": job_id, **optional_package((payload or {}).get("package_id"))},
        )
        await runtime_bridge.send_frontend_command(command)
        return {"accepted": True, "command": command.model_dump(mode="json")}

    return router
