"""LLM Import API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from app.models import (
    ImportConfirmRequest,
    ImportPreviewRequest,
    ImportTaskConfirmRequest,
    ImportTaskCreateRequest,
    ImportTaskAnalysisRequest,
)
from services.db import get_db
from app.dependencies.auth import require_admin
from services.audit_log import log_event
from services.database_registry import get_active_book_id, get_active_database_id
import logging

from services.import_tasks import (
    ImportTaskError,
    cancel_import_task,
    confirm_import_task,
    create_import_task,
    get_import_task,
    list_import_tasks,
    retry_import_task,
    start_import_analysis,
)

router = APIRouter(tags=["import"])
log = logging.getLogger(__name__)


def _task_error(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail={"code": "IMPORT_TASK_NOT_FOUND", "message": "Import task not found"})
    if isinstance(exc, ImportTaskError):
        status = 404 if exc.code in {"DATABASE_NOT_FOUND", "BOOK_NOT_FOUND"} else 409
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.safe_message})
    raise exc


@router.post("/api/import/tasks", status_code=202)
def create_task(req: ImportTaskCreateRequest, _: None = Depends(require_admin)):
    """Create a durable parsing task. This endpoint never performs formal writes."""
    try:
        return {"task": create_import_task(req.model_dump())}
    except (ImportTaskError, KeyError) as exc:
        _task_error(exc)


@router.get("/api/import/tasks")
def get_tasks(limit: int = 50, _: None = Depends(require_admin)):
    return {"tasks": list_import_tasks(limit)}


@router.get("/api/import/tasks/{task_id}")
def get_task(task_id: str, _: None = Depends(require_admin)):
    try:
        return {"task": get_import_task(task_id)}
    except (ImportTaskError, KeyError) as exc:
        _task_error(exc)


@router.get("/api/import/tasks/{task_id}/preview")
def get_task_preview(task_id: str, _: None = Depends(require_admin)):
    try:
        task = get_import_task(task_id)
    except (ImportTaskError, KeyError) as exc:
        _task_error(exc)
    if task["status"] != "awaiting_confirmation" or task["preview"] is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "PREVIEW_NOT_READY", "message": "Import preview is not ready"},
        )
    return {"preview": task["preview"]}


@router.post("/api/import/tasks/{task_id}/cancel")
def cancel_task(task_id: str, _: None = Depends(require_admin)):
    try:
        return {"task": cancel_import_task(task_id)}
    except (ImportTaskError, KeyError) as exc:
        _task_error(exc)


@router.post("/api/import/tasks/{task_id}/retry", status_code=202)
def retry_task(task_id: str, _: None = Depends(require_admin)):
    try:
        return {"task": retry_import_task(task_id)}
    except (ImportTaskError, KeyError) as exc:
        _task_error(exc)


@router.post("/api/import/tasks/{task_id}/confirm")
def confirm_task(task_id: str, req: ImportTaskConfirmRequest, _: None = Depends(require_admin)):
    try:
        return {"task": confirm_import_task(task_id, req.model_dump())}
    except (ImportTaskError, KeyError) as exc:
        _task_error(exc)


@router.post("/api/import/tasks/{task_id}/analyze", status_code=202)
def analyze_task(
    task_id: str,
    req: ImportTaskAnalysisRequest,
    _: None = Depends(require_admin),
):
    try:
        return {"task": start_import_analysis(task_id, req.analysis_mode)}
    except (ImportTaskError, KeyError) as exc:
        _task_error(exc)


@router.post("/api/import/preview")
def import_preview(req: ImportPreviewRequest, _: None = Depends(require_admin)):
    """Preview LLM extracted entities and relations."""
    try:
        from extractors import get_extractor
        config = req.extractor_config or {}
        extractor = get_extractor(config)
        return extractor.extract(req.text)
    except Exception as exc:
        log.error("Import preview failed: %s", exc, exc_info=True)
        return {"entities": [], "relations": [], "error": "Import preview failed"}


@router.post("/api/import/confirm")
def import_confirm(req: ImportConfirmRequest, _: None = Depends(require_admin)):
    """Confirm imported entities and relations into the current database."""
    conn = get_db()
    try:
        book_id = get_active_book_id() or "default"
        from services.import_pipeline import ImportChangeSet, ImportPipeline

        changeset = ImportChangeSet(
            entities=[
                {
                    "title": ent.title,
                    "type": ent.type,
                    "content": ent.content,
                    "tags": ent.tags,
                    "importance": ent.importance,
                }
                for ent in req.entities
            ],
            relations=[
                {
                    "source": rel.source,
                    "target": rel.target,
                    "relation_type": rel.relation_type,
                    "description": rel.description,
                }
                for rel in req.relations
            ],
            book_id=book_id,
            source_type="legacy_import_confirm",
        )
        result = ImportPipeline().commit(
            changeset,
            db=conn,
            database_id=get_active_database_id(),
        )
        log_event(
            conn,
            "import.confirm",
            f"Import confirmed: {result['created_entities']} entities, {result['created_relations']} relations",
            target="import.confirm",
            database_id=get_active_database_id(),
            book_id=book_id,
            success=True,
        )
        return {
            "success": True,
            "created_entities": result["created_entities"],
            "created_relations": result["created_relations"],
            "vector_indexed": bool(result.get("vector_indexed")),
            "vector_task_id": result.get("vector_task_id"),
        }
    except Exception as exc:
        conn.rollback()
        log.error("Import confirm failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Import confirm failed")
    finally:
        conn.close()
