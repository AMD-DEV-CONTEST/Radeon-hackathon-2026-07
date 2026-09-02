"""Authenticated, confirmation-gated Stage I integration endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.integrations.base import ConfirmationRequired
from app.integrations.email import EmailConnector
from app.integrations.scm import SCMConnector
from app.integrations.webhook import WebhookRegistry
from app.security.permissions import get_current_user, get_project_role, has_min_role

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _db(request: Request, name: str) -> str:
    db_path = Path(request.app.state.db_path)
    db_dir = db_path.parent if db_path.parent.name else db_path
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / name)


def _require_project_role(request: Request, user: dict, project_id: str, role: str) -> None:
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    actual = get_project_role(str(request.app.state.db_path), project_id, user["user_id"])
    if not has_min_role(actual, role):
        raise HTTPException(status_code=403, detail="Project role does not permit this integration action")


@router.post("/email/preview")
async def email_preview(payload: dict, request: Request, user: dict = Depends(get_current_user)):
    """Create an email preview and a one-time confirmation ID; never sends mail."""
    _require_project_role(request, user, str(payload.get("project_id", "")), "member")
    try:
        preview = EmailConnector(db_path=_db(request, "integration_email.db")).preview_diff(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "preview": preview}


@router.post("/email/execute")
async def email_execute(payload: dict, request: Request, user: dict = Depends(get_current_user)):
    """Send only the exact email that was previously previewed and confirmed."""
    _require_project_role(request, user, str(payload.get("project_id", "")), "member")
    confirmation_id = str(payload.pop("confirmation_id", ""))
    if not confirmation_id:
        raise HTTPException(status_code=400, detail="confirmation_id from /email/preview is required")
    result = EmailConnector(db_path=_db(request, "integration_email.db")).execute(payload, confirmation_id)
    if result.status.name == "FAILED":
        raise HTTPException(status_code=409, detail=result.summary)
    return {"ok": True, "summary": result.summary, "details": result.details}


@router.post("/webhook/register")
async def webhook_register(payload: dict, request: Request, user: dict = Depends(get_current_user)):
    """Persist a validated webhook. Registration never dispatches a network event."""
    project_id = str(payload.get("project_id", ""))
    _require_project_role(request, user, project_id, "pm")
    url, events, secret = payload.get("url", ""), payload.get("events", []), payload.get("secret", "")
    if not url or not events:
        raise HTTPException(status_code=400, detail="url and events are required")
    try:
        reg = WebhookRegistry(db_path=_db(request, "integration_webhooks.db")).register(
            str(url), list(events), str(secret), project_id=project_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "webhook": {
        "id": reg.id, "project_id": reg.project_id, "url": reg.url,
        "events": reg.events, "active": reg.active,
        "created_at": reg.created_at, "updated_at": reg.updated_at,
    }}


@router.post("/scm/preview")
async def scm_preview(payload: dict, request: Request, user: dict = Depends(get_current_user)):
    """Preview an SCM write and return its server-side confirmation ID."""
    _require_project_role(request, user, str(payload.get("project_id", "")), "member")
    connector = SCMConnector(db_path=_db(request, "integration_scm.db"))
    try:
        connector.preview_diff(payload)
    except ConfirmationRequired as required:
        return {"ok": True, "preview": required.details.get("diff", {}), "confirmation_id": required.details["confirmation_id"]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail="Unable to create SCM preview")


@router.post("/scm/execute")
async def scm_execute(payload: dict, request: Request, user: dict = Depends(get_current_user)):
    _require_project_role(request, user, str(payload.get("project_id", "")), "member")
    confirmation_id = str(payload.pop("confirmation_id", ""))
    if not confirmation_id:
        raise HTTPException(status_code=400, detail="confirmation_id from /scm/preview is required")
    result = SCMConnector(db_path=_db(request, "integration_scm.db")).execute(payload, confirmation_id)
    if result.status.name == "FAILED":
        raise HTTPException(status_code=409, detail=result.summary)
    return {"ok": True, "summary": result.summary, "details": result.details}
