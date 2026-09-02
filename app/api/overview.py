"""
Phase H.3 — 项目总览 API

聚合项目进度、风险、待确认、文档变更和最近运行记录。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.schemas.models import ProjectOverview
from app.security.permissions import get_current_user, require_project_role

router = APIRouter(prefix="/projects/{project_id}", tags=["overview"])


def _project_db_path(settings, project_id: str) -> Path:
    sqlite_path = Path(settings.sqlite_path)
    sqlite_root = sqlite_path if sqlite_path.is_dir() else sqlite_path.parent
    return sqlite_root / "projects" / project_id / "tasks.db"


def _connect_rows(db_path: str) -> list | None:
    """Try connecting to a SQLite DB. Returns rows (via fetchall) or None."""
    if not Path(db_path).exists():
        return None
    return None  # caller must handle


@router.get("/overview", response_model=ProjectOverview, dependencies=[Depends(require_project_role("guest"))])
async def get_project_overview(
    project_id: str,
    request: Request,
    _: dict = Depends(get_current_user),
):
    """Aggregated project dashboard overview.

    Includes:
    - Task statistics (by status)
    - Risk statistics (by severity)
    - Pending confirmation count
    - Recent document changes (last 5)
    - Recent run records (last 5)
    """
    settings = request.app.state.settings
    project_root = Path(settings.project_root)
    project_dir = project_root / project_id

    # Check project exists (via project.json)
    project_json = project_dir / "project.json"
    if not project_json.exists():
        raise HTTPException(status_code=404, detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"})

    with open(project_json, "r", encoding="utf-8") as f:
        pdata = json.load(f)
    project_name = pdata.get("name", project_id)

    # Task stats — read from tasks.db
    task_stats: dict[str, int] = {}
    task_db = _project_db_path(settings, project_id)
    if task_db.exists():
        conn = sqlite3.connect(str(task_db))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT status, COUNT(*) as cnt FROM task GROUP BY status").fetchall()
            task_stats = {r["status"]: r["cnt"] for r in rows}
            task_stats["total"] = sum(task_stats.values())
        finally:
            conn.close()

    # Risk stats — read from risks.db
    risk_stats: dict[str, int] = {}
    risk_db = task_db
    if risk_db.exists():
        conn = sqlite3.connect(str(risk_db))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT severity, COUNT(*) as cnt FROM risk_record WHERE lifecycle = 'active' GROUP BY severity"
            ).fetchall()
            risk_stats = {r["severity"]: r["cnt"] for r in rows}
            risk_stats["total_active"] = sum(risk_stats.values())
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    # Pending confirmations
    pending_confirmations = 0
    if task_db.exists():
        conn = sqlite3.connect(str(task_db))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM confirmation WHERE status = 'pending'").fetchone()
            pending_confirmations = row["cnt"] if row else 0
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    # Recent doc changes
    docs_db = task_db
    recent_doc_changes: list[dict] = []
    if docs_db.exists():
        conn = sqlite3.connect(str(docs_db))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT relative_path, sha256, is_current, last_seen_at FROM document_version "
                "ORDER BY last_seen_at DESC LIMIT 5"
            ).fetchall()
            recent_doc_changes = [
                {"path": r["relative_path"], "sha256": r["sha256"],
                 "is_current": bool(r["is_current"]), "last_seen": r["last_seen_at"]}
                for r in rows
            ]
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    # Recent runs
    runs_db = project_dir / "runs.db"
    recent_runs: list[dict] = []
    if runs_db.exists():
        conn = sqlite3.connect(str(runs_db))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT run_id, status, created_at, completed_at FROM run_state "
                "ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
            recent_runs = [
                {"run_id": r["run_id"], "status": r["status"],
                 "created_at": r["created_at"], "completed_at": r["completed_at"]}
                for r in rows
            ]
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    return ProjectOverview(
        project_id=project_id,
        project_name=project_name,
        task_stats=task_stats,
        risk_stats=risk_stats,
        pending_confirmations=pending_confirmations,
        recent_doc_changes=recent_doc_changes,
        recent_runs=recent_runs,
    )
