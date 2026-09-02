from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from app.observability.error_codes import get_error
from app.schemas import RunProgress, RunState
from app.services.projects import ProjectNotFoundError
from app.services.runs import (
    RunAlreadyExecutedError,
    RunCancelTooLateError,
    RunNotFoundError,
    RunWrongStatusError,
    build_progress,
    cancel_run,
    create_run,
    dispatch_background_run,
    get_run,
    list_runs,
    retry_run,
)
from app.security.paths import ensure_project_path
from app.security.permissions import require_project_api_role


router = APIRouter(
    prefix="/api/projects/{project_id}/runs",
    tags=["runs"],
    dependencies=[Depends(require_project_api_role("guest"))],
)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=RunState, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_project_api_role("member"))])
def create(project_id: str, request: Request) -> RunState:
    try:
        return create_run(request.app.state.settings, project_id)
    except ValueError as error:
        err = get_error("PROJECT_ID_INVALID")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err) from error
    except ProjectNotFoundError as error:
        err = get_error("PROJECT_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error


@router.get("/{run_id}", response_model=RunState)
def get(project_id: str, run_id: str, request: Request) -> RunState:
    try:
        return get_run(request.app.state.settings, project_id, run_id)
    except ValueError as error:
        err = get_error("VALIDATION_ERROR")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err) from error
    except RunNotFoundError as error:
        err = get_error("RUN_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error


@router.get("", response_model=list[RunState])
def list_project_runs(project_id: str, request: Request) -> list[RunState]:
    """List all runs for a project, newest first."""
    try:
        return list_runs(request.app.state.settings, project_id)
    except ValueError as error:
        err = get_error("PROJECT_ID_INVALID")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err) from error


# ---------------------------------------------------------------------------
# Background execution (Stage E)
# ---------------------------------------------------------------------------


@router.post("/{run_id}/execute", response_model=RunState, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_project_api_role("member"))])
async def execute(project_id: str, run_id: str, request: Request) -> RunState:
    """Kick off background execution. Returns the queued RunState immediately."""
    try:
        state = get_run(request.app.state.settings, project_id, run_id)
    except RunNotFoundError as error:
        err = get_error("RUN_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error

    try:
        dispatch_background_run(request.app.state.settings, project_id, run_id)
    except RunAlreadyExecutedError as error:
        err = get_error("RUN_ALREADY_EXECUTED")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err) from error
    except ValueError as error:
        err = get_error("VALIDATION_ERROR")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err) from error

    # Re-read state after dispatch (it may already be in "running" state)
    return get_run(request.app.state.settings, project_id, run_id)


# ---------------------------------------------------------------------------
# Progress (Stage E)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/progress", response_model=RunProgress)
def progress(project_id: str, run_id: str, request: Request) -> RunProgress:
    """Pollable progress endpoint for a run."""
    try:
        state = get_run(request.app.state.settings, project_id, run_id)
    except RunNotFoundError as error:
        err = get_error("RUN_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error
    return build_progress(state)


# ---------------------------------------------------------------------------
# Cancel / Retry (Stage E)
# ---------------------------------------------------------------------------


@router.delete("/{run_id}", response_model=RunState, dependencies=[Depends(require_project_api_role("member"))])
def cancel(project_id: str, run_id: str, request: Request) -> RunState:
    """Request cancellation of a running or queued run."""
    try:
        return cancel_run(request.app.state.settings, project_id, run_id)
    except RunNotFoundError as error:
        err = get_error("RUN_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error
    except RunAlreadyExecutedError as error:
        err = get_error("RUN_ALREADY_CANCELLED")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err) from error
    except RunCancelTooLateError as error:
        err = get_error("RUN_CANCEL_TOO_LATE")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err) from error


@router.post("/{run_id}/retry", response_model=RunState, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_project_api_role("member"))])
def retry(project_id: str, run_id: str, request: Request) -> RunState:
    """Retry a failed or cancelled run.  Creates a new queued run."""
    try:
        return retry_run(request.app.state.settings, project_id, run_id)
    except RunNotFoundError as error:
        err = get_error("RUN_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error
    except RunWrongStatusError as error:
        err = get_error("RUN_WRONG_STATUS")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err) from error


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


@router.get("/{run_id}/artifacts/{artifact_name}")
def download_artifact(project_id: str, run_id: str, artifact_name: str, request: Request) -> FileResponse:
    if artifact_name not in {"report", "risk_csv", "next_week_plan", "result"}:
        err = get_error("NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
    try:
        run = get_run(request.app.state.settings, project_id, run_id)
    except (ValueError, RunNotFoundError) as error:
        err = get_error("RUN_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error
    relative_path = run.artifacts.get(artifact_name)
    if relative_path is None:
        err = get_error("NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
    path = ensure_project_path(request.app.state.settings.output_root, project_id, *relative_path.split("/"))
    if not path.is_file():
        err = get_error("NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
    return FileResponse(path, filename=path.name)
