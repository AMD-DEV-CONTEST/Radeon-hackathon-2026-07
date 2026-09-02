"""
Phase H — 风险中心 API

提供风险的生命周期管理、负责人分配和评论功能。
"""

from __future__ import annotations

import sqlite3
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.observability.error_codes import get_error
from app.schemas.models import RiskAssignmentRequest, RiskCenterEntry, RiskLifecycleUpdate
from app.security.permissions import get_current_user, require_project_role

router = APIRouter(prefix="/projects/{project_id}/risks", tags=["risks"])


def _risk_db_path(settings, project_id: str):
    from pathlib import Path
    sqlite_path = Path(settings.sqlite_path)
    sqlite_root = sqlite_path if sqlite_path.is_dir() else sqlite_path.parent
    return sqlite_root / "projects" / project_id / "tasks.db"


@router.get("", response_model=list[RiskCenterEntry])
async def list_risks(
    project_id: str,
    request: Request,
    severity: str | None = Query(default=None),
    lifecycle: str | None = Query(default=None),
    _: None = Depends(require_project_role("guest")),
    user: dict = Depends(get_current_user),
):
    """List risk records for a project, with optional severity/lifecycle filters."""
    from pathlib import Path
    settings = request.app.state.settings
    risk_db = _risk_db_path(settings, project_id)
    main_db = request.app.state.db_path

    results: list[dict] = []

    if risk_db.exists():
        conn = sqlite3.connect(str(risk_db))
        conn.row_factory = sqlite3.Row
        try:
            # Phase G tables share the project task DB and may not have been
            # initialised until the first monitoring scan.
            from app.services.risk_scanner import ensure_all
            ensure_all(conn)
            where = "1=1"
            params: list = []
            if severity:
                where += " AND rr.severity = ?"
                params.append(severity)
            if lifecycle:
                where += " AND rr.lifecycle = ?"
                params.append(lifecycle)

            rows = conn.execute(
                f"SELECT rr.* FROM risk_record rr "
                f"WHERE {where} ORDER BY rr.created_at DESC",
                params,
            ).fetchall()

            for r in rows:
                # Look up assignment from main DB
                assigned_to = None
                assignee_name = None
                mc = sqlite3.connect(main_db)
                mc.row_factory = sqlite3.Row
                try:
                    arow = mc.execute(
                        "SELECT ra.assigned_to, u.display_name as assignee_name "
                        "FROM risk_assignment ra LEFT JOIN user_account u ON ra.assigned_to = u.id "
                        "WHERE ra.risk_record_id = ?",
                        (r["id"],),
                    ).fetchone()
                    if arow:
                        assigned_to = arow["assigned_to"]
                        assignee_name = arow["assignee_name"]
                    cc = mc.execute(
                        "SELECT COUNT(*) as cnt FROM comment WHERE project_id = ? AND entity_type = 'risk' AND entity_id = ?",
                        (project_id, r["id"]),
                    ).fetchone()
                    comment_count = cc["cnt"] if cc else 0
                finally:
                    mc.close()

                results.append({
                    "record_id": r["id"],
                    "project_id": r["project_id"],
                    "title": r["title"],
                    "severity": r["severity"],
                    "lifecycle": r["lifecycle"],
                    "description": r["description"],
                    "assigned_to": assigned_to,
                    "assignee_name": assignee_name,
                    "comment_count": comment_count,
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                })
        finally:
            conn.close()

    return results


@router.put("/{risk_id}/assign", response_model=dict)
async def assign_risk(
    project_id: str,
    risk_id: str,
    body: RiskAssignmentRequest,
    request: Request,
    _: None = Depends(require_project_role("pm")),
    user: dict = Depends(get_current_user),
):
    """Assign a risk record to a user for handling."""
    from pathlib import Path
    settings = request.app.state.settings
    risk_db = _risk_db_path(settings, project_id)
    main_db = request.app.state.db_path

    # Verify risk exists in risk DB
    rconn = sqlite3.connect(str(risk_db))
    rconn.row_factory = sqlite3.Row
    try:
        risk = rconn.execute(
            "SELECT id, title FROM risk_record WHERE id = ?",
            (risk_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        rconn.close()
        raise HTTPException(status_code=404, detail="Risk record not found")
    rconn.close()
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk record not found")

    # Upsert assignment in main DB
    conn = sqlite3.connect(main_db)
    conn.row_factory = sqlite3.Row
    try:
        existing = conn.execute(
            "SELECT id FROM risk_assignment WHERE risk_record_id = ?",
            (risk_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE risk_assignment SET assigned_to = ?, assigned_by = ? WHERE risk_record_id = ?",
                (body.assignee_user_id, user["user_id"], risk_id),
            )
        else:
            conn.execute(
                "INSERT INTO risk_assignment (id, risk_record_id, assigned_to, assigned_by) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), risk_id, body.assignee_user_id, user["user_id"]),
            )
        conn.commit()

        # Notify assignee
        from app.services.notifications import NotificationService
        ntf = NotificationService(main_db)
        ntf.create_notification(
            recipient_id=body.assignee_user_id,
            kind="risk_assigned",
            title=f"You have been assigned a risk in project {project_id}",
            body=f"Risk: {risk['title']}",
            link=f"/projects/{project_id}/risks/{risk_id}",
        )
    finally:
        conn.close()

    return {"risk_id": risk_id, "assigned_to": body.assignee_user_id, "assigned_by": user["user_id"]}


@router.put("/{risk_id}/lifecycle", response_model=dict)
async def update_risk_lifecycle(
    project_id: str,
    risk_id: str,
    body: RiskLifecycleUpdate,
    request: Request,
    _: None = Depends(require_project_role("pm")),
    user: dict = Depends(get_current_user),
):
    """Transition a risk's lifecycle state.

    Valid actions: acknowledge, resolve, dismiss, reopen.
    """
    from pathlib import Path
    settings = request.app.state.settings
    risk_db = _risk_db_path(settings, project_id)
    main_db = request.app.state.db_path

    valid_transitions = {
        "acknowledge": "acknowledged",
        "resolve": "resolved",
        "dismiss": "dismissed",
        "reopen": "active",
    }
    new_state = valid_transitions.get(body.action)
    if new_state is None:
        raise HTTPException(status_code=400, detail=get_error("RISK_LIFECYCLE_INVALID"))

    if not risk_db.exists():
        raise HTTPException(status_code=404, detail="Risk record not found")

    conn = sqlite3.connect(str(risk_db))
    conn.row_factory = sqlite3.Row
    try:
        try:
            risk = conn.execute(
                "SELECT id, lifecycle FROM risk_record WHERE id = ?",
                (risk_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            raise HTTPException(status_code=404, detail="Risk record not found")

        if risk is None:
            raise HTTPException(status_code=404, detail="Risk record not found")

        conn.execute(
            "UPDATE risk_record SET lifecycle = ?, updated_at = datetime('now') WHERE id = ?",
            (new_state, risk_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Notify assignee if exists
    mc = sqlite3.connect(main_db)
    mc.row_factory = sqlite3.Row
    try:
        assignment = mc.execute(
            "SELECT assigned_to FROM risk_assignment WHERE risk_record_id = ?",
            (risk_id,),
        ).fetchone()
        if assignment and assignment["assigned_to"] != user["user_id"]:
            from app.services.notifications import NotificationService
            ntf = NotificationService(main_db)
            actor_name = user.get("username", "Someone")
            ntf.create_notification(
                recipient_id=assignment["assigned_to"],
                kind="risk_assigned",
                title=f"Risk {risk_id} was {body.action}d by {actor_name}",
                body=body.note,
                link=f"/projects/{project_id}/risks/{risk_id}",
            )
    finally:
        mc.close()

    return {"risk_id": risk_id, "previous_lifecycle": risk["lifecycle"], "new_lifecycle": new_state, "note": body.note}
