"""Story-time anchor and partial-order relation API."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import get_current_user_role, require_capability
from app.deployment import Capability, EffectivePrincipal
from app.models import (
    ChapterTemporalContextUpdate,
    EntityStateSegmentCreate,
    TemporalEventMetadataUpdate,
    TemporalAnchorCreate,
    TemporalRelationCreate,
    TimelineCreate,
)
from services.temporal import (
    TemporalError,
    create_anchor,
    create_relation,
    create_state_segment,
    create_timeline,
    get_event_metadata,
    get_chapter_context,
    list_anchors,
    list_relations,
    list_timelines,
    resolve_entity_state,
    set_chapter_context,
    set_event_metadata,
    state_history,
)


router = APIRouter(prefix="/api/temporal", tags=["temporal"])
context_router = APIRouter(tags=["temporal-context"])


def _handle(exc):
    if isinstance(exc, TemporalError):
        status = 404 if exc.code.endswith("NOT_FOUND") else 409
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.safe_message})
    raise exc


@router.post("/anchors", status_code=201)
def api_create_anchor(
    payload: TemporalAnchorCreate,
    _: EffectivePrincipal = Depends(require_capability(Capability.MANAGE_TEMPORAL)),
):
    try:
        return {"anchor": create_anchor(payload.model_dump())}
    except TemporalError as exc:
        _handle(exc)


@router.get("/anchors")
def api_list_anchors(
    database_id: str,
    book_id: str,
    timeline_id: str = None,
    branch_id: str = None,
    role: str = Depends(get_current_user_role),
):
    try:
        return list_anchors(database_id, book_id, timeline_id, branch_id)
    except TemporalError as exc:
        _handle(exc)


@router.post("/timelines", status_code=201)
def api_create_timeline(
    payload: TimelineCreate,
    _: EffectivePrincipal = Depends(require_capability(Capability.MANAGE_TEMPORAL)),
):
    try:
        return {"timeline": create_timeline(payload.model_dump())}
    except TemporalError as exc:
        _handle(exc)


@router.get("/timelines")
def api_list_timelines(
    database_id: str,
    book_id: str,
    role: str = Depends(get_current_user_role),
):
    try:
        return list_timelines(database_id, book_id)
    except TemporalError as exc:
        _handle(exc)


@router.post("/relations", status_code=201)
def api_create_relation(
    payload: TemporalRelationCreate,
    _: EffectivePrincipal = Depends(require_capability(Capability.MANAGE_TEMPORAL)),
):
    try:
        return {"relation": create_relation(payload.model_dump())}
    except TemporalError as exc:
        _handle(exc)


@router.get("/relations")
def api_list_relations(
    database_id: str,
    book_id: str,
    timeline_id: str,
    branch_id: str = None,
    role: str = Depends(get_current_user_role),
):
    try:
        return list_relations(database_id, book_id, timeline_id, branch_id)
    except TemporalError as exc:
        _handle(exc)


@router.post("/state-segments", status_code=201)
def api_create_state_segment(
    payload: EntityStateSegmentCreate,
    _: EffectivePrincipal = Depends(require_capability(Capability.MANAGE_TEMPORAL)),
):
    try:
        return {"segment": create_state_segment(payload.model_dump())}
    except TemporalError as exc:
        _handle(exc)


@router.put("/events/{event_id}/metadata")
def api_set_event_metadata(
    event_id: str,
    payload: TemporalEventMetadataUpdate,
    _: EffectivePrincipal = Depends(require_capability(Capability.MANAGE_TEMPORAL)),
):
    try:
        return {"metadata": set_event_metadata(event_id, payload.model_dump())}
    except TemporalError as exc:
        _handle(exc)


@router.get("/events/{event_id}/metadata")
def api_get_event_metadata(
    event_id: str,
    database_id: str,
    book_id: str,
    role: str = Depends(get_current_user_role),
):
    try:
        return {"metadata": get_event_metadata(database_id, book_id, event_id)}
    except TemporalError as exc:
        _handle(exc)


@context_router.get("/api/entities/{entity_id}/resolved-state")
def api_resolved_entity_state(
    entity_id: str,
    database_id: str,
    book_id: str,
    timeline_id: str = None,
    branch_id: str = None,
    anchor_id: str = None,
    chapter_id: str = None,
    role: str = Depends(get_current_user_role),
):
    try:
        return resolve_entity_state(
            database_id, book_id, entity_id, timeline_id, branch_id, anchor_id, chapter_id
        )
    except TemporalError as exc:
        _handle(exc)


@context_router.get("/api/entities/{entity_id}/state-history")
def api_entity_state_history(
    entity_id: str,
    database_id: str,
    book_id: str,
    timeline_id: str = None,
    branch_id: str = None,
    role: str = Depends(get_current_user_role),
):
    try:
        return state_history(database_id, book_id, entity_id, timeline_id, branch_id)
    except TemporalError as exc:
        _handle(exc)


@context_router.get("/api/chapters/{chapter_id}/temporal-context")
def api_get_chapter_temporal_context(
    chapter_id: str,
    database_id: str,
    book_id: str,
    role: str = Depends(get_current_user_role),
):
    try:
        return {"context": get_chapter_context(database_id, book_id, chapter_id)}
    except TemporalError as exc:
        _handle(exc)


@context_router.put("/api/chapters/{chapter_id}/temporal-context")
def api_set_chapter_temporal_context(
    chapter_id: str,
    payload: ChapterTemporalContextUpdate,
    _: EffectivePrincipal = Depends(require_capability(Capability.MANAGE_TEMPORAL)),
):
    try:
        return {"context": set_chapter_context(chapter_id, payload.model_dump())}
    except TemporalError as exc:
        _handle(exc)
