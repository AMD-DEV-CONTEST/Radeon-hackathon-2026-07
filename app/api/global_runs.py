"""Global runs list — cross‑project run history (Stage E)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.schemas import RunState
from app.services.runs import list_all_runs
from app.security.permissions import get_project_api_user, get_project_role, has_min_role

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("", response_model=list[RunState])
def list_all(request: Request, user: dict | None = Depends(get_project_api_user)) -> list[RunState]:
    """Return all runs across all projects, newest first (global history).

    This endpoint powers the ``/runs`` frontend dashboard.
    """
    runs = list_all_runs(request.app.state.settings)
    if not request.app.state.settings.enforce_project_authorization:
        return runs
    assert user is not None
    return [
        run for run in runs
        if has_min_role(get_project_role(request.app.state.db_path, run.project_id, user["user_id"]), "guest")
    ]
