from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.collaboration_system.task_runtime import background_task_service
from agent_factory.collaboration_system.interactions import public_task_payload
from agent_factory.contracts import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    ConflictError,
    DomainError,
    DomainValidationError,
    NotFoundError,
    ServiceUnavailableError,
)


class SchedulerSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_parallel_sub_agents: int = Field(ge=1, le=128)
    revision: int | None = Field(default=None, ge=0)


class TaskCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="user_cancelled", min_length=1, max_length=256)


class TaskInteractionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "deny", "trust_tool", "revise", "answer", "continue"]
    payload: dict[str, Any] = Field(default_factory=dict)


def create_background_task_router() -> APIRouter:
    router = APIRouter(prefix="/api/background-tasks")

    @router.get("")
    def list_tasks(
        session_id: str | None = None,
        type: BackgroundTaskType | None = None,
        status: list[BackgroundTaskStatus] | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        try:
            tasks = background_task_service().list(
                session_id=session_id,
                type=type,
                statuses=status,
                limit=limit,
                offset=offset,
            )
            return {"tasks": [public_task_payload(task) for task in tasks]}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/settings")
    def scheduler_settings():
        try:
            return {"settings": background_task_service().scheduler_settings()}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.patch("/settings")
    def update_scheduler_settings(payload: SchedulerSettingsUpdate):
        try:
            return {
                "settings": background_task_service().configure_max_parallel_sub_agents(
                    payload.max_parallel_sub_agents,
                    expected_revision=payload.revision,
                )
            }
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/{task_id}")
    def get_task(task_id: str):
        try:
            return {"task": public_task_payload(background_task_service().get(task_id))}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/{task_id}/events")
    def task_events(
        task_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=5000),
    ):
        try:
            service = background_task_service()
            service.get(task_id)
            events = service.events.list_task_timeline_after(
                task_id,
                after_seq=after,
                limit=limit,
            )
            return {"events": [event.model_dump(mode="json") for event in events]}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/{task_id}/cancel")
    def cancel_task(task_id: str, payload: TaskCancelRequest | None = None):
        try:
            reason = payload.reason if payload is not None else "user_cancelled"
            task = background_task_service().cancel(task_id, reason=reason)
            return {"task": public_task_payload(task)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/{task_id}/interactions/{interaction_id}/resolve")
    def resolve_interaction(task_id: str, interaction_id: str, payload: TaskInteractionResolution):
        try:
            task = background_task_service().resolve_interaction(
                task_id,
                interaction_id=interaction_id,
                action=payload.action,
                payload=payload.payload,
            )
            return {"task": public_task_payload(task)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.delete("/{task_id}")
    def delete_task(task_id: str):
        try:
            task = background_task_service().delete_task(task_id)
            return {"task": public_task_payload(task), "deleted": True}
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


def _http_error(exc: Exception) -> HTTPException:
    status = 500
    if isinstance(exc, NotFoundError):
        status = 404
    elif isinstance(exc, ConflictError):
        status = 409
    elif isinstance(exc, DomainValidationError):
        status = 422
    elif isinstance(exc, ServiceUnavailableError):
        status = 503
    detail = exc.as_dict() if isinstance(exc, DomainError) else {
        "code": "internal_error",
        "message": "后台任务操作失败。",
    }
    return HTTPException(status_code=status, detail=detail)
