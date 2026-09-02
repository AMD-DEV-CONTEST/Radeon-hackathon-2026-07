"""Redaction event review endpoints (contract section 8).

Every event mutation bumps project.revision, appends a review_history entry,
sets exports_stale=True and saves the project. Optimistic concurrency uses
expected_revision (409 on mismatch).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from policycut.core.ids import new_id
from policycut.core.models import BoxKeyframe, RedactionEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store(request: Request):
    return request.app.state.store


def _get_project_or_404(store, project_id: str):
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


def _check_revision(project, expected_revision: int) -> None:
    if int(expected_revision) != int(project.revision):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "revision_conflict",
                "current_revision": int(project.revision),
                "message": (
                    f"Expected revision {expected_revision} but the project is at "
                    f"revision {project.revision}; reload events and retry."
                ),
            },
        )


def _commit_mutation(store, project, action: str, extra: Optional[dict] = None) -> None:
    """Bump revision, record history, mark exports stale and persist."""
    project.revision = int(project.revision) + 1
    project.exports_stale = True
    project.updated_at = _utcnow()
    store.save_project(project)
    entry = {"ts": _utcnow(), "action": action, "revision": project.revision}
    entry.update(extra or {})
    try:
        store.append_review_history(project.id, entry)
    except Exception:
        logger.debug("could not append review history", exc_info=True)


def _parse_boxes(raw: list) -> list[BoxKeyframe]:
    boxes: list[BoxKeyframe] = []
    for item in raw:
        try:
            boxes.append(BoxKeyframe.model_validate(item))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid box keyframe: {exc}")
    return boxes


class EventCreateBody(BaseModel):
    expected_revision: int
    kind: Literal["visual", "audio"]
    category: str = "manual"
    start_s: float
    end_s: float
    action: Optional[dict] = None
    boxes: list[dict] = Field(default_factory=list)
    text_preview: str = ""


class EventPatchBody(BaseModel):
    expected_revision: int
    status: Optional[Literal["pending", "confirmed", "ignored"]] = None
    action: Optional[dict] = None
    start_s: Optional[float] = None
    end_s: Optional[float] = None
    category: Optional[str] = None
    boxes: Optional[list[dict]] = None


class RevisionBody(BaseModel):
    expected_revision: int


@router.get("/projects/{project_id}/events")
def list_events(project_id: str, request: Request) -> dict:
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    events = store.load_events(project_id) or []
    return {
        "events": [e.model_dump() for e in events],
        "revision": int(project.revision),
    }


@router.post("/projects/{project_id}/events")
def create_event(project_id: str, body: EventCreateBody, request: Request):
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    _check_revision(project, body.expected_revision)
    if body.end_s <= body.start_s:
        raise HTTPException(status_code=400, detail="end_s must be greater than start_s")

    if body.kind == "visual":
        if not body.boxes:
            raise HTTPException(
                status_code=400, detail="Visual manual events require at least one box"
            )
        event = RedactionEvent(
            id=new_id("e"),
            kind="visual",
            category=body.category or "manual",
            status="confirmed",
            source="manual",
            start_s=float(body.start_s),
            end_s=float(body.end_s),
            action=body.action or {"type": "pixelate", "strength": 65},
            confidence=1.0,
            boxes=_parse_boxes(body.boxes),
            manual_fixed_region=True,
        )
    else:
        event = RedactionEvent(
            id=new_id("e"),
            kind="audio",
            category=body.category or "manual",
            status="confirmed",
            source="manual",
            start_s=float(body.start_s),
            end_s=float(body.end_s),
            action=body.action or {"type": "mute"},
            confidence=1.0,
            text_preview=body.text_preview or "MANUAL",
        )

    events = store.load_events(project_id) or []
    events.append(event)
    store.save_events(project_id, events)
    _commit_mutation(store, project, "add_event", {"event_id": event.id, "kind": event.kind})
    return event


@router.patch("/projects/{project_id}/events/{event_id}")
def patch_event(project_id: str, event_id: str, body: EventPatchBody, request: Request):
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    _check_revision(project, body.expected_revision)

    events = store.load_events(project_id) or []
    event = next((e for e in events if e.id == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")

    changes: dict = {}
    if body.status is not None:
        event.status = body.status
        changes["status"] = body.status
    if body.action is not None:
        if not isinstance(body.action, dict) or "type" not in body.action:
            raise HTTPException(status_code=422, detail="action must be a dict with a 'type'")
        event.action = body.action
        changes["action"] = body.action
    if body.start_s is not None:
        event.start_s = float(body.start_s)
        changes["start_s"] = event.start_s
    if body.end_s is not None:
        event.end_s = float(body.end_s)
        changes["end_s"] = event.end_s
    if body.category is not None:
        event.category = body.category
        changes["category"] = body.category
    if body.boxes is not None:
        event.boxes = _parse_boxes(body.boxes)
        changes["boxes"] = len(event.boxes)
    if event.end_s <= event.start_s:
        raise HTTPException(status_code=400, detail="end_s must be greater than start_s")

    store.save_events(project_id, events)
    _commit_mutation(store, project, "patch_event", {"event_id": event_id, "changes": changes})
    return event


@router.delete("/projects/{project_id}/events/{event_id}", status_code=204)
def delete_event(
    project_id: str,
    event_id: str,
    request: Request,
    expected_revision: int = Query(...),
) -> Response:
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    _check_revision(project, expected_revision)

    events = store.load_events(project_id) or []
    event = next((e for e in events if e.id == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")

    if event.source == "manual":
        events = [e for e in events if e.id != event_id]
        action = "delete_event"
    else:
        # Auto events are never deleted; they are marked ignored instead.
        event.status = "ignored"
        action = "ignore_event"

    store.save_events(project_id, events)
    _commit_mutation(store, project, action, {"event_id": event_id})
    return Response(status_code=204)


@router.post("/projects/{project_id}/review/confirm-all")
def confirm_all(project_id: str, body: RevisionBody, request: Request) -> dict:
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    _check_revision(project, body.expected_revision)

    events = store.load_events(project_id) or []
    confirmed = 0
    for event in events:
        if event.status == "pending":
            event.status = "confirmed"
            confirmed += 1
    if confirmed:
        store.save_events(project_id, events)
        _commit_mutation(store, project, "confirm_all", {"count": confirmed})
    return {"confirmed": confirmed, "revision": int(project.revision)}


@router.post("/projects/{project_id}/review/complete")
def complete_review(project_id: str, request: Request):
    store = _store(request)
    project = _get_project_or_404(store, project_id)
    events = store.load_events(project_id) or []
    pending_auto = [e for e in events if e.source == "auto" and e.status == "pending"]
    if pending_auto:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(pending_auto)} auto-detected events are still pending review; "
                "confirm or ignore them first"
            ),
        )
    project.updated_at = _utcnow()
    store.save_project(project)
    try:
        store.append_review_history(
            project_id, {"ts": _utcnow(), "action": "review_complete"}
        )
    except Exception:
        logger.debug("could not append review history", exc_info=True)
    return project
