"""
Phase H — 任务看板 API

提供按状态、负责人、优先级、截止日期进行筛选/排序/分组的任务看板视图。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request

from app.schemas.models import TaskBoardResponse
from app.security.permissions import get_current_user, require_project_role
from app.services.task_lifecycle import TaskLifecycleService

router = APIRouter(prefix="/projects/{project_id}/board", tags=["task-board"])


def _task_db_path(settings, project_id: str) -> Path:
    sqlite_path = Path(settings.sqlite_path)
    sqlite_root = sqlite_path if sqlite_path.is_dir() else sqlite_path.parent
    return sqlite_root / "projects" / project_id / "tasks.db"


@router.get("/tasks", response_model=TaskBoardResponse, dependencies=[Depends(require_project_role("guest"))])
async def get_task_board(
    project_id: str,
    request: Request,
    status: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    due_before: str | None = Query(default=None),
    due_after: str | None = Query(default=None),
    sort_by: str = Query(default="due_date"),
    sort_order: str = Query(default="asc"),
    group_by: str | None = Query(default=None),
    search: str | None = Query(default=None),
    _: dict = Depends(get_current_user),
):
    """Task board with filter/sort/group capabilities.

    Parameters:
    - status: filter by task status
    - owner: filter by owner name
    - priority: filter by priority level
    - due_before / due_after: date range filters (ISO format)
    - sort_by: due_date | priority | title | status | created_at
    - sort_order: asc | desc
    - group_by: owner | status | priority (optional grouping)
    - search: text search in task title
    """
    # Locate the project's task DB
    settings = request.app.state.settings
    task_db = _task_db_path(settings, project_id)

    # Always report filters that were requested
    filters_applied: dict = {}
    if status:
        filters_applied["status"] = status
    if owner:
        filters_applied["owner"] = owner
    if priority:
        filters_applied["priority"] = priority
    if due_before:
        filters_applied["due_before"] = due_before
    if due_after:
        filters_applied["due_after"] = due_after
    if search:
        filters_applied["search"] = search

    if not task_db.exists():
        return TaskBoardResponse(project_id=project_id, groups={}, total_count=0, filters_applied=filters_applied)

    tsvc = TaskLifecycleService(task_db)
    task_records = tsvc.list_tasks(project_id)
    # Convert TaskRecord objects to dicts
    tasks = [t.model_dump() if hasattr(t, "model_dump") else t for t in task_records]

    # Normalize status for records where status might be an object
    for t in tasks:
        if isinstance(t.get("status"), dict):
            t["status"] = t["status"].get("value", str(t["status"]))
        elif hasattr(t.get("status"), "value"):
            t["status"] = t["status"].value  # type: ignore

    # Apply filters (filters_applied already populated above)
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    if owner:
        tasks = [t for t in tasks if (t.get("owner") or "").lower() == owner.lower()]
    if priority:
        tasks = [t for t in tasks if t.get("priority") == priority]
    if due_before:
        tasks = [t for t in tasks if (t.get("due_date") or "") <= due_before]
    if due_after:
        tasks = [t for t in tasks if (t.get("due_date") or "") >= due_after]
    if search:
        term = search.lower()
        tasks = [t for t in tasks if term in (t.get("title") or "").lower()]

    # Sort
    reverse = sort_order == "desc"
    allowed_sort = {"due_date", "priority", "title", "status", "created_at"}
    key_field = sort_by if sort_by in allowed_sort else "due_date"

    # Priority ordering for sorting
    _prio = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def _sort_key(t: dict):
        val = t.get(key_field, "")
        if key_field == "priority":
            return _prio.get(val or "", 99)
        return val or ""

    tasks = sorted(tasks, key=_sort_key, reverse=reverse)

    # Build cards
    cards: list[dict] = []
    for t in tasks:
        cards.append({
            "task_id": t.get("id", ""),
            "title": t.get("title", ""),
            "owner": t.get("owner"),
            "due_date": t.get("due_date"),
            "priority": t.get("priority"),
            "status": t.get("status", ""),
            "comment_count": 0,
            "risk_level": "low",
        })

    # Group
    groups: dict[str, list[dict]] = {}
    if group_by:
        for card in cards:
            key = card.get(group_by) or "unknown"
            groups.setdefault(key, []).append(card)
    else:
        groups["all"] = cards

    return TaskBoardResponse(
        project_id=project_id,
        groups=groups,
        total_count=len(cards),
        filters_applied=filters_applied,
    )
