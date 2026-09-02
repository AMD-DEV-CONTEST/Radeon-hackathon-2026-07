"""Authenticated automation task endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.security.permissions import get_current_user, get_project_role, has_min_role
from app.services.automation_tasks import AutomationTaskService

router = APIRouter(prefix="/api", tags=["automation-tasks"])


def _get_service(request: Request) -> AutomationTaskService:
    db_path = Path(request.app.state.db_path)
    db_dir = db_path.parent if db_path.parent.name else db_path
    db_dir.mkdir(parents=True, exist_ok=True)
    return AutomationTaskService(str(db_dir / "automation_tasks.db"))


def _check(request: Request, user: dict, project_id: str, role: str) -> None:
    actual = get_project_role(str(request.app.state.db_path), project_id, user["user_id"])
    if not has_min_role(actual, role):
        raise HTTPException(status_code=403, detail="Project role does not permit this automation action")


def _task_project(service: AutomationTaskService, task_id: str) -> str:
    try:
        return service.project_id_for_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Automation task {task_id} not found") from exc


@router.get("/projects/{project_id}/automation-tasks")
async def list_automation_tasks(project_id: str, request: Request, user: dict = Depends(get_current_user)):
    _check(request, user, project_id, "guest")
    tasks = _get_service(request).list_by_project(project_id)
    return {"ok": True, "project_id": project_id, "tasks": [t.__dict__ for t in tasks], "count": len(tasks)}


@router.post("/automation-tasks")
async def create_automation_task(payload: dict, request: Request, user: dict = Depends(get_current_user)):
    project_id, name = str(payload.get("project_id", "")), str(payload.get("name", ""))
    if not project_id or not name:
        raise HTTPException(status_code=400, detail="project_id and name are required")
    _check(request, user, project_id, "member")
    task = _get_service(request).create(project_id, name, str(payload.get("type", "on_demand")), payload.get("config"))
    return {"ok": True, "task": task.__dict__}


async def _mutate(task_id: str, action: str, request: Request, user: dict) -> dict:
    service = _get_service(request)
    _check(request, user, _task_project(service, task_id), "member")
    try:
        if action == "pause": result = service.pause(task_id).__dict__
        elif action == "resume": result = service.resume(task_id).__dict__
        elif action == "dry-run": result = service.dry_run(task_id)
        else: service.delete(task_id); result = {"message": f"Task {task_id} cancelled."}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


@router.post("/automation-tasks/{task_id}/pause")
async def pause_automation_task(task_id: str, request: Request, user: dict = Depends(get_current_user)):
    return {"ok": True, "task": await _mutate(task_id, "pause", request, user)}


@router.post("/automation-tasks/{task_id}/resume")
async def resume_automation_task(task_id: str, request: Request, user: dict = Depends(get_current_user)):
    return {"ok": True, "task": await _mutate(task_id, "resume", request, user)}


@router.post("/automation-tasks/{task_id}/dry-run")
async def dry_run_automation_task(task_id: str, request: Request, user: dict = Depends(get_current_user)):
    return {"ok": True, "dry_run": await _mutate(task_id, "dry-run", request, user)}


@router.post("/automation-tasks/{task_id}/delete")
async def delete_automation_task(task_id: str, request: Request, user: dict = Depends(get_current_user)):
    return {"ok": True, **(await _mutate(task_id, "delete", request, user))}


@router.get("/automation-tasks/{task_id}/audit")
async def audit_automation_task(task_id: str, request: Request, user: dict = Depends(get_current_user)):
    service = _get_service(request)
    _check(request, user, _task_project(service, task_id), "guest")
    log = service.audit_log(task_id)
    return {"ok": True, "task_id": task_id, "audit_log": log, "count": len(log)}
