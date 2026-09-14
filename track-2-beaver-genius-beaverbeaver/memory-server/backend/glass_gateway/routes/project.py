from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from glass_gateway.config import get_settings
from glass_gateway.services.project_tracker import ProjectTrackerStore


router = APIRouter()


class MilestoneUpdateRequest(BaseModel):
    status: Literal["completed", "in_progress", "at_risk", "planned", "blocked"] | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    owner: str | None = Field(default=None, max_length=80)
    target_date: str | None = Field(default=None, max_length=20)
    summary: str | None = Field(default=None, max_length=500)
    priority: Literal["high", "medium", "low"] | None = None
    author: str = Field(default="项目组", max_length=80)
    note: str | None = Field(default=None, max_length=1000)


class ProgressUpdateRequest(BaseModel):
    author: str = Field(default="项目组", max_length=80)
    type: Literal["project", "milestone", "risk"] = "project"
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=2000)
    milestone_id: str | None = Field(default=None, max_length=80)


@lru_cache
def _store() -> ProjectTrackerStore:
    settings = get_settings()
    path = Path(settings.project_tracker_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return ProjectTrackerStore(path)


def _require_write_token(token: str | None) -> None:
    expected = get_settings().pm_write_token
    if not token or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid PM write token")


@router.get("/v1/project")
async def get_project() -> dict[str, Any]:
    return _store().snapshot()


@router.patch("/v1/project/milestones/{milestone_id}")
async def update_milestone(
    milestone_id: str,
    request: MilestoneUpdateRequest,
    x_pm_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_write_token(x_pm_token)
    changes = request.model_dump(exclude={"author", "note"}, exclude_none=True)
    try:
        return _store().update_milestone(
            milestone_id,
            changes,
            author=request.author,
            note=request.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="milestone not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/v1/project/updates", status_code=status.HTTP_201_CREATED)
async def add_progress_update(
    request: ProgressUpdateRequest,
    x_pm_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_write_token(x_pm_token)
    return _store().add_update(request.model_dump())
